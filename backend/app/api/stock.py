"""Stok / depo: stock cards, manual moves (giriş, çıkış, sayım) and the stock ledger."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core import numbers as num
from ..models import Firm, Project, StockItem, StockMove, User
from ..services import audit, conflict, erp, reorder
from ..permissions import require
from .deps import get_db, project_or_404
from app.core.i18n import tx

stock_view, stock_edit = require("stock", "view"), require("stock", "edit")
purchasing_view, purchasing_edit = require("purchasing", "view"), require("purchasing", "edit")

router = APIRouter(tags=["stock"])


class ItemIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=300)
    kind: str = "part"
    unit: str = Field(default="Adet", max_length=20)
    min_qty: float = Field(default=0, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    location: str = Field(default="", max_length=100)
    note: str = ""
    qty: float = Field(default=0, ge=0)       # opening balance
    reorder_qty: float = Field(default=0, ge=0)
    preferred_firm_id: int | None = None


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    kind: str | None = None
    unit: str | None = Field(default=None, max_length=20)
    min_qty: float | None = Field(default=None, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=100)
    note: str | None = None
    reorder_qty: float | None = Field(default=None, ge=0)
    preferred_firm_id: int | None = None
    rev: int | None = None


class ReorderLine(BaseModel):
    item_id: int
    qty: float = Field(gt=0)
    firm_id: int | None = None


class ReorderIn(BaseModel):
    items: list[ReorderLine] = Field(min_length=1)


class MoveIn(BaseModel):
    kind: str            # in | out | count | issue
    qty: float = Field(ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    project_id: int | None = None
    note: str = ""


def _item_or_404(db: Session, item_id: int) -> StockItem:
    i = db.get(StockItem, item_id)
    if i is None:
        raise HTTPException(404, tx("Stok kartı bulunamadı"))
    return i


def _check_firm(db: Session, firm_id: int | None) -> None:
    if firm_id is not None and db.get(Firm, firm_id) is None:
        raise HTTPException(400, tx("Firma bulunamadı"))


@router.get("/stock")
def list_stock(q: str = "", low: bool = False, _: User = Depends(stock_view),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    stmt = select(StockItem).order_by(StockItem.code)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(StockItem.code.ilike(like), StockItem.name.ilike(like), StockItem.location.ilike(like)))
    rows = [erp.stock_out(i) for i in db.scalars(stmt)]
    if low:
        rows = [r for r in rows if r["low"]]
    return {"rows": rows, "kinds": erp.ITEM_KINDS, "move_kinds": erp.MOVE_KINDS,
            "total_value": num.money(sum(r["value"] or 0 for r in rows)), "low_count": sum(1 for r in rows if r["low"])}


@router.get("/stock/reorder")
def reorder_list(_: User = Depends(stock_view), __: User = Depends(purchasing_view),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    """Cards under their minimum. Both rights: it joins stock levels with supplier prices."""
    return {"rows": reorder.suggestions(db)}


@router.post("/stock/reorder/orders", status_code=201)
def reorder_orders(body: ReorderIn, me: User = Depends(purchasing_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    orders = reorder.create_orders(db, me, [r.model_dump() for r in body.items])
    db.commit()
    return {"orders": [{"id": po.id, "no": po.no, "firm_name": po.firm_name, "line_count": len(po.lines)} for po in orders]}


@router.post("/stock", status_code=201)
def create_item(body: ItemIn, me: User = Depends(stock_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    code = body.code.strip()
    if db.scalar(select(StockItem).where(StockItem.code == code)):
        raise HTTPException(409, tx("Bu kodla stok kartı zaten var"))
    if body.kind not in erp.ITEM_KINDS:
        raise HTTPException(400, tx("Geçersiz kalem türü"))
    _check_firm(db, body.preferred_firm_id)
    i = StockItem(code=code, name=body.name.strip(), kind=body.kind, unit=body.unit or "Adet", qty=0.0,
                  min_qty=body.min_qty, unit_cost=body.unit_cost, location=body.location, note=body.note,
                  reorder_qty=body.reorder_qty, preferred_firm_id=body.preferred_firm_id)
    db.add(i)
    db.flush()
    audit.record(db, me, "stock", code, "code", None, code, action="create")
    if body.qty > 0:
        erp.move(db, me, i, "in", body.qty, note="Açılış", unit_cost=body.unit_cost)
    db.commit()
    return erp.stock_out(i)


@router.put("/stock/{item_id}")
def update_item(item_id: int, body: ItemUpdate, me: User = Depends(stock_edit),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    i = _item_or_404(db, item_id)
    conflict.claim(db, i, body.rev, me)
    changes = {k: v for k, v in body.model_dump().items() if k in body.model_fields_set and k != "rev"}
    if "kind" in changes and changes["kind"] not in erp.ITEM_KINDS:
        raise HTTPException(400, tx("Geçersiz kalem türü"))
    for k in ("name", "kind", "unit", "min_qty", "location", "note", "reorder_qty"):
        if k in changes and changes[k] is None:
            del changes[k]
    if "preferred_firm_id" in changes:
        _check_firm(db, changes["preferred_firm_id"])
    audit.record_changes(db, me, i, changes, "stock", i.code)
    db.commit()
    return erp.stock_out(i)


@router.delete("/stock/{item_id}")
def delete_item(item_id: int, me: User = Depends(stock_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    i = _item_or_404(db, item_id)
    if abs(i.qty) > erp.EPS:
        raise HTTPException(400, tx("Stokta miktar olan kart silinemez; önce sayım ile sıfırlayın"))
    if db.scalar(select(StockMove.id).where(StockMove.item_id == i.id, StockMove.project_id.is_not(None)).limit(1)):
        raise HTTPException(400, tx("Projeye hareketi olan kart silinemez: proje maliyeti bu hareketlerden hesaplanır"))
    audit.record(db, me, "stock", i.code, "code", i.code, None, action="delete")
    db.delete(i)
    db.commit()
    return {"ok": True}


@router.post("/stock/{item_id}/moves")
def add_move(item_id: int, body: MoveIn, me: User = Depends(stock_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Manual move. receipt/production are booked by purchase orders and work orders only."""
    i = _item_or_404(db, item_id)
    if body.kind not in ("in", "out", "count", "issue"):
        raise HTTPException(400, tx("Elle yalnızca giriş, çıkış, sayım veya projeye çıkış yapılır"))
    if body.kind == "issue":
        if body.project_id is None:
            raise HTTPException(400, tx("Projeye çıkış için proje seçin"))
        erp.issue_from_stock(db, me, project_or_404(db, body.project_id), i.code, body.qty, body.note)
    else:
        if body.project_id is not None:
            project_or_404(db, body.project_id)
        erp.move(db, me, i, body.kind, body.qty, project_id=body.project_id, note=body.note,
                 unit_cost=body.unit_cost if body.kind == "in" else None)
    db.commit()
    return erp.stock_out(i)


@router.get("/stock/{item_id}/moves")
def item_moves(item_id: int, _: User = Depends(stock_view), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    i = _item_or_404(db, item_id)
    names = dict(db.execute(select(Project.id, Project.name)).all())
    moves = db.scalars(select(StockMove).where(StockMove.item_id == i.id).order_by(StockMove.id.desc()).limit(1000))
    return [erp.move_out(m, i, names.get(m.project_id or 0)) for m in moves]


@router.get("/stock-moves")
def recent_moves(project_id: int | None = None, limit: int = 500, _: User = Depends(stock_view),
                 db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    stmt = select(StockMove, StockItem).join(StockItem).order_by(StockMove.id.desc()).limit(min(max(limit, 1), 5000))
    if project_id is not None:
        stmt = stmt.where(StockMove.project_id == project_id)
    names = dict(db.execute(select(Project.id, Project.name)).all())
    return [erp.move_out(m, i, names.get(m.project_id or 0)) for m, i in db.execute(stmt)]
