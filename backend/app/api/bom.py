"""BOM versions: upload, compare, approve/reject, undo, raw rows; part aliases (spec 4.5, screen 8.6)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import BomRow, BomVersion, PartAlias, Project, Tracking, User
from ..services import audit, bomimport
from ..services.state import ProjectView
from ..services.tracking import move_state, read_upload_sync
from ..permissions import require
from .deps import get_db, project_or_404

projects_view, projects_edit = require("projects", "view"), require("projects", "edit")
from .projects import version_brief
from app.core.i18n import tx

router = APIRouter(prefix="/projects", tags=["bom"])

# A BOM CSV is parsed in memory; anything bigger than this is not a BOM export
BOM_MAX_MB = 200


def _version_or_404(db: Session, project: Project, vid: int) -> BomVersion:
    v = db.get(BomVersion, vid)
    if v is None or v.project_id != project.id:
        raise HTTPException(404, tx("BOM sürümü bulunamadı"))
    return v


def version_out(project: Project, v: BomVersion, detail: bool = False) -> dict[str, Any]:
    out = version_brief(v) or {}
    cj = v.compare_json or {}
    out.update(note=v.note, previous_version_id=v.previous_version_id, is_current=project.current_version_id == v.id,
               stats=v.stats_json or {}, can_undo=project.current_version_id == v.id and v.status == "approved"
               and bool(v.undo_json),
               summary={"added": len(cj.get("added") or []), "removed": len(cj.get("removed") or []),
                        "rev_changed": len(cj.get("rev_changed") or []),
                        "qty_changed": len(cj.get("qty_changed") or []),
                        "fastener_changes": len(cj.get("fastener_changes") or []),
                        "warnings": len(cj.get("warnings") or []), "first": bool(cj.get("first"))})
    if detail:
        out["compare"] = cj
        out["alias_suggestions"] = cj.get("alias_suggestions") or []
        out["warnings"] = cj.get("warnings") or []
    return out


def _bad(e: bomimport.BomImportError) -> HTTPException:
    return HTTPException(400, str(e))


# ---------- versions ----------
@router.post("/{pid}/bom/upload", status_code=201)
def upload(pid: int, file: UploadFile = File(...), note: str = Form(""),
                 db: Session = Depends(get_db), user: User = Depends(projects_edit)) -> dict:
    project = project_or_404(db, pid)
    if project.archived:
        raise HTTPException(400, tx("Arşivlenmiş projeye BOM yüklenemez"))
    name = Path(file.filename or "bom.csv").name
    if not name.lower().endswith((".csv", ".txt")):
        raise HTTPException(400, tx("BOM dosyası CSV olmalı"))
    # Sync endpoint: parsing a large BOM must not block the event loop
    data = read_upload_sync(file, BOM_MAX_MB)
    try:
        v = bomimport.upload_bom(db, project, name, data, user, note)
    except bomimport.BomImportError as e:
        db.rollback()
        raise _bad(e) from e
    db.commit()
    return version_out(project, v, detail=True)


@router.get("/{pid}/bom/versions")
def list_versions(pid: int, db: Session = Depends(get_db), _: User = Depends(projects_view)) -> list[dict]:
    project = project_or_404(db, pid)
    vs = db.scalars(select(BomVersion).where(BomVersion.project_id == project.id).order_by(BomVersion.seq.desc()))
    return [version_out(project, v) for v in vs]


@router.get("/{pid}/bom/versions/{vid}")
def get_version(pid: int, vid: int, db: Session = Depends(get_db), _: User = Depends(projects_view)) -> dict:
    project = project_or_404(db, pid)
    v = _version_or_404(db, project, vid)
    if v.status == "pending" and v.previous_version_id != project.current_version_id:
        # Current version changed since upload: compare against the new one
        bomimport.refresh_compare(db, project, v)
        db.commit()
    return version_out(project, v, detail=True)


@router.get("/{pid}/bom/versions/{vid}/rows")
def version_rows(pid: int, vid: int, db: Session = Depends(get_db), _: User = Depends(projects_view)) -> dict:
    """All rows of a version in BOM order (tree view: level, depth, parent_level, qty, total_qty)."""
    project = project_or_404(db, pid)
    v = _version_or_404(db, project, vid)
    rows = ProjectView.load(db, project, v.id).all_rows()
    return {"version": version_out(project, v), "count": len(rows), "rows": rows}


@router.get("/{pid}/bom/versions/{vid}/file")
def version_file(pid: int, vid: int, db: Session = Depends(get_db), _: User = Depends(projects_view)):
    project = project_or_404(db, pid)
    v = _version_or_404(db, project, vid)
    path = Path(v.file_path) if v.file_path else None
    if path is None or not path.is_file():
        raise HTTPException(404, tx("BOM dosyası sunucuda bulunamadı"))
    return FileResponse(path, filename=v.filename, media_type="text/csv")


class AliasPair(BaseModel):
    removed: str
    added: str


class ApproveIn(BaseModel):
    alias_accept: list[AliasPair] = Field(default_factory=list)


@router.post("/{pid}/bom/versions/{vid}/approve")
def approve(pid: int, vid: int, body: ApproveIn | None = None, db: Session = Depends(get_db),
            user: User = Depends(projects_edit)) -> dict:
    project = project_or_404(db, pid)
    v = _version_or_404(db, project, vid)
    if project.archived:
        raise HTTPException(400, tx("Arşivlenmiş projede BOM onaylanamaz"))
    pairs = [p.model_dump() for p in (body.alias_accept if body else [])]
    try:
        bomimport.approve(db, v, user, pairs)
    except bomimport.BomImportError as e:
        db.rollback()
        raise _bad(e) from e
    db.commit()
    return version_out(project, v, detail=True)


@router.post("/{pid}/bom/versions/{vid}/reject")
def reject(pid: int, vid: int, db: Session = Depends(get_db), user: User = Depends(projects_edit)) -> dict:
    project = project_or_404(db, pid)
    v = _version_or_404(db, project, vid)
    try:
        bomimport.reject(db, v, user)
    except bomimport.BomImportError as e:
        db.rollback()
        raise _bad(e) from e
    db.commit()
    return version_out(project, v)


@router.delete("/{pid}/bom/versions/{vid}")
def delete_version(pid: int, vid: int, db: Session = Depends(get_db), user: User = Depends(projects_edit)) -> dict:
    project = project_or_404(db, pid)
    v = _version_or_404(db, project, vid)
    try:
        path = bomimport.delete_version(db, v, user)
    except bomimport.BomImportError as e:
        db.rollback()
        raise _bad(e) from e
    db.commit()
    bomimport.remove_stored_file(path)
    return {"ok": True}


@router.post("/{pid}/bom/undo")
def undo(pid: int, db: Session = Depends(get_db), user: User = Depends(projects_edit)) -> dict:
    """Undo the last approved upload. Tracking edits made after that approval are lost."""
    project = project_or_404(db, pid)
    try:
        v = bomimport.undo_last(db, project, user)
    except bomimport.BomImportError as e:
        db.rollback()
        raise _bad(e) from e
    db.commit()
    cur = db.get(BomVersion, project.current_version_id) if project.current_version_id else None
    return {"undone": version_out(project, v), "current": version_out(project, cur) if cur else None}


# ---------- aliases ----------
def alias_out(a: PartAlias) -> dict[str, Any]:
    return {"id": a.id, "alias": a.alias, "part_no": a.part_no, "created_by": a.created_by,
            "created_at": a.created_at.isoformat() if a.created_at else None}


class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=200, description="Eski / farklı numara")
    part_no: str = Field(min_length=1, max_length=200, description="Geçerli parça numarası")
    move_state: bool = True


@router.get("/{pid}/aliases")
def list_aliases(pid: int, all: bool = False, db: Session = Depends(get_db),
                 _: User = Depends(projects_view)) -> list[dict]:
    """Aliases are global; by default only those touching this project's tracked parts are listed."""
    project = project_or_404(db, pid)
    q = select(PartAlias).order_by(PartAlias.part_no, PartAlias.alias)
    if not all:
        tracked = select(Tracking.part_no).where(Tracking.project_id == project.id)
        q = q.where(or_(PartAlias.part_no.in_(tracked), PartAlias.alias.in_(tracked)))
    return [alias_out(a) for a in db.scalars(q)]


@router.post("/{pid}/aliases", status_code=201)
def create_alias(pid: int, body: AliasIn, db: Session = Depends(get_db), user: User = Depends(projects_edit)) -> dict:
    """Manual "same part" mapping. With move_state the old number's tracking and missing rows
    move to the current number (as when accepting a suggestion at approval)."""
    project = project_or_404(db, pid)
    alias, part_no = body.alias.strip(), body.part_no.strip()
    if not alias or not part_no:
        raise HTTPException(400, tx("Takma ad ve parça numarası boş olamaz"))
    if alias == part_no:
        raise HTTPException(400, tx("Takma ad ile parça numarası aynı olamaz"))
    if db.scalar(select(PartAlias).where(PartAlias.alias == alias)):
        raise HTTPException(400, tx("Bu numara için zaten bir eşleştirme var: {0}", alias))
    if db.scalar(select(PartAlias).where(PartAlias.alias == part_no)):
        raise HTTPException(400, tx("{0} zaten başka bir numaranın takma adı; geçerli numarayı seçin", part_no))
    if project.current_version_id and db.scalar(select(BomRow.id).where(
            BomRow.version_id == project.current_version_id, BomRow.part_no == alias).limit(1)):
        raise HTTPException(400, tx("{0} güncel BOM'da hâlâ var; takma ad yapılamaz", alias))
    a = PartAlias(alias=alias, part_no=part_no, created_by=user.username)
    db.add(a)
    db.flush()
    # Aliases pointing at the old number now point at the new one (no chains)
    for other in db.scalars(select(PartAlias).where(PartAlias.part_no == alias)):
        audit.record(db, user, "alias", other.alias, "part_no", other.part_no, part_no, project.id)
        other.part_no = part_no
    moved = move_state(db, user, project.id, alias, part_no) if body.move_state else False
    audit.record(db, user, "part", part_no, "alias", alias, part_no, project.id, action="create")
    db.commit()
    return {**alias_out(a), "state_moved": moved}


@router.delete("/{pid}/aliases/{aid}")
def delete_alias(pid: int, aid: int, db: Session = Depends(get_db), user: User = Depends(projects_edit)) -> dict:
    """Removes only the mapping; tracking already moved to the current number stays there."""
    project = project_or_404(db, pid)
    a = db.get(PartAlias, aid)
    if a is None:
        raise HTTPException(404, tx("Eşleştirme bulunamadı"))
    audit.record(db, user, "part", a.part_no, "alias", a.alias, None, project.id, action="delete")
    db.delete(a)
    db.commit()
    return {"ok": True}
