"""Projects: list, create, update, archive, delete (spec 3, screen 8.2)."""
from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (BomVersion, ControlIssue, Drawing, Invoice, Project, PurchaseOrder, SalesOrder, StockMove,
                      TimeEntry, Tracking, User, WorkOrder)
from ..services import audit
from ..services import backup as backup_svc
from ..permissions import can, require
from .deps import admin, any_user, get_db, project_or_404

projects_view, projects_edit = require("projects", "view"), require("projects", "edit")
# Screens that pick a project without showing it: these see only ids and names
PICKER_MODULES = ("parts", "fasteners", "drawings", "control", "planning", "purchasing", "workorders", "stock", "hr",
                  "attendance", "sales", "finance")

router = APIRouter(prefix="/projects", tags=["projects"])


def version_brief(v: BomVersion | None) -> dict[str, Any] | None:
    if v is None:
        return None
    return {"id": v.id, "seq": v.seq, "filename": v.filename, "status": v.status,
            "uploaded_by": v.uploaded_by, "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None,
            "approved_by": v.approved_by, "approved_at": v.approved_at.isoformat() if v.approved_at else None}


def project_out(db: Session, p: Project) -> dict[str, Any]:
    cur = db.get(BomVersion, p.current_version_id) if p.current_version_id else None
    pending = db.scalar(select(func.count()).select_from(BomVersion)
                        .where(BomVersion.project_id == p.id, BomVersion.status == "pending")) or 0
    parts = db.scalar(select(func.count()).select_from(Tracking)
                      .where(Tracking.project_id == p.id, Tracking.archived.is_(False))) or 0
    return {"id": p.id, "name": p.name, "root_part_no": p.root_part_no, "description": p.description,
            "archived": p.archived, "created_at": p.created_at.isoformat() if p.created_at else None,
            "current_version_id": p.current_version_id, "current_version": version_brief(cur),
            "pending_versions": pending, "tracked_parts": parts}


def _brief(p: Project) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "archived": p.archived}


def _name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    q = select(Project.id).where(func.lower(Project.name) == name.lower())
    if exclude_id is not None:
        q = q.where(Project.id != exclude_id)
    return db.scalar(q) is not None


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    root_part_no: str = ""
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    root_part_no: str | None = None
    description: str | None = None


@router.get("")
def list_projects(include_archived: bool = False, db: Session = Depends(get_db),
                  me: User = Depends(any_user)) -> list[dict]:
    q = select(Project).order_by(Project.archived, Project.name)
    if not include_archived:
        q = q.where(Project.archived.is_(False))
    if can(me, "projects"):
        return [project_out(db, p) for p in db.scalars(q)]
    if any(can(me, m) for m in PICKER_MODULES):
        return [_brief(p) for p in db.scalars(q)]
    return []


@router.post("", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(projects_edit)) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Proje adı boş olamaz")
    if _name_taken(db, name):
        raise HTTPException(400, f"Bu isimde bir proje zaten var: {name}")
    p = Project(name=name, root_part_no=body.root_part_no.strip(), description=body.description)
    db.add(p)
    db.flush()
    audit.record(db, user, "project", p.id, "name", None, name, p.id, action="create")
    db.commit()
    return project_out(db, p)


@router.get("/{pid}")
def get_project(pid: int, db: Session = Depends(get_db), me: User = Depends(any_user)) -> dict:
    if not can(me, "projects"):
        if any(can(me, m) for m in PICKER_MODULES):
            return _brief(project_or_404(db, pid))
        raise HTTPException(403, "Bu proje için yetkiniz yok")
    return project_out(db, project_or_404(db, pid))


@router.patch("/{pid}")
def update_project(pid: int, body: ProjectPatch, db: Session = Depends(get_db),
                   user: User = Depends(projects_edit)) -> dict:
    p = project_or_404(db, pid)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise HTTPException(400, "Proje adı boş olamaz")
        if _name_taken(db, changes["name"], p.id):
            raise HTTPException(400, f"Bu isimde bir proje zaten var: {changes['name']}")
    if "root_part_no" in changes:
        changes["root_part_no"] = changes["root_part_no"].strip()
    audit.record_changes(db, user, p, changes, "project", p.id, p.id)
    db.commit()
    return project_out(db, p)


@router.delete("/{pid}")
def archive_project(pid: int, db: Session = Depends(get_db), user: User = Depends(admin)) -> dict:
    """Archive only: BOM versions and history stay. POST /{pid}/purge deletes for good."""
    p = project_or_404(db, pid)
    audit.record_changes(db, user, p, {"archived": True}, "project", p.id, p.id)
    db.commit()
    return project_out(db, p)


@router.post("/{pid}/restore")
def restore_project(pid: int, db: Session = Depends(get_db), user: User = Depends(admin)) -> dict:
    p = project_or_404(db, pid)
    audit.record_changes(db, user, p, {"archived": False}, "project", p.id, p.id)
    db.commit()
    return project_out(db, p)


def _count(db: Session, model: Any, pid: int) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.project_id == pid)) or 0


@router.get("/{pid}/delete-impact")
def delete_impact(pid: int, db: Session = Depends(get_db), _: User = Depends(admin)) -> dict:
    """What a purge removes with the project, and the records that stay without a project link."""
    p = project_or_404(db, pid)
    return {"deleted": {"bom_versions": _count(db, BomVersion, p.id), "tracked_parts": _count(db, Tracking, p.id),
                        "work_orders": _count(db, WorkOrder, p.id), "control_issues": _count(db, ControlIssue, p.id)},
            "unlinked": {"purchase_orders": _count(db, PurchaseOrder, p.id), "sales_orders": _count(db, SalesOrder, p.id),
                         "invoices": _count(db, Invoice, p.id), "stock_moves": _count(db, StockMove, p.id),
                         "time_entries": _count(db, TimeEntry, p.id), "drawings": _count(db, Drawing, p.id)}}


@router.post("/{pid}/purge")
def purge_project(pid: int, db: Session = Depends(get_db), user: User = Depends(admin)) -> dict:
    """Delete a project for good. A backup is taken first, so the data can still be restored from it."""
    p = project_or_404(db, pid)
    backup_name = ""
    try:
        backup_name = backup_svc.create_backup().name
    except backup_svc.BackupBusy:
        pass  # a backup is running or was just taken
    except backup_svc.BackupError as e:
        raise HTTPException(500, f"Yedek alınamadı, proje silinmedi: {e}") from e
    audit.record(db, user, "project", p.id, "deleted", p.name, None, action="delete")
    p.current_version_id = None
    db.flush()
    db.delete(p)
    db.commit()
    shutil.rmtree(get_settings().bom_dir / str(pid), ignore_errors=True)
    return {"ok": True, "backup": backup_name}
