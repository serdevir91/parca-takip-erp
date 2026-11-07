"""QR codes for printed drawings, assembly sheets, labels and lists. Reading one only opens a confirmation with the
drawing; nothing is booked until the user confirms. Codes: P<project>-<part>, A<plan>-<part>, S<plan>-<item>-<step>."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..core import assembly as core
from ..core.assembly import EPS, Foy, Step
from ..core.i18n import tx
from ..core.status import KIND_HAZIR
from ..models import AssemblyPlan, AssemblyScan, Project, User
from . import assembly as svc

SOURCE_QR = "QR"
CODE = re.compile(r"(?:^|[/.])q[/.]([PAS])(\d+)-(\S+)$")


def part_url(base_url: str, project_id: int, part_no: str) -> str:
    return f"{base_url}/q/P{project_id}-{quote(part_no, safe='')}"


def plan_part_url(base_url: str, plan_id: int, part_no: str) -> str:
    return f"{base_url}/q/A{plan_id}-{quote(part_no, safe='')}"


def step_url(base_url: str, plan_id: int, item_id: int, step_no: int) -> str:
    return f"{base_url}/q/S{plan_id}-{item_id}-{step_no}"


def done_label(ctx: svc.Context, part_no: str) -> str:
    p = ctx.cat.get(part_no)
    return "Geldi" if p is not None and p.kind == KIND_HAZIR else "Üretildi"


@dataclass
class Mark:
    kind: str
    ctx: svc.Context
    plan: AssemblyPlan | None
    part_no: str = ""
    foy: Foy | None = None
    step: Step | None = None


def parse(text: str) -> tuple[str, int, str] | None:
    hit = CODE.search(text.strip())
    return (hit.group(1), int(hit.group(2)), hit.group(3)) if hit else None


def load(db: Session, kind: str, ref: int, rest: str) -> Mark:
    if kind == "P":
        project, plan = db.get(Project, ref), None
    else:
        plan = db.get(AssemblyPlan, ref)
        project = db.get(Project, plan.project_id) if plan is not None else None
    if project is None:
        raise HTTPException(404, tx("Bu QR kodun kaydı artık yok"))
    ctx = svc.context(db, project, plan)
    if kind == "S":
        assert plan is not None
        item, _, no = rest.partition("-")
        doc = ctx.docs[plan.id]
        foy = next((f for f in doc.foys if str(f.item_id) == item and not f.single), None)
        step = next((s for s in foy.steps if str(s.no) == no), None) if foy is not None else None
        if step is None:
            raise HTTPException(404, tx("Föyde bu adım yok"))
        return Mark("step", ctx, plan, step.part_no, foy, step)
    part_no = unquote(rest)
    if part_no not in ctx.cat:
        raise HTTPException(404, tx("{0} güncel BOM'da yok", part_no))
    return Mark("part", ctx, plan, part_no)


def _left(m: Mark) -> tuple[float, float]:
    """How many this code stands for, and how many of them are still open. Reading it twice books nothing new."""
    if m.plan is None:
        need = m.ctx.totals.get(m.part_no, 0)
        return need, max(need - m.ctx.ready(m.part_no), 0)
    p = next((x for x in m.ctx.docs[m.plan.id].picks if x.part_no == m.part_no), None)
    if p is None:
        raise HTTPException(404, tx("{0} güncel BOM'da yok", m.part_no))
    need = p.need + p.extra
    if any(x.part_no == m.part_no for x in m.plan.scans):
        return need, 0
    return need, max(need - p.ready - p.extra_ready, 0)


def _blocked(m: Mark) -> str:
    if m.plan is None:
        return ""
    if m.plan.status == core.DRAFT:
        return tx("Önce planı yayınlayın")
    return tx("Tamamlanan plan değiştirilemez") if m.plan.status == core.DONE else ""


def preview(m: Mark) -> dict[str, Any]:
    ctx = m.ctx
    d, warning = svc.pick_drawing(ctx, m.part_no)
    p = ctx.cat.get(m.part_no)
    out: dict[str, Any] = {
        "type": "mark", "kind": m.kind, "part_no": m.part_no, "name": p.name if p is not None else "",
        "project": ctx.project.name, "project_id": ctx.project.id, "plan_no": m.plan.no if m.plan is not None else None,
        "blocked": _blocked(m), "warnings": [warning] if warning else [], "rows": [],
        "drawing": None if d is None else {"id": d.id, "filename": d.filename, "rev": d.rev or "", "ext": d.ext.lower().lstrip(".")},
    }
    if m.kind == "part":
        qty, left = _left(m)
        return out | {"action": tx(done_label(ctx, m.part_no)), "qty": qty, "left": left, "done": left <= EPS}
    assert m.foy is not None and m.step is not None
    s = m.step
    short = [r for r in s.rows if r.state != core.READY and not r.mounted]
    if short:
        out["warnings"].append(tx("{0} kalem eksik görünüyor. Onaylarsanız takılmış sayılır.", len(short)))
    if any(not x.done for x in m.foy.steps if x.no < s.no):
        out["warnings"].append(tx("Önceki adımlar henüz bitmemiş"))
    out["rows"] = [{"part_no": r.part_no, "need": r.need, "ready": r.allocated, "mounted": r.mounted} for r in s.rows]
    return out | {"action": tx("Montaj tamam"), "step": tx("ADIM {0}/{1}", s.no, s.total), "foy": m.foy.part_no,
                  "qty": s.make, "left": 0 if s.done else s.make, "done": s.done}


def apply(db: Session, user: User, m: Mark) -> None:
    blocked = _blocked(m)
    if blocked:
        raise HTTPException(409, blocked)
    if m.kind == "part":
        _, left = _left(m)
        if left > EPS:
            q = svc.quantity_of(db, m.ctx, m.part_no)
            svc.set_ready(db, user, m.ctx, m.plan, m.part_no, q.ready_qty + left, SOURCE_QR)
            if m.plan is not None:
                m.plan.scans.append(AssemblyScan(part_no=m.part_no, qty=left, username=user.username))
        return
    assert m.plan is not None and m.foy is not None and m.step is not None
    s = m.step
    if s.done:
        return
    ops = [{"item_id": r.item_id, "path": r.path, "part_no": r.part_no, "mounted": True} for r in s.rows if not r.mounted]
    svc.apply_field(db, user, m.ctx, m.plan, ops, [{"item_id": m.foy.item_id, "path": s.path, "done": True}], SOURCE_QR)
