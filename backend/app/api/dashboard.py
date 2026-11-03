"""Project dashboard: KPIs, status breakdowns, main-group progress (spec 6, screen 8.3)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models import BomVersion, User
from ..services.state import ProjectView
from ..permissions import require
from .deps import get_db, project_or_404
from .projects import project_out

router = APIRouter(prefix="/projects", tags=["dashboard"])


@router.get("/{pid}/dashboard")
def dashboard(pid: int, version_id: int | None = None, db: Session = Depends(get_db),
              _: User = Depends(require("projects", "view"))) -> dict:
    """Dashboard of the current (or a chosen) BOM version. A project without an approved BOM
    returns empty counts."""
    project = project_or_404(db, pid)
    if version_id is not None:
        v = db.get(BomVersion, version_id)
        if v is None or v.project_id != project.id:
            raise HTTPException(404, "BOM sürümü bulunamadı")
    data = ProjectView.load(db, project, version_id).dashboard()
    return {"project": project_out(db, project), **data}
