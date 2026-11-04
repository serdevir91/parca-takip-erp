"""Proje şablonları: a product tree kept under a name; a new project starts from it as its draft."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import bomtree
from ..models import BomVersion, Project, ProjectTemplate, User
from ..permissions import require
from ..services import audit
from .bomtree import _named
from .deps import get_db, project_or_404

router = APIRouter(prefix="/project-templates", tags=["templates"])
view = require("projects", "view")
edit = require("projects", "edit")


class TemplateIn(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=1000)


def _count(n: dict[str, Any]) -> int:
    return 1 + sum(_count(c) for c in n.get("children", []))


def _out(t: ProjectTemplate) -> dict[str, Any]:
    return {"id": t.id, "name": t.name, "note": t.note, "created_by": t.created_by, "nodes": _count(t.payload),
            "created_at": t.created_at.isoformat() if t.created_at else None}


def _tree_of(db: Session, project: Project) -> dict[str, Any] | None:
    """The tree being worked on when there is one, else the current BOM."""
    if project.bom_draft and project.bom_draft.get("tree"):
        return project.bom_draft["tree"]
    v = db.get(BomVersion, project.current_version_id) if project.current_version_id else None
    return _named(db, bomtree.from_rows(v.rows)) if v else None


@router.get("")
def list_templates(_: User = Depends(view), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [_out(t) for t in db.scalars(select(ProjectTemplate).order_by(ProjectTemplate.name))]


@router.post("", status_code=201)
def create_template(body: TemplateIn, me: User = Depends(edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Şablon adı boş olamaz")
    if db.scalar(select(ProjectTemplate.id).where(ProjectTemplate.name == name)):
        raise HTTPException(400, f"Bu isimde bir şablon zaten var: {name}")
    tree = _tree_of(db, project_or_404(db, body.project_id))
    if not tree:
        raise HTTPException(400, "Bu projede şablona alınacak ürün ağacı yok")
    t = ProjectTemplate(name=name, note=body.note.strip(), payload=tree, created_by=me.username)
    db.add(t)
    db.flush()
    audit.record(db, me, "project_template", t.id, "name", None, name, action="create")
    db.commit()
    return _out(t)


@router.delete("/{template_id}")
def delete_template(template_id: int, me: User = Depends(edit), db: Session = Depends(get_db)) -> dict[str, bool]:
    t = db.get(ProjectTemplate, template_id)
    if t is None:
        raise HTTPException(404, "Şablon bulunamadı")
    audit.record(db, me, "project_template", t.id, "name", t.name, None, action="delete")
    db.delete(t)
    db.commit()
    return {"ok": True}
