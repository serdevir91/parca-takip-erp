"""Ürün ağacı: build a BOM by hand, keep a draft on the project and send it as a pending BOM version."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core import bomtree
from ..models import BomRow, BomVersion, PartName, User, utcnow
from ..services import bomimport
from ..services.settings import temin_choices
from ..services.tracking import set_names
from .bom import projects_edit, projects_view, version_out
from .deps import get_db, project_or_404
from app.core.i18n import tx

router = APIRouter(prefix="/projects", tags=["bomtree"])


class TreeNode(BaseModel):
    part_no: str = Field(default="", max_length=200)
    name: str = Field(default="", max_length=300)
    assembly: bool = False
    qty: int = Field(default=1, ge=0, le=1_000_000)
    material: str = Field(default="", max_length=200)
    weight: float | None = Field(default=None, ge=0)
    rev: str = Field(default="", max_length=32)
    procurement: str = Field(default="", max_length=64)
    coating: str = Field(default="", max_length=200)
    children: list["TreeNode"] = Field(default_factory=list)


class DraftIn(BaseModel):
    tree: TreeNode
    rev: int | None = None   # the draft this edit started from; None overwrites


class SubmitIn(BaseModel):
    tree: TreeNode
    note: str = Field(default="", max_length=1000)


def _editable(db: Session, pid: int):
    project = project_or_404(db, pid)
    if project.archived:
        raise HTTPException(400, tx("Arşivlenmiş projede ürün ağacı değiştirilemez"))
    return project


@router.get("/{pid}/bom/draft")
def get_draft(pid: int, db: Session = Depends(get_db), _: User = Depends(projects_view)) -> dict[str, Any]:
    return {"draft": project_or_404(db, pid).bom_draft, "temin": temin_choices(db)}


@router.put("/{pid}/bom/draft")
def save_draft(pid: int, body: DraftIn, db: Session = Depends(get_db),
               user: User = Depends(projects_edit)) -> dict[str, Any]:
    project = _editable(db, pid)
    old = project.bom_draft or {}
    if body.rev is not None and body.rev != old.get("rev", 0):
        raise HTTPException(409, tx("Taslağı {0} değiştirdi.", old.get('by') or 'başka biri'))
    project.bom_draft = {"tree": body.tree.model_dump(), "rev": old.get("rev", 0) + 1, "by": user.username,
                         "at": utcnow().isoformat()}
    db.commit()
    return {"rev": project.bom_draft["rev"], "at": project.bom_draft["at"]}


@router.delete("/{pid}/bom/draft")
def delete_draft(pid: int, db: Session = Depends(get_db), _: User = Depends(projects_edit)) -> dict[str, bool]:
    _editable(db, pid).bom_draft = None
    db.commit()
    return {"ok": True}


@router.post("/{pid}/bom/tree/submit", status_code=201)
def submit(pid: int, body: SubmitIn, db: Session = Depends(get_db), user: User = Depends(projects_edit)) -> dict:
    """The tree becomes a pending version; comparing and approving work as for an uploaded file."""
    project = _editable(db, pid)
    root = body.tree.model_dump()
    root["assembly"], root["qty"] = True, 1
    errors = bomtree.validate(root, temin_choices(db))
    if errors:
        more = len(errors) - bomtree.MAX_ERRORS
        raise HTTPException(400, "\n".join(errors[:bomtree.MAX_ERRORS] + ([f"ve {more} hata daha"] if more > 0 else [])))
    try:
        v = bomimport.upload_bom(db, project, f"{bomtree.part_no_of(root)}_urun_agaci.csv", bomtree.to_csv(root),
                                 user, body.note)
    except bomimport.BomImportError as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e
    project.bom_draft = None
    set_names(db, user, bomtree.names_of(root))
    db.commit()
    return version_out(project, v, detail=True)


def _names(db: Session) -> dict[str, str]:
    return {n.part_no: n.name for n in db.scalars(select(PartName))}


def _named(db: Session, tree: dict[str, Any] | None) -> dict[str, Any] | None:
    names = _names(db)

    def walk(n: dict[str, Any]) -> None:
        n["name"] = names.get(n["part_no"], "")
        for c in n["children"]:
            walk(c)
    if tree:
        walk(tree)
    return tree


@router.get("/{pid}/bom/versions/{vid}/tree")
def version_tree(pid: int, vid: int, db: Session = Depends(get_db), _: User = Depends(projects_view)) -> dict:
    project_or_404(db, pid)
    v = db.get(BomVersion, vid)
    if v is None or v.project_id != pid:
        raise HTTPException(404, tx("BOM sürümü bulunamadı"))
    return {"tree": _named(db, bomtree.from_rows(v.rows))}


@router.get("/{pid}/bom/items")
def items(pid: int, q: str = Query("", max_length=100), db: Session = Depends(get_db),
          _: User = Depends(projects_view)) -> list[dict[str, Any]]:
    """Known items from every project, newest values first, so a part is entered once and picked afterwards."""
    project_or_404(db, pid)
    q = q.strip()
    if len(q) < 2:
        return []
    named = db.scalars(select(PartName.part_no).where(PartName.name.icontains(q, autoescape=True)).limit(200)).all()
    ids = db.scalars(select(func.max(BomRow.id)).where(or_(BomRow.part_no.icontains(q, autoescape=True),
                                                           BomRow.file_name.icontains(q, autoescape=True),
                                                           BomRow.part_no.in_(named)))
                     .group_by(BomRow.part_no).order_by(BomRow.part_no).limit(20)).all()
    rows = db.scalars(select(BomRow).where(BomRow.id.in_(ids)).order_by(BomRow.part_no)) if ids else []
    names = _names(db)
    return [{**bomtree.node_of(r), "name": names.get(r.part_no, "")} for r in rows]


@router.get("/{pid}/bom/items/tree")
def item_tree(pid: int, part_no: str = Query(min_length=1, max_length=200), db: Session = Depends(get_db),
              _: User = Depends(projects_view)) -> dict[str, Any]:
    """A sub-assembly with its children, as last used in any project."""
    project_or_404(db, pid)
    r = db.scalar(select(BomRow).where(BomRow.part_no == part_no, BomRow.ext == "SLDASM")
                  .order_by(BomRow.id.desc()).limit(1))
    if r is None:
        raise HTTPException(404, tx("Montaj bulunamadı"))
    rows = db.scalars(select(BomRow).where(BomRow.version_id == r.version_id, or_(
        BomRow.level == r.level, BomRow.level.startswith(r.level + ".", autoescape=True))).order_by(BomRow.seq))
    return {"tree": _named(db, bomtree.from_rows(rows))}
