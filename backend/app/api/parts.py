"""Parts list with tracking, inline / bulk edit, part detail and missing rows (spec 5, screen 8.4)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.normalize import tr_contains
from ..core.status import (COLORS, PROG_WAIT, PROGRESS_CHOICES, STATUS_IN_PURCHASED, STATUS_MAP,
                           STATUS_NO_TEMIN)
from ..models import AuditLog, BomVersion, MissingRow, PartAlias, Tracking, User
from ..services import audit
from ..services.settings import manufacturers, suppliers
from ..services.state import FASTENER_COLORS, ProjectView, row_types, temin_choices
from ..services.state import FASTENER_ORDER_STATUSES
from ..services.tracking import (apply_changes, check_progress, clean_changes, material_status_choices,
                                 resolve_alias, resolve_aliases, tracking_map, tracking_of, tracking_view)
from ..permissions import require
from .deps import get_db, project_or_404

parts_view, parts_edit = require("parts", "view"), require("parts", "edit")

router = APIRouter(prefix="/projects", tags=["parts"])

SEARCH_FIELDS = ("part_no", "file_name", "material", "note", "t35_note", "manufacturer", "main_group",
                 "parent_part_no", "level", "coating", "fastener_desc")


class TrackingPatch(BaseModel):
    procurement_override: str | None = None
    progress: str | None = None
    note: str | None = None
    t35_note: str | None = None
    manufacturer: str | None = None
    material_status: str | None = None
    is_new: bool | None = None
    hidden: bool | None = None


class BulkIn(BaseModel):
    part_nos: list[str] = Field(min_length=1, max_length=20000)
    changes: TrackingPatch


class MissingIn(BaseModel):
    part_no: str = Field(min_length=1, max_length=200)
    qty: int = Field(default=1, ge=1, le=1_000_000)
    reason: str = Field(default="", max_length=300)
    progress: str = PROG_WAIT
    note: str = ""


class MissingPatch(BaseModel):
    qty: int | None = Field(default=None, ge=1, le=1_000_000)
    reason: str | None = Field(default=None, max_length=300)
    progress: str | None = None
    note: str | None = None


def _patch_changes(body: TrackingPatch) -> dict[str, Any]:
    """Sent fields only; an explicit null clears procurement_override / text fields."""
    ch = body.model_dump(exclude_unset=True)
    if "progress" in ch and ch["progress"] is None:
        raise HTTPException(400, "İlerleme boş olamaz")
    for f in ("is_new", "hidden"):
        if f in ch and ch[f] is None:
            del ch[f]
    return ch


def _match(v: dict[str, Any], values: list[str] | None, key: str) -> bool:
    return not values or (v.get(key) or "") in values


def _filter(rows: list[dict[str, Any]], q: str | None, procurement: list[str] | None, status: list[str] | None,
            progress: list[str] | None, manufacturer: list[str] | None, row_type: list[str] | None,
            main_group: list[str] | None, is_new: bool | None, in_purchased: bool | None,
            has_drawing: bool | None, fastener: bool | None) -> list[dict[str, Any]]:
    out = []
    for v in rows:
        if not (_match(v, procurement, "procurement") and _match(v, status, "status")
                and _match(v, progress, "progress") and _match(v, manufacturer, "manufacturer")
                and _match(v, row_type, "row_type")):
            continue
        if main_group and not set(v.get("main_groups") or [v.get("main_group") or ""]) & set(main_group):
            continue
        if is_new is not None and bool(v.get("is_new")) != is_new:
            continue
        if in_purchased is not None and bool(v.get("in_purchased")) != in_purchased:
            continue
        if has_drawing is not None and bool(v.get("has_drawing")) != has_drawing:
            continue
        if fastener is not None and bool(v.get("fastener")) != fastener:
            continue
        if q and not any(tr_contains(str(v.get(f) or ""), q) for f in SEARCH_FIELDS):
            continue
        out.append(v)
    return out


def _check_version(db: Session, project, version_id: int | None) -> None:
    if version_id is not None:
        v = db.get(BomVersion, version_id)
        if v is None or v.project_id != project.id:
            raise HTTPException(404, "BOM sürümü bulunamadı")


def _part_row(view: ProjectView, part_no: str) -> dict[str, Any] | None:
    return next((p for p in view.parts() if p["part_no"] == part_no), None)


def _part_or_tracking(db: Session, view: ProjectView, part_no: str) -> dict[str, Any]:
    row = _part_row(view, part_no)
    if row is not None:
        row["archived"] = False
        return row
    t = view.tracking.get(part_no)
    if t is None:
        raise HTTPException(404, f"Parça bu projede bulunamadı: {part_no}")
    return tracking_view(t)


# ---------- list ----------
@router.get("/{pid}/parts")
def list_parts(pid: int, view: str = Query("flat", pattern="^(flat|tree)$"), q: str | None = None,
               procurement: list[str] | None = Query(None), status: list[str] | None = Query(None),
               progress: list[str] | None = Query(None), manufacturer: list[str] | None = Query(None),
               row_type: list[str] | None = Query(None), main_group: list[str] | None = Query(None),
               is_new: bool | None = None, in_purchased: bool | None = None, has_drawing: bool | None = None,
               fastener: bool | None = None, archived: bool = False, version_id: int | None = None,
               limit: int | None = Query(None, ge=1), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), _: User = Depends(parts_view)) -> dict:
    """flat: one line per part number (summed total qty); tree: every BOM row in order.
    archived=true lists parts removed from the BOM whose tracking is kept."""
    project = project_or_404(db, pid)
    _check_version(db, project, version_id)
    pv = ProjectView.load(db, project, version_id)
    if archived:
        rows = [tracking_view(t) for t in sorted(pv.tracking.values(), key=lambda t: t.part_no) if t.archived]
        rows = _filter(rows, q, None, None, progress, manufacturer, None, None, is_new, None, None, None)
        total = sum(1 for t in pv.tracking.values() if t.archived)
    else:
        base = pv.all_rows() if view == "tree" else pv.parts(include_in_purchased=in_purchased is not False)
        total = len(base)
        rows = _filter(base, q, procurement, status, progress, manufacturer, row_type, main_group, is_new,
                       in_purchased, has_drawing, fastener)
    count = len(rows)
    total_qty = sum(r.get("total_qty") or 0 for r in rows)
    if offset or limit:
        rows = rows[offset: offset + limit if limit else None]
    return {"version_id": pv.version.id if pv.version else None, "view": "archived" if archived else view,
            "total": total, "count": count, "total_qty": total_qty, "offset": offset, "rows": rows}


@router.get("/{pid}/parts/choices")
def choices(pid: int, db: Session = Depends(get_db), _: User = Depends(parts_view)) -> dict:
    project_or_404(db, pid)
    statuses = list(dict.fromkeys([*(s for m in STATUS_MAP.values() for s in m.values()), STATUS_NO_TEMIN,
                                   STATUS_IN_PURCHASED]))
    return {"row_types": row_types(), "temin_choices": temin_choices(), "progress_choices": PROGRESS_CHOICES,
            "manufacturers": manufacturers(db), "suppliers": suppliers(db),
            "material_status_choices": material_status_choices(db),
            "statuses": [{"status": s, "color": COLORS.get(s, COLORS["in_purchased"]
                                                          if s == STATUS_IN_PURCHASED else "")} for s in statuses],
            "fastener_order_statuses": [{"status": s, "color": FASTENER_COLORS.get(s, "")}
                                        for s in FASTENER_ORDER_STATUSES],
            "colors": COLORS}


# ---------- edit ----------
@router.post("/{pid}/parts/bulk")
def bulk_edit(pid: int, body: BulkIn, db: Session = Depends(get_db), user: User = Depends(parts_edit)) -> dict:
    """Multi-select edit: same values for every selected part ("İlerlemeyi ayarla", "Temin şeklini ayarla")."""
    project = project_or_404(db, pid)
    changes = clean_changes(db, _patch_changes(body.changes))
    if not changes:
        raise HTTPException(400, "Değiştirilecek alan seçilmedi")
    wanted = resolve_aliases(db, [p.strip() for p in body.part_nos if p.strip()])
    tmap = tracking_map(db, project.id, wanted)
    updated = fields = 0
    for pno in wanted:
        t = tmap.get(pno)
        if t is None:
            continue
        n = apply_changes(db, user, t, changes)
        fields += n
        updated += 1 if n else 0
    db.commit()
    return {"matched": len(tmap), "updated": updated, "fields_changed": fields,
            "not_found": [p for p in wanted if p not in tmap]}


@router.patch("/{pid}/parts/{part_no:path}")
def edit_part(pid: int, part_no: str, body: TrackingPatch, db: Session = Depends(get_db),
              user: User = Depends(parts_edit)) -> dict:
    project = project_or_404(db, pid)
    pno = resolve_alias(db, part_no)
    t = tracking_of(db, project.id, pno)
    if t is None:
        raise HTTPException(404, f"Parça bu projede takip edilmiyor: {part_no}")
    changes = clean_changes(db, _patch_changes(body))
    n = apply_changes(db, user, t, changes)
    db.commit()
    row = _part_or_tracking(db, ProjectView.load(db, project), pno)
    return {"changed": n, "part": row}


# ---------- missing rows ----------
def _missing_view(db: Session, project, mid: int) -> dict[str, Any]:
    view = ProjectView.load(db, project)
    return next(m for m in view.missing_views() if m["id"] == mid)


def _missing_or_404(db: Session, pid: int, mid: int) -> MissingRow:
    m = db.get(MissingRow, mid)
    if m is None or m.project_id != pid:
        raise HTTPException(404, "Eksik satırı bulunamadı")
    return m


@router.get("/{pid}/missing")
def list_missing(pid: int, part_no: str | None = None, db: Session = Depends(get_db),
                 _: User = Depends(parts_view)) -> dict:
    project = project_or_404(db, pid)
    rows = ProjectView.load(db, project).missing_views()
    if part_no:
        pno = resolve_alias(db, part_no)
        rows = [m for m in rows if m["part_no"] == pno]
    return {"count": len(rows), "total_qty": sum(m["qty"] for m in rows), "rows": rows}


@router.post("/{pid}/missing", status_code=201)
def create_missing(pid: int, body: MissingIn, db: Session = Depends(get_db), user: User = Depends(parts_edit)) -> dict:
    project = project_or_404(db, pid)
    pno = resolve_alias(db, body.part_no.strip())
    if tracking_of(db, project.id, pno) is None:
        raise HTTPException(400, f"Parça bu projede bulunamadı: {body.part_no}")
    m = MissingRow(project_id=project.id, part_no=pno, qty=body.qty, reason=body.reason.strip(),
                   progress=check_progress(body.progress), note=body.note, created_by=user.username)
    db.add(m)
    db.flush()
    audit.record(db, user, "missing", pno, "qty", None, m.qty, project.id, action="create")
    db.commit()
    return _missing_view(db, project, m.id)


@router.patch("/{pid}/missing/{mid}")
def update_missing(pid: int, mid: int, body: MissingPatch, db: Session = Depends(get_db),
                   user: User = Depends(parts_edit)) -> dict:
    project = project_or_404(db, pid)
    m = _missing_or_404(db, project.id, mid)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "progress" in changes:
        check_progress(changes["progress"])
    if "reason" in changes:
        changes["reason"] = changes["reason"].strip()
    audit.record_changes(db, user, m, changes, "missing", m.part_no, project.id)
    db.commit()
    return _missing_view(db, project, m.id)


@router.delete("/{pid}/missing/{mid}")
def delete_missing(pid: int, mid: int, db: Session = Depends(get_db), user: User = Depends(parts_edit)) -> dict:
    project = project_or_404(db, pid)
    m = _missing_or_404(db, project.id, mid)
    audit.record(db, user, "missing", m.part_no, "qty", m.qty, None, project.id, action="delete")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ---------- detail (path route last: part numbers may contain '/') ----------
@router.get("/{pid}/parts/{part_no:path}")
def part_detail(pid: int, part_no: str, version_id: int | None = None, db: Session = Depends(get_db),
                _: User = Depends(parts_view)) -> dict:
    """Info, drawings, status history, assemblies it is used in, missing rows."""
    project = project_or_404(db, pid)
    _check_version(db, project, version_id)
    pno = resolve_alias(db, part_no)
    view = ProjectView.load(db, project, version_id)
    part = _part_or_tracking(db, view, pno)
    occ = [r for r in view.rows if r.part_no == pno]
    occurrences = [{"id": r.id, "level": r.level, "parent_part_no": r.parent_part_no, "qty": r.qty,
                    "multiplier": r.multiplier, "total_qty": r.total_qty, "main_group": r.main_group,
                    "in_purchased": r.in_purchased} for r in occ]
    used_in = list(dict.fromkeys(r.parent_part_no for r in occ if r.parent_part_no))
    drawings = [{"id": d.id, "filename": d.filename, "ext": d.ext, "rev": d.rev, "match_via": d.match_via,
                 "current_version": d.current_version,
                 "updated_at": d.updated_at.isoformat() if d.updated_at else None}
                for d in view.drawings.get(pno, [])]
    aliases = list(db.scalars(select(PartAlias.alias).where(PartAlias.part_no == pno)))
    ids = [pno, *aliases]
    logs = db.scalars(select(AuditLog).where(AuditLog.project_id == project.id,
                                             AuditLog.entity.in_(["tracking", "missing", "part"]),
                                             AuditLog.entity_id.in_(ids))
                      .order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(500))
    history = [{"id": a.id, "ts": a.ts.isoformat() if a.ts else None, "username": a.username, "entity": a.entity,
                "entity_id": a.entity_id, "field": a.field, "old": a.old, "new": a.new, "action": a.action}
               for a in logs]
    missing = [m for m in view.missing_views() if m["part_no"] == pno]
    t: Tracking | None = view.tracking.get(pno)
    return {"part": part, "tracking": tracking_view(t) if t else None, "aliases": aliases,
            "occurrences": occurrences, "used_in": used_in, "drawings": drawings,
            "drawing_info": view.drawing_info(pno, part.get("rev") or ""), "missing": missing,
            "history": history}
