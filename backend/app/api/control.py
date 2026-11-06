"""Kontrol Listesi: automatic BOM checks merged with stored resolve state and manual issues (spec 8)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.control import (KIND_EMPTY_MATERIAL, KIND_EMPTY_TEMIN, KIND_MATERIAL_MISMATCH, KIND_NO_DRAWING, KIND_REV,
                            AutoIssue, check_bom)
from ..core.status import PROG_DONE
from ..models import ControlIssue, User
from ..services import audit
from ..services.settings import temin_choices
from ..services.state import ProjectView
from ..services.tracking import apply_changes, clean_changes, tracking_of
from ..permissions import require
from .deps import get_db, project_or_404
from app.core.i18n import tx

control_view, control_edit = require("control", "view"), require("control", "edit")
parts_edit = require("parts", "edit")

router = APIRouter(tags=["control"])

OPEN, RESOLVED = "Açık", "Çözüldü"
KIND_DRAWING_REV = "Resim revizyonu uyuşmuyor"
KIND_MANUAL = "Manuel"
SEVERITIES = ("error", "warning", "info")
# What the list can settle by itself, and which value it asks for
FIX_FIELD = {KIND_EMPTY_MATERIAL: "material", KIND_MATERIAL_MISMATCH: "material", KIND_EMPTY_TEMIN: "procurement",
             KIND_NO_DRAWING: "procurement", KIND_REV: "rev", KIND_DRAWING_REV: "rev"}
FIELD_LIMIT = {"material": 200, "rev": 32}


class ResolveIn(BaseModel):
    key: str
    note: str = ""


class FixIn(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=20000)
    value: str = Field(min_length=1, max_length=200)


class ManualIn(BaseModel):
    message: str = Field(min_length=1)
    part_no: str = ""
    kind: str = KIND_MANUAL
    severity: str = "warning"


def detect(view: ProjectView) -> list[AutoIssue]:
    """Automatic issues for the current BOM, plus drawing revision mismatches."""
    if view.version is None:
        return []
    parts = view.parts(include_in_purchased=False)
    issues = check_bom(view.to_parsed(), drawing_parts=set(view.drawings),
                       produced_parts={p["part_no"] for p in parts if p["progress"] == PROG_DONE},
                       procurement_of={p["part_no"]: p["procurement"] for p in parts},
                       drawing_temins=[t for t in view.temin if view.needs_drawing(t)])
    for p in parts:
        if p.get("drawing_rev_mismatch"):
            issues.append(AutoIssue(KIND_DRAWING_REV, p["part_no"],
                                    f"BOM revizyonu {p['rev'] or '-'}, resim revizyonu {p['drawing_rev'] or '-'}.",
                                    list(p["levels"]), choices=[p["drawing_rev"]] if p["drawing_rev"] else []))
    return issues


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _out(key: str, kind: str, part_no: str, message: str, levels: list, severity: str,
         row: ControlIssue | None, manual: bool = False, present: bool = True) -> dict[str, Any]:
    return {
        "key": key, "id": row.id if row else None, "kind": kind, "part_no": part_no, "message": message,
        "levels": levels, "severity": severity, "manual": manual, "present": present,
        "status": row.status if row else OPEN, "note": row.note if row else "",
        "resolved_by": row.resolved_by if row else "", "resolved_at": _iso(row.resolved_at) if row else None,
        "created_by": row.created_by if row else "", "fix": None,
    }


def _stored(db: Session, pid: int) -> dict[str, ControlIssue]:
    return {c.key: c for c in db.scalars(select(ControlIssue).where(ControlIssue.project_id == pid)
                                         .order_by(ControlIssue.id))}


@router.get("/projects/{pid}/control")
def control_list(pid: int, status: str | None = Query(None, description="Açık | Çözüldü"),
                 db: Session = Depends(get_db), user: User = Depends(control_view)) -> dict[str, Any]:
    view = ProjectView.load(db, project_or_404(db, pid))
    stored = _stored(db, pid)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in detect(view):
        if i.key in seen:
            continue
        seen.add(i.key)
        items.append({**_out(i.key, i.kind, i.part_no, i.message, i.levels, i.severity, stored.get(i.key)),
                      "fix": {"field": FIX_FIELD[i.kind], "choices": i.choices} if i.kind in FIX_FIELD else None})
    stale = []
    for key, c in stored.items():
        if c.manual:
            items.append(_out(key, c.kind, c.part_no, c.message, c.levels or [], c.severity, c, manual=True))
        elif key not in seen:
            stale.append(_out(key, c.kind, c.part_no, c.message, c.levels or [], c.severity, c, present=False))
    if status:
        items = [i for i in items if i["status"] == status]
    kinds: dict[str, int] = {}
    for i in items:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    return {
        "items": items, "stale": stale, "kinds": kinds,
        "materials": sorted({r.material for r in view.rows if r.material}), "temin": list(view.temin),
        "counts": {"total": len(items), "open": sum(1 for i in items if i["status"] == OPEN),
                   "resolved": sum(1 for i in items if i["status"] == RESOLVED),
                   "error": sum(1 for i in items if i["severity"] == "error" and i["status"] == OPEN)},
    }


def _find_or_create(db: Session, view: ProjectView, key: str, user: User) -> ControlIssue:
    pid = view.project.id
    row = db.scalar(select(ControlIssue).where(ControlIssue.project_id == pid, ControlIssue.key == key))
    if row is not None:
        return row
    issue = next((i for i in detect(view) if i.key == key), None)
    if issue is None:
        raise HTTPException(404, tx("Kontrol maddesi bulunamadı"))
    row = ControlIssue(project_id=pid, key=key, kind=issue.kind, part_no=issue.part_no, message=issue.message,
                       levels=list(issue.levels), severity=issue.severity, status=OPEN, manual=False,
                       present=True, created_by=user.username)
    db.add(row)
    db.flush()
    return row


@router.post("/projects/{pid}/control/resolve")
def resolve(pid: int, body: ResolveIn, db: Session = Depends(get_db), user: User = Depends(control_edit)) -> dict[str, Any]:
    """Mark an issue as solved (Çözüldü) with an optional note."""
    view = ProjectView.load(db, project_or_404(db, pid))
    row = _find_or_create(db, view, body.key, user)
    audit.record(db, user, "control", row.key, "status", row.status, RESOLVED, pid)
    if body.note != row.note:
        audit.record(db, user, "control", row.key, "note", row.note, body.note, pid)
    row.status, row.note = RESOLVED, body.note
    row.resolved_by, row.resolved_at = user.username, datetime.now(timezone.utc)
    db.commit()
    return _out(row.key, row.kind, row.part_no, row.message, row.levels or [], row.severity, row, row.manual)


@router.post("/projects/{pid}/control/fix")
def fix(pid: int, body: FixIn, db: Session = Depends(get_db), user: User = Depends(control_edit),
        _: User = Depends(parts_edit)) -> dict[str, Any]:
    """Changes the data behind the selected issues. Once the data is right the check stops reporting them.
    Material and revision are written to the rows of the current BOM version, temin to the part's tracking."""
    project = project_or_404(db, pid)
    view = ProjectView.load(db, project)
    found = {i.key: i for i in detect(view)}
    value = body.value.strip()
    if not value:
        raise HTTPException(400, tx("Değer boş olamaz"))
    fixed = 0
    for key in dict.fromkeys(body.keys):
        issue = found.get(key)
        if issue is None:
            continue                # already gone, for example fixed by the same part in this selection
        target = FIX_FIELD.get(issue.kind)
        if target is None:
            raise HTTPException(400, tx("Bu kontrol maddesi burada düzeltilemez"))
        if target == "procurement":
            if value not in temin_choices(db):
                raise HTTPException(400, tx("Temin şekli tanımlı değil. Önce sistem ayarlarından ekleyin."))
            t = tracking_of(db, pid, issue.part_no)
            if t is None:
                raise HTTPException(404, tx("Kontrol maddesi bulunamadı"))
            apply_changes(db, user, t, clean_changes(db, {"procurement_override": value}))
        else:
            if len(value) > FIELD_LIMIT[target]:
                raise HTTPException(400, tx("Değer çok uzun"))
            if issue.kind == KIND_MATERIAL_MISMATCH and value not in issue.choices:
                raise HTTPException(400, tx("Listeden bir değer seçin"))
            for r in view.rows:
                hit = r.material in issue.choices if issue.kind == KIND_MATERIAL_MISMATCH else r.part_no == issue.part_no
                if hit and getattr(r, target) != value:
                    audit.record(db, user, "bom", r.part_no, target, getattr(r, target), value, pid)
                    setattr(r, target, value)
        fixed += 1
    db.commit()
    return {"fixed": fixed}


@router.post("/projects/{pid}/control/unresolve")
def unresolve(pid: int, body: ResolveIn, db: Session = Depends(get_db),
              user: User = Depends(control_edit)) -> dict[str, Any]:
    """Reopen an issue (Açık); a non-empty note replaces the stored one."""
    project_or_404(db, pid)
    row = db.scalar(select(ControlIssue).where(ControlIssue.project_id == pid, ControlIssue.key == body.key))
    if row is None:
        raise HTTPException(404, tx("Kontrol maddesi bulunamadı"))
    audit.record(db, user, "control", row.key, "status", row.status, OPEN, pid)
    if body.note and body.note != row.note:
        audit.record(db, user, "control", row.key, "note", row.note, body.note, pid)
        row.note = body.note
    row.status, row.resolved_by, row.resolved_at = OPEN, "", None
    db.commit()
    return _out(row.key, row.kind, row.part_no, row.message, row.levels or [], row.severity, row, row.manual)


@router.post("/projects/{pid}/control/issues", status_code=201)
def create_manual(pid: int, body: ManualIn, db: Session = Depends(get_db),
                  user: User = Depends(control_edit)) -> dict[str, Any]:
    project_or_404(db, pid)
    if body.severity not in SEVERITIES:
        raise HTTPException(400, tx("Geçersiz önem derecesi. Seçenekler: {0}", ', '.join(SEVERITIES)))
    row = ControlIssue(project_id=pid, key=f"manual|tmp|{datetime.now(timezone.utc).timestamp()}",
                       kind=body.kind.strip() or KIND_MANUAL, part_no=body.part_no.strip(),
                       message=body.message.strip(), levels=[], severity=body.severity, status=OPEN,
                       manual=True, present=True, created_by=user.username)
    db.add(row)
    db.flush()
    row.key = f"manual|{row.id}"
    audit.record(db, user, "control", row.key, "message", None, row.message, pid, action="create")
    db.commit()
    return _out(row.key, row.kind, row.part_no, row.message, [], row.severity, row, manual=True)


@router.delete("/projects/{pid}/control/issues/{iid}")
def delete_manual(pid: int, iid: int, db: Session = Depends(get_db), user: User = Depends(control_edit)) -> dict[str, Any]:
    row = db.get(ControlIssue, iid)
    if row is None or row.project_id != pid:
        raise HTTPException(404, tx("Kontrol maddesi bulunamadı"))
    if not row.manual:
        raise HTTPException(400, tx("Otomatik kontrol maddeleri silinemez; çözüldü olarak işaretleyin"))
    audit.record(db, user, "control", row.key, "message", row.message, None, pid, action="delete")
    db.delete(row)
    db.commit()
    return {"deleted": True}
