"""Montaj föyü: reads the BOM, tracking and quantities into core/assembly.py and books what comes back from the field.

Like `erp`, this does not commit; the caller commits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import assembly as core
from ..core.assembly import EPS, Doc, Extra, Foy, Part, PlanInput, PlanItem, Row, Step
from ..core.i18n import tx
from ..core.status import KIND_HAZIR, KIND_IMALAT, PROG_DONE, PROG_RUN, PROG_WAIT
from ..models import (AssemblyItem, AssemblyMark, AssemblyPlan, PartQuantity, Project, StockItem,
                      Tracking, User)
from . import audit, erp
from .state import ProjectView
from .tracking import apply_changes, tracking_of

SOURCE_SCREEN, SOURCE_EXCEL, SOURCE_PHOTO = "ekran", "Excel", "fotoğraf"
PENDING_PLAN = -1   # stands for "what if this were planned now" on the wizard
ALERT_DAYS = 7


def catalog(view: ProjectView) -> dict[str, Part]:
    """Every part and assembly of the BOM once. An assembly that sits in several places is read from its first place."""
    rows = [r for r in view.rows if not r.in_purchased]
    kids: dict[str, list[Any]] = {}
    for r in rows:
        kids.setdefault(r.parent_level or "", []).append(r)
    cat: dict[str, Part] = {}
    for r in rows:
        if r.fastener_key or r.part_no in cat or not r.part_no:
            continue
        is_asm = r.ext == "SLDASM"
        t = view.tracking.get(r.part_no)
        proc = view.procurement_of(r.part_no, r.procurement, is_asm, r.is_purchased_assembly)
        kind = view.base_kind(proc)
        info = view.drawing_info(r.part_no, r.rev)
        p = Part(r.part_no, proc, kind if kind in (KIND_IMALAT, KIND_HAZIR) else "", _material(r.material), r.rev or "",
                 view.part_names.get(r.part_no, ""), progress=t.progress if t else PROG_WAIT,
                 needs_drawing=not is_asm and view.needs_drawing(proc), has_drawing=info["has_drawing"],
                 drawing_rev=info["drawing_rev"], rev_mismatch=info["drawing_rev_mismatch"])
        if is_asm and not r.is_purchased_assembly:
            merged: dict[str, float] = {}
            for c in kids.get(r.level, []):
                if c.fastener_key:
                    p.fasteners.append(f"{c.fastener_desc or c.part_no} {c.fastener_size or ''} × {core.n(c.qty)}".replace("  ", " "))
                elif c.part_no:
                    merged[c.part_no] = merged.get(c.part_no, 0) + c.qty
            p.children = list(merged.items())
            p.is_asm = bool(p.children)
            if p.is_asm:
                p.procurement = "Alt montaj"
        cat[r.part_no] = p
    return cat


def _material(text: str | None) -> str:
    return "" if not text or "not specified" in text else text


def bom_totals(view: ProjectView) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in view.rows:
        if not r.in_purchased and not r.fastener_key:
            out[r.part_no] = out.get(r.part_no, 0) + r.total_qty
    return out


def plan_input(plan: AssemblyPlan) -> PlanInput:
    mounted = {(m.item_id, m.path, m.part_no): m.qty for m in plan.marks if m.part_no}
    done = {(m.item_id, m.path) for m in plan.marks if not m.part_no}
    return PlanInput(plan.id, [PlanItem(i.id, i.part_no, i.qty) for i in plan.items],
                     [Extra(e.id, e.part_no, e.qty, e.assembly_no, e.note) for e in plan.extras], mounted, done)


@dataclass
class Context:
    project: Project
    view: ProjectView
    cat: dict[str, Part]
    totals: dict[str, float]
    quantities: dict[str, PartQuantity]
    docs: dict[int, Doc]
    plans: list[AssemblyPlan]

    def ready(self, part_no: str) -> float:
        """Counted quantity, or the whole need when the part list says Tamamlandı."""
        q = self.quantities.get(part_no)
        stored = q.ready_qty if q else 0
        p = self.cat.get(part_no)
        return max(stored, self.totals.get(part_no, 0)) if p is not None and p.progress == PROG_DONE else stored

    def used(self, part_no: str) -> float:
        q = self.quantities.get(part_no)
        return q.used_qty if q else 0


def context(db: Session, project: Project, plan: AssemblyPlan | None = None,
            pending: PlanInput | None = None) -> Context:
    """Reserve for the published plans in the order they went out; a draft or a finished plan is read after them."""
    view = ProjectView.load(db, project)
    cat = catalog(view)
    quantities = {q.part_no: q for q in db.scalars(select(PartQuantity).where(PartQuantity.project_id == project.id))}
    plans = list(db.scalars(select(AssemblyPlan).where(AssemblyPlan.project_id == project.id,
                                                       AssemblyPlan.status == core.PUBLISHED)
                            .order_by(AssemblyPlan.published_at, AssemblyPlan.id)))
    ctx = Context(project, view, cat, bom_totals(view), quantities, {}, plans)
    parts = set(cat) | set(quantities)
    available = {p: ctx.ready(p) - ctx.used(p) for p in parts}
    inputs = [plan_input(p) for p in plans]
    if plan is not None and all(p.id != plan.id for p in plans):
        inputs.append(plan_input(plan))
    if pending is not None:
        inputs.append(pending)
    ctx.docs = core.allocate(cat, inputs, available)
    return ctx


# ---------- plans ----------

def next_no(db: Session, project_id: int) -> int:
    return (db.scalar(select(func.max(AssemblyPlan.no)).where(AssemblyPlan.project_id == project_id)) or 0) + 1


def candidates(db: Session, project: Project) -> list[dict[str, Any]]:
    """What the wizard offers: every assembly of the BOM with the quantity the main BOM asks for."""
    view = ProjectView.load(db, project)
    cat = catalog(view)
    totals = bom_totals(view)
    root = next((r for r in view.rows if r.depth == 0), None)
    depth: dict[str, int] = {}
    for r in view.rows:
        depth.setdefault(r.part_no, r.depth)
    names = [p for p, c in cat.items() if c.is_asm and p != (root.part_no if root else "")]
    ctx = context(db, project)
    open_plans = [plan_input(p) for p in ctx.plans]
    available = _available(ctx)
    out = []
    for part_no in names:
        # Each row answers on its own: would this one be ready if it were planned next?
        one = PlanInput(PENDING_PLAN, [PlanItem(1, part_no, totals.get(part_no, 1) or 1)])
        f = core.allocate(ctx.cat, [*open_plans, one], available)[PENDING_PLAN].foys[0]
        out.append({"part_no": part_no, "name": cat[part_no].name, "qty": f.qty, "depth": depth.get(part_no, 1),
                    "kinds": len({r.part_no for r in f.part_rows}), "percent": f.percent, "ready": f.ready,
                    "steps": len(f.steps)})
    return out


def _available(ctx: Context) -> dict[str, float]:
    return {p: ctx.ready(p) - ctx.used(p) for p in set(ctx.cat) | set(ctx.quantities)}


def lone_parts(view: ProjectView) -> list[dict[str, Any]]:
    """Parts sitting directly under the root: these can go on a plan without a föy."""
    cat = catalog(view)
    totals = bom_totals(view)
    return [{"part_no": r.part_no, "qty": totals.get(r.part_no, 1)} for r in view.rows
            if r.depth == 1 and r.part_no in cat and not cat[r.part_no].is_asm]


def set_items(db: Session, plan: AssemblyPlan, items: list[tuple[str, float]], cat: dict[str, Part]) -> None:
    names = [p for p, _ in items]
    if len(set(names)) != len(names):
        raise HTTPException(400, tx("Aynı montaj plana iki kez eklenemez"))
    for part_no, qty in items:
        if part_no not in cat:
            raise HTTPException(400, tx("{0} güncel BOM'da yok", part_no))
        if qty <= 0:
            raise HTTPException(400, tx("Montaj adedi sıfırdan büyük olmalı"))
    old = {i.part_no: i for i in plan.items}
    if plan.status != core.DRAFT and (set(old) != set(names) or any(abs(old[p].qty - q) > EPS for p, q in items)):
        raise HTTPException(409, tx("Yayınlanmış planda yalnızca rezervasyon sırası değişir"))
    plan.items[:] = [i for i in plan.items if i.part_no in set(names)]
    for seq, (part_no, qty) in enumerate(items, 1):
        row = old.get(part_no)
        if row is None:
            plan.items.append(AssemblyItem(part_no=part_no, qty=qty, seq=seq))
        else:
            row.qty, row.seq = qty, seq
    plan.items.sort(key=lambda i: i.seq)


def plan_out(plan: AssemblyPlan, doc: Doc | None = None) -> dict[str, Any]:
    out = {"id": plan.id, "project_id": plan.project_id, "no": plan.no, "plan_date": plan.plan_date.isoformat(),
           "responsible": plan.responsible, "checker": plan.checker, "status": plan.status, "notes": plan.notes,
           "drawing_mode": plan.drawing_mode, "rev": plan.edit_rev, "created_by": plan.created_by,
           "items": [{"id": i.id, "part_no": i.part_no, "qty": i.qty, "seq": i.seq} for i in plan.items],
           "extras": [{"id": e.id, "part_no": e.part_no, "qty": e.qty, "assembly_no": e.assembly_no, "note": e.note}
                      for e in plan.extras]}
    if doc is not None:
        out.update(percent=doc.percent, ready_count=sum(1 for f in doc.foys if f.ready and not f.done),
                   done_count=sum(1 for f in doc.foys if f.done), item_count=len(doc.foys))
    return out


def row_out(r: Row) -> dict[str, Any]:
    return {"item_id": r.item_id, "path": r.path, "poz": r.poz, "part_no": r.part_no, "qty": r.qty, "need": r.need,
            "is_sub": r.is_sub, "sub_step": r.sub_step, "temin": r.procurement, "kind": r.kind, "material": r.material,
            "rev": r.rev, "allocated": r.allocated, "mounted": r.mounted, "state": r.state, "notes": r.notes}


def step_out(s: Step) -> dict[str, Any]:
    return {"no": s.no, "total": s.total, "part_no": s.part_no, "path": s.path, "is_top": s.is_top, "parent": s.parent,
            "per_parent": s.per_parent, "make": s.make, "done": s.done, "ready": s.ready, "rows": [row_out(r) for r in s.rows]}


def foy_out(doc: Doc, f: Foy) -> dict[str, Any]:
    return {"item_id": f.item_id, "part_no": f.part_no, "qty": f.qty, "name": f.name, "rev": f.rev, "single": f.single,
            "ready": f.ready, "done": f.done, "percent": f.percent, "fasteners": f.fasteners,
            "kinds": len({r.part_no for r in f.part_rows}), "total": sum(r.need for r in f.part_rows),
            "ready_rows": sum(1 for r in f.part_rows if r.state == core.READY),
            "short_rows": sum(1 for r in f.part_rows if r.state != core.READY),
            "extra_note": core.extra_shortage_text(doc, f), "steps": [step_out(s) for s in f.steps]}


def uses_text(p: core.Pick) -> str:
    use = ", ".join(f"{k or tx('Ana montaj (doğrudan)')} ({core.n(q)})" for k, q in p.uses.items())
    return f"{use} + {core.n(p.extra)} {tx('ek')}" if p.extra else use


def doc_out(ctx: Context, doc: Doc) -> dict[str, Any]:
    picks = [{"part_no": p.part_no, "temin": p.procurement or tx("Belirtilmemiş"), "material": p.material, "rev": p.rev,
              "uses": uses_text(p), "need": p.need, "extra": p.extra, "ready": p.ready, "short": p.short, "status": p.status}
             for p in doc.picks]
    return {"foys": [foy_out(doc, f) for f in doc.foys], "picks": picks, "plan_total": doc.plan_total,
            "pick_total": doc.pick_total, "extra_total": doc.extra_total, "percent": doc.percent,
            "issues": core.check(core.sheet_of(doc), doc, ctx.cat)}


# ---------- quantities ----------

def _quantity(db: Session, ctx: Context, part_no: str) -> PartQuantity:
    q = ctx.quantities.get(part_no)
    if q is None:
        q = PartQuantity(project_id=ctx.project.id, part_no=part_no, ready_qty=ctx.ready(part_no), used_qty=0)
        db.add(q)
        ctx.quantities[part_no] = q
    elif q.ready_qty < ctx.ready(part_no):
        q.ready_qty = ctx.ready(part_no)
    return q


def _sync_progress(db: Session, user: User, ctx: Context, part_no: str, wanted: str | None = None) -> None:
    """The part list keeps telling the same story: all there is Tamamlandı, some is Devam ediyor."""
    q = ctx.quantities[part_no]
    need = ctx.totals.get(part_no, 0)
    if need > 0 and q.ready_qty >= need - EPS:
        progress = PROG_DONE
    elif q.ready_qty > EPS:
        progress = PROG_RUN
    else:
        progress = wanted or PROG_WAIT
    t = tracking_of(db, ctx.project.id, part_no)
    if t.progress != progress:
        apply_changes(db, user, t, {"progress": progress})
        p = ctx.cat.get(part_no)
        if p is not None:
            p.progress = progress


def _log(db: Session, user: User, ctx: Context, plan: AssemblyPlan | None, what: str, old: Any, new: Any, source: str) -> None:
    where = f"{source}, plan {plan.no}" if plan is not None else source
    audit.record(db, user, "assembly_plan", plan.id if plan is not None else 0, what[:100], old, f"{new} ({where})", ctx.project.id)


def set_ready(db: Session, user: User, ctx: Context, plan: AssemblyPlan | None, part_no: str, ready: float, source: str,
              wanted: str | None = None) -> None:
    q = _quantity(db, ctx, part_no)
    old = q.ready_qty
    q.ready_qty = max(ready, q.used_qty, 0)
    q.updated_by = user.username
    if abs(old - q.ready_qty) > EPS:
        _log(db, user, ctx, plan, f"{part_no}: hazır", core.n(old), core.n(q.ready_qty), source)
    _sync_progress(db, user, ctx, part_no, wanted)


def quantities_out(ctx: Context) -> list[dict[str, Any]]:
    reserved: dict[str, float] = {}
    extra: dict[str, float] = {}
    for doc in ctx.docs.values():
        for f in doc.foys:
            for r in f.rows:
                if not r.mounted:
                    reserved[r.part_no] = reserved.get(r.part_no, 0) + r.allocated
        for e in doc.extras:
            extra[e.part_no] = extra.get(e.part_no, 0) + e.qty
            reserved[e.part_no] = reserved.get(e.part_no, 0) + getattr(e, "ready", 0)
    out = []
    for part_no, p in ctx.cat.items():
        q = ctx.quantities.get(part_no)
        out.append({"part_no": part_no, "temin": p.procurement or tx("Belirtilmemiş"), "is_asm": p.is_asm, "need": ctx.totals.get(part_no, 0),
                    "ready": ctx.ready(part_no), "reserved": reserved.get(part_no, 0), "used": ctx.used(part_no),
                    "extra": extra.get(part_no, 0), "progress": p.progress, "counted": q is not None})
    return out


def convert_preview(ctx: Context) -> list[dict[str, Any]]:
    """Row progress turned into quantities: Tamamlandı = the whole need. Nothing is written here."""
    return [{"part_no": p, "progress": c.progress, "ready": ctx.totals.get(p, 0)} for p, c in ctx.cat.items()
            if p not in ctx.quantities and c.progress == PROG_DONE]


def convert(db: Session, user: User, ctx: Context) -> int:
    rows = convert_preview(ctx)
    for r in rows:
        _quantity(db, ctx, r["part_no"]).updated_by = user.username
    audit.record(db, user, "assembly_plan", 0, "adet geçişi", None, f"{len(rows)} parça", ctx.project.id)
    return len(rows)


# ---------- field feedback ----------

def _take_from_stock(db: Session, user: User, ctx: Context, plan: AssemblyPlan, part_no: str, qty: float) -> float:
    item = db.scalar(select(StockItem).where(StockItem.code == part_no))
    take = min(item.qty, qty) if item is not None else 0
    if take > EPS:
        erp.move(db, user, item, "assembly", take, project_id=ctx.project.id, ref=f"Montaj planı {plan.no}", note=part_no)
    return max(take, 0)


def _give_back(db: Session, user: User, ctx: Context, plan: AssemblyPlan, part_no: str, qty: float) -> None:
    item = db.scalar(select(StockItem).where(StockItem.code == part_no))
    if item is not None and qty > EPS:
        erp.move(db, user, item, "assembly_return", qty, project_id=ctx.project.id, ref=f"Montaj planı {plan.no}", note=part_no)


def _row_of(doc: Doc, item_id: int, path: str, part_no: str) -> Row:
    for f in doc.foys:
        for s in f.steps:
            for r in s.rows:
                if r.item_id == item_id and r.path == path and r.part_no == part_no:
                    return r
    raise HTTPException(400, tx("Föyde bu satır yok: {0}", part_no))


def _step_of(doc: Doc, item_id: int, path: str) -> Step:
    for f in doc.foys:
        if f.item_id == item_id:
            for s in f.steps:
                if s.path == path and not f.single:
                    return s
    raise HTTPException(400, tx("Föyde bu adım yok"))


def apply_field(db: Session, user: User, ctx: Context, plan: AssemblyPlan, ops: list[dict[str, Any]],
                steps: list[dict[str, Any]], source: str) -> int:
    """Book what the paper says. A state box moves the part's counted quantity, mounting moves used_qty and stock,
    a built step adds to the assembly's own count. Allocation then runs again on the next read, in plan order."""
    if plan.status == core.DONE:
        raise HTTPException(409, tx("Tamamlanan plan değiştirilemez"))
    doc = ctx.docs[plan.id]
    marks = {(m.item_id, m.path, m.part_no): m for m in plan.marks}
    delta: dict[str, float] = {}
    wanted: dict[str, str] = {}
    changed = 0
    for op in ops:
        row = _row_of(doc, op["item_id"], op["path"], op["part_no"])
        target = op.get("ready_qty")
        state = op.get("state")
        if target is None and state is not None:
            target = row.need if state == core.READY else 0
        have = row.allocated
        if target is not None and not row.mounted and not row.is_sub:
            delta[row.part_no] = delta.get(row.part_no, 0) + min(target, row.need) - have
            have = min(target, row.need)
            changed += 1
        if state == core.RUNNING:
            wanted[row.part_no] = PROG_RUN
        mounted = op.get("mounted")
        if mounted is None or mounted == row.mounted:
            continue
        key = (row.item_id, row.path, row.part_no)
        changed += 1
        q = _quantity(db, ctx, row.part_no)
        if mounted:
            delta[row.part_no] = delta.get(row.part_no, 0) + max(row.need - have, 0)
            q.used_qty += row.need
            taken = 0 if row.is_sub else _take_from_stock(db, user, ctx, plan, row.part_no, row.need)
            mark = AssemblyMark(plan_id=plan.id, item_id=row.item_id, path=row.path, part_no=row.part_no, qty=row.need,
                                stock_qty=taken, username=user.username)
            plan.marks.append(mark)
        else:
            mark = marks[key]
            q.used_qty = max(q.used_qty - mark.qty, 0)
            _give_back(db, user, ctx, plan, row.part_no, mark.stock_qty)
            plan.marks.remove(mark)
        _log(db, user, ctx, plan, f"{row.part_no}: takıldı ({row.foy})", not mounted, mounted, source)
    for st in steps:
        s = _step_of(doc, st["item_id"], st["path"])
        done = bool(st["done"])
        if done == s.done:
            continue
        changed += 1
        if done:
            delta[s.part_no] = delta.get(s.part_no, 0) + s.make
            plan.marks.append(AssemblyMark(plan_id=plan.id, item_id=st["item_id"], path=s.path, part_no="", qty=s.make,
                                           username=user.username))
        else:
            mark = marks[(st["item_id"], s.path, "")]
            delta[s.part_no] = delta.get(s.part_no, 0) - mark.qty
            plan.marks.remove(mark)
        _log(db, user, ctx, plan, f"{s.part_no}: montajlandı", not done, done, source)
    for part_no in set(delta) | set(wanted):
        q = _quantity(db, ctx, part_no)
        set_ready(db, user, ctx, plan, part_no, q.ready_qty + delta.get(part_no, 0), source, wanted.get(part_no))
    db.flush()
    _finish_if_done(db, user, ctx, plan)
    return changed


def _finish_if_done(db: Session, user: User, ctx: Context, plan: AssemblyPlan) -> None:
    if plan.status != core.PUBLISHED or not plan.items:
        return
    built = {(m.item_id, m.path) for m in plan.marks if not m.part_no}
    mounted = {m.item_id for m in plan.marks if m.part_no}
    for f in ctx.docs[plan.id].foys:
        if not ((f.item_id in mounted) if f.single else (f.item_id, f.steps[-1].path) in built):
            return
    plan.status = core.DONE
    audit.record(db, user, "assembly_plan", plan.id, "status", core.PUBLISHED, core.DONE, ctx.project.id)


# ---------- dashboard and notifications ----------

def summary(db: Session, ctx: Context) -> dict[str, Any]:
    ready: list[dict[str, Any]] = []
    blocked: dict[str, dict[str, Any]] = {}
    plans = {p.id: p for p in ctx.plans}
    for pid, doc in ctx.docs.items():
        plan = plans[pid]
        for f in doc.foys:
            if f.done:
                continue
            if f.ready:
                ready.append({"plan_id": pid, "plan_no": plan.no, "part_no": f.part_no, "qty": f.qty, "name": f.name})
            for r in f.part_rows:
                if r.state != core.READY:
                    b = blocked.setdefault(r.part_no, {"part_no": r.part_no, "short": 0.0, "assemblies": [], "plan_id": pid})
                    b["short"] += r.need - min(r.allocated, r.need)
                    if f.part_no not in b["assemblies"]:
                        b["assemblies"].append(f.part_no)
    planned = done = 0
    for plan in db.scalars(select(AssemblyPlan).where(AssemblyPlan.project_id == ctx.project.id,
                                                      AssemblyPlan.status != core.DRAFT)):
        planned += len(plan.items)
        if plan.status == core.DONE:
            done += len(plan.items)
        elif plan.id in ctx.docs:
            done += sum(1 for f in ctx.docs[plan.id].foys if f.done)
    order = sorted(blocked.values(), key=lambda b: (-len(b["assemblies"]), -b["short"], b["part_no"]))
    return {"ready": ready, "blocking": order[:20], "planned": planned, "completed": done}


_alerts: dict[int, tuple[Any, list[dict[str, Any]]]] = {}


def _stamp(db: Session, project_id: int) -> tuple:
    return (db.scalar(select(func.max(Tracking.updated_at)).where(Tracking.project_id == project_id)),
            db.scalar(select(func.max(PartQuantity.updated_at)).where(PartQuantity.project_id == project_id)),
            db.scalar(select(func.max(AssemblyPlan.updated_at)).where(AssemblyPlan.project_id == project_id)),
            db.scalar(select(func.count(AssemblyMark.id)).join(AssemblyPlan).where(AssemblyPlan.project_id == project_id)))


def _aware(t: datetime | None) -> datetime | None:
    return t.replace(tzinfo=timezone.utc) if t is not None and t.tzinfo is None else t


def _project_alerts(db: Session, project: Project) -> list[dict[str, Any]]:
    """Which part, arriving lately, made which assemblies ready. Grouped by that part."""
    ctx = context(db, project)
    since = datetime.now(timezone.utc) - timedelta(days=ALERT_DAYS)
    changed: dict[str, datetime] = {}
    for part_no, t in ctx.view.tracking.items():
        if t.progress == PROG_DONE and (at := _aware(t.updated_at)) and at >= since:
            changed[part_no] = at
    for part_no, q in ctx.quantities.items():
        at = _aware(q.updated_at)
        if at and at >= since and q.ready_qty > EPS:
            changed[part_no] = max(at, changed.get(part_no, at))
    groups: dict[str, dict[str, Any]] = {}
    for plan in ctx.plans:
        for f in ctx.docs[plan.id].foys:
            if not f.ready or f.done or f.single:
                continue
            fresh = [r for r in f.part_rows if r.part_no in changed]
            if not fresh:
                continue
            last = max(fresh, key=lambda r: changed[r.part_no])
            g = groups.setdefault(last.part_no, {"project_id": project.id, "plan_id": plan.id, "part_no": last.part_no,
                                                 "kind": last.kind, "assemblies": [], "when": changed[last.part_no].date()})
            g["assemblies"].append(f.part_no)
    return list(groups.values())


def ready_alerts(db: Session) -> list[dict[str, Any]]:
    """Polled by every open screen, so a project is only worked out again after something in it changed."""
    ids = db.scalars(select(AssemblyPlan.project_id).where(AssemblyPlan.status == core.PUBLISHED).distinct()).all()
    out: list[dict[str, Any]] = []
    for pid in ids:
        stamp = _stamp(db, pid)
        cached = _alerts.get(pid)
        if cached is None or cached[0] != stamp:
            project = db.get(Project, pid)
            if project is None or project.current_version_id is None:
                continue
            cached = (stamp, _project_alerts(db, project))
            _alerts[pid] = cached
        out += cached[1]
    return out
