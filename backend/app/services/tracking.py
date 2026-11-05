"""Tracking edits shared by the parts, missing-row and alias endpoints.

Validation of user-chosen values (progress, procurement, manufacturer, material status)
lives here so inline edit, bulk edit and missing rows reject the same bad input.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.status import MATERIAL_STATUS_CHOICES, PROGRESS_CHOICES
from ..models import AuditLog, MissingRow, PartAlias, PartName, SyncState, Tracking, User
from . import audit
from .settings import get_setting, manufacturers, temin_choices
from app.core.i18n import tx

# Fields a user may change on a tracking row (inline or bulk edit)
EDITABLE_FIELDS = ("procurement_override", "progress", "note", "t35_note", "manufacturer",
                   "material_status", "is_new", "hidden")


def material_status_choices(db: Session) -> list[str]:
    v = get_setting(db, "material_status_choices", MATERIAL_STATUS_CHOICES)
    return list(v) if isinstance(v, list) and v else list(MATERIAL_STATUS_CHOICES)


def check_progress(value: Any) -> str:
    if value not in PROGRESS_CHOICES:
        raise HTTPException(400, tx("Geçersiz ilerleme değeri: {0}. Seçenekler: {1}", value, ', '.join(PROGRESS_CHOICES)))
    return value


def clean_changes(db: Session, changes: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise tracking changes; unknown fields are rejected."""
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise HTTPException(400, tx("Düzenlenemeyen alan: {0}", ', '.join(sorted(unknown))))
    out: dict[str, Any] = {}
    for f, v in changes.items():
        if f == "progress":
            out[f] = check_progress(v)
        elif f == "procurement_override":
            v = (v or "").strip() or None
            choices = temin_choices(db)
            if v is not None and v not in choices:
                raise HTTPException(400, tx("Geçersiz temin şekli: {0}. Seçenekler: {1}", v, ', '.join(choices)))
            out[f] = v
        elif f == "manufacturer":
            v = (v or "").strip()
            allowed = manufacturers(db)
            if v and allowed and v not in allowed:
                raise HTTPException(400, tx("Üretici/firma listede yok: {0}. Yönetim ekranından ekleyin.", v))
            out[f] = v
        elif f == "material_status":
            v = (v or "").strip()
            choices = material_status_choices(db)
            if v and v not in choices:
                raise HTTPException(400, tx("Geçersiz malzeme durumu: {0}. Seçenekler: {1}", v, ', '.join(choices)))
            out[f] = v
        elif f in ("is_new", "hidden"):
            if not isinstance(v, bool):
                raise HTTPException(400, tx("Bu alan doğru/yanlış olmalı"))
            out[f] = v
        else:  # note, t35_note
            out[f] = "" if v is None else str(v)
    return out


def apply_changes(db: Session, user: User, t: Tracking, changes: dict[str, Any]) -> int:
    """Apply already cleaned changes with audit entries. Returns changed field count."""
    n = audit.record_changes(db, user, t, changes, "tracking", t.part_no, t.project_id)
    if n:
        t.updated_by = user.username
    return n


def current_rev(db: Session) -> int:
    """Handed out with the part list and sent back with edits: what the editor had seen."""
    return db.scalar(select(func.max(AuditLog.id))) or 0


def recent_edits(db: Session, user: User, project_id: int, rev: int) -> dict[tuple[str, str], AuditLog]:
    """What others changed in this project after `rev`, latest per (part, field)."""
    # Holds a write lock until commit: of two people saving the same cell at once, the second one sees the first
    db.execute(update(SyncState).where(SyncState.id == 1).values(rev=SyncState.rev))
    rows = db.scalars(select(AuditLog).where(
        AuditLog.id > rev, AuditLog.entity.in_(("tracking", "part_name")), AuditLog.username != user.username,
        or_(AuditLog.project_id == project_id, AuditLog.project_id.is_(None))).order_by(AuditLog.id))
    return {(r.entity_id, r.field): r for r in rows}


def conflict_of(edits: dict[tuple[str, str], AuditLog], part_no: str, field: str, value: Any) -> dict[str, Any] | None:
    """Saving `value` would overwrite someone else's newer entry; arriving at the same value is no conflict."""
    r = edits.get((part_no, "name" if field == "part_name" else field))
    mine = audit.text(value) or ""
    if r is None or (r.new or "") == mine:
        return None
    return {"part_no": part_no, "field": field, "mine": value, "theirs": r.new, "by": r.username, "at": r.ts}


def set_names(db: Session, user: User, names: dict[str, str]) -> int:
    """Name parts for all projects; an empty name removes it. Returns how many changed."""
    have = {n.part_no: n for n in db.scalars(select(PartName).where(PartName.part_no.in_(list(names))))}
    changed = 0
    for pno, name in names.items():
        name = name.strip()[:300]
        cur = have.get(pno)
        if (cur.name if cur else "") == name:
            continue
        if cur is None:
            try:
                with db.begin_nested():
                    db.add(PartName(part_no=pno, name=name, updated_by=user.username))
            except IntegrityError:  # someone named the same part at the same moment; the later name wins
                cur = db.scalar(select(PartName).where(PartName.part_no == pno))
                cur.name, cur.updated_by = name, user.username
        elif name:
            cur.name, cur.updated_by = name, user.username
        else:
            db.delete(cur)
        audit.record(db, user, "part_name", pno, "name", cur.name if cur else "", name)
        changed += 1
    return changed


def resolve_alias(db: Session, part_no: str) -> str:
    """Map an old number to its canonical part number (single hop, as aliases are stored)."""
    a = db.scalar(select(PartAlias).where(PartAlias.alias == part_no))
    return a.part_no if a else part_no


def tracking_of(db: Session, project_id: int, part_no: str) -> Tracking | None:
    return db.scalar(select(Tracking).where(Tracking.project_id == project_id, Tracking.part_no == part_no))


def tracking_map(db: Session, project_id: int, part_nos: list[str] | None = None) -> dict[str, Tracking]:
    q = select(Tracking).where(Tracking.project_id == project_id)
    if part_nos is not None:
        q = q.where(Tracking.part_no.in_(part_nos))
    return {t.part_no: t for t in db.scalars(q)}


def move_state(db: Session, user: User, project_id: int, old_no: str, new_no: str) -> bool:
    """Carry tracking + missing rows of `old_no` over to `new_no` (manual alias).
    The new number keeps its archived flag; the old state wins over a fresh default.
    Returns True when a tracking row was moved."""
    t_old, t_new = tracking_of(db, project_id, old_no), tracking_of(db, project_id, new_no)
    moved = False
    if t_old is not None:
        archived = t_new.archived if t_new is not None else t_old.archived
        if t_new is not None:
            db.delete(t_new)
            db.flush()
        t_old.part_no = new_no
        t_old.archived = archived
        t_old.is_new = False
        t_old.updated_by = user.username
        moved = True
    for m in db.scalars(select(MissingRow).where(MissingRow.project_id == project_id,
                                                 MissingRow.part_no == old_no)):
        m.part_no = new_no
        audit.record(db, user, "missing", new_no, "part_no", old_no, new_no, project_id)
    return moved


def tracking_view(t: Tracking) -> dict[str, Any]:
    """Row for a tracked part that is not in the shown BOM version (archived / removed)."""
    return {
        "id": None, "part_no": t.part_no, "procurement_override": t.procurement_override,
        "progress": t.progress, "note": t.note, "t35_note": t.t35_note, "manufacturer": t.manufacturer,
        "material_status": t.material_status, "is_new": t.is_new, "archived": t.archived, "hidden": t.hidden,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None, "updated_by": t.updated_by,
    }


async def read_upload(file: UploadFile, max_mb: int | None = None) -> bytes:
    """Read an upload in 1 MB chunks, refusing anything above the size limit."""
    limit = (max_mb or get_settings().max_upload_mb) * (1 << 20)
    buf = bytearray()
    while True:
        chunk = await file.read(1 << 20)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, tx("Dosya çok büyük (en fazla {0} MB).", limit >> 20))
    return bytes(buf)


def read_upload_sync(file: UploadFile, max_mb: int | None = None) -> bytes:
    """Same as read_upload for sync endpoints (heavy parsing then runs in the threadpool,
    not on the event loop). FastAPI has already spooled the upload to a temp file."""
    limit = (max_mb or get_settings().max_upload_mb) * (1 << 20)
    buf = bytearray()
    file.file.seek(0)
    while True:
        chunk = file.file.read(1 << 20)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, tx("Dosya çok büyük (en fazla {0} MB).", limit >> 20))
    return bytes(buf)


def resolve_aliases(db: Session, part_nos: list[str]) -> list[str]:
    """resolve_alias for many numbers in one query; order kept, duplicates dropped."""
    amap = {a.alias: a.part_no for a in db.scalars(select(PartAlias).where(PartAlias.alias.in_(part_nos)))} \
        if part_nos else {}
    return list(dict.fromkeys(amap.get(p, p) for p in part_nos))
