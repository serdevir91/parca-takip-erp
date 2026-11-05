"""Bağlantı elemanı stoğu: every fastener in one list, whether it has a stock card yet or only sits in a BOM.

A row is keyed by the fastener key (type|std|size), which is also the stock card's code. A card is opened by the
first move or setting, so nobody has to create cards by hand before counting the shelf."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, PurchaseOrder, PurchaseOrderLine, StockItem, User
from ..permissions import require
from ..services import audit, erp
from .deps import get_db, project_or_404

stock_view, stock_edit = require("stock", "view"), require("stock", "edit")

router = APIRouter(prefix="/fastener-stock", tags=["fastener-stock"])

MOVES = ("in", "out", "count", "issue")


def _key(type_: str, std: str, size: str) -> str:
    return "|".join(x.strip() for x in (type_, std, size))


def _parts(key: str, name: str) -> tuple[str, str, str]:
    bits = key.split("|")
    return (bits[0], bits[1], bits[2]) if len(bits) == 3 else (name or key, "", "")


def _on_order(db: Session) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for code, qty, got in db.execute(select(PurchaseOrderLine.code, PurchaseOrderLine.qty, PurchaseOrderLine.received_qty)
                                     .join(PurchaseOrder).where(PurchaseOrder.status.in_(erp.PO_OPEN))):
        out[code] += max(0.0, qty - got)
    return out


def _demand(db: Session) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """What open projects still need, per fastener key. A fastener marked delivered by hand needs nothing."""
    need: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: dict[str, dict[str, Any]] = {}
    for p in db.scalars(select(Project).where(Project.archived.is_(False)).order_by(Project.name)):
        for r in erp.requirements(db, p):
            if r["kind"] != "fastener":
                continue
            seen.setdefault(r["code"], r)
            left = 0.0 if r["done"] else max(0.0, r["required"] - r["issued"])
            if left > erp.EPS:
                need[r["code"]].append({"id": p.id, "name": p.name, "required": r["required"],
                                        "issued": r["issued"], "open": erp._num(left)})
    return need, seen


def _row(key: str, card: StockItem | None, projects: list[dict[str, Any]], unit: str, name: str,
         on_order: float) -> dict[str, Any]:
    type_, std, size = _parts(key, card.name if card else name)
    qty = card.qty if card else 0.0
    need = erp._num(sum(p["open"] for p in projects))
    return {"key": key, "item_id": card.id if card else None, "rev": card.edit_rev if card else None,
            "type": type_, "std": std, "size": size, "name": (card.name if card else "") or name,
            "unit": card.unit if card else unit, "qty": qty, "min_qty": card.min_qty if card else 0.0,
            "location": card.location if card else "", "open_need": need, "on_order": erp._num(on_order),
            "shortage": erp._num(max(0.0, need - qty - on_order)), "low": bool(card and card.min_qty > 0 and qty < card.min_qty),
            "projects": projects}


def _description(type_: str, std: str, size: str) -> str:
    return " ".join(x for x in (type_, std, size) if x)


@router.get("")
def overview(_: User = Depends(stock_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    cards = {c.code: c for c in db.scalars(select(StockItem).where(StockItem.kind == "fastener"))}
    need, seen = _demand(db)
    orders = _on_order(db)
    rows = [_row(k, cards.get(k), need.get(k, []), seen[k]["unit"] if k in seen else "Adet",
                 seen[k]["description"] if k in seen else "", orders.get(k, 0.0))
            for k in sorted(set(cards) | set(seen), key=str.casefold)]
    return {"rows": rows, "short_count": sum(1 for r in rows if r["shortage"] > erp.EPS),
            "low_count": sum(1 for r in rows if r["low"]),
            "without_card": sum(1 for r in rows if r["item_id"] is None)}


class CardIn(BaseModel):
    key: str | None = Field(None, max_length=200)    # empty: a new fastener made of the three fields below
    type: str = Field("", max_length=60)
    std: str = Field("", max_length=60)
    size: str = Field("", max_length=60)
    unit: str | None = Field(None, max_length=20)
    min_qty: float | None = Field(None, ge=0)
    location: str | None = Field(None, max_length=100)


class MoveIn(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    kind: str
    qty: float = Field(ge=0)
    project_id: int | None = None
    unit: str | None = Field(None, max_length=20)
    note: str = ""


def _card(db: Session, key: str, unit: str | None) -> StockItem:
    item = db.scalar(select(StockItem).where(StockItem.code == key))
    if item is not None and item.kind != "fastener":
        raise HTTPException(409, f"{key}: bu kod başka türde bir stok kartında kullanılıyor")
    return item or erp.stock_item(db, key, _description(*_parts(key, "")), "fastener", unit or "")


def _saved(db: Session, item: StockItem) -> dict[str, Any]:
    return _row(item.code, item, [], item.unit, item.name, 0.0)


@router.put("/card")
def save_card(body: CardIn, me: User = Depends(stock_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Minimum, shelf and unit of a fastener. Opens the card when there is none yet."""
    key = (body.key or "").strip()
    if not key:
        if not body.type.strip() or not body.size.strip():
            raise HTTPException(400, "Tip ve ölçü gerekli")
        key = _key(body.type, body.std, body.size)
        if db.scalar(select(StockItem).where(StockItem.code == key)) is not None:
            raise HTTPException(409, "Bu bağlantı elemanı zaten listede")
    item = _card(db, key, body.unit)
    for field in ("unit", "min_qty", "location"):
        value = getattr(body, field)
        if value is not None:
            setattr(item, field, value.strip() if isinstance(value, str) else value)
    audit.record(db, me, "stock", item.id, "fastener_card", None, item.code)
    db.commit()
    return _saved(db, item)


@router.post("/move")
def quick_move(body: MoveIn, me: User = Depends(stock_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.kind not in MOVES:
        raise HTTPException(400, "Geçersiz hareket")
    if body.kind != "count" and body.qty <= 0:
        raise HTTPException(400, "Miktar girin")
    item = _card(db, body.key.strip(), body.unit)
    if body.kind == "issue":
        if body.project_id is None:
            raise HTTPException(400, "Projeye çıkış için proje seçin")
        erp.issue_from_stock(db, me, project_or_404(db, body.project_id), item.code, body.qty, body.note)
    else:
        erp.move(db, me, item, body.kind, body.qty, note=body.note)
    db.commit()
    return _saved(db, item)
