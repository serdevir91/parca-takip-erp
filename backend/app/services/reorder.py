"""Sipariş önerisi: stock cards under their minimum, and the draft purchase orders made from them.
These functions do not commit; the API layer commits."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Firm, PurchaseOrder, PurchaseOrderLine, StockItem, User
from . import audit, erp, system
from app.core.i18n import tx


def _on_order(db: Session) -> dict[str, float]:
    """What is on its way to free stock. A project's order is left out: its goods are issued to the project on
    receipt, so they never reach the shelf this card's minimum is about."""
    out: dict[str, float] = defaultdict(float)
    for l in db.scalars(select(PurchaseOrderLine).join(PurchaseOrder).where(PurchaseOrder.status.in_(erp.PO_OPEN),
                                                                            PurchaseOrder.project_id.is_(None))):
        out[l.code] += max(0.0, l.qty - l.received_qty)
    return out


def _history(db: Session, codes: list[str], firms: dict[int, Firm]) -> dict[str, dict[str, Any]]:
    """Per code, newest first: the last usable firm and the last price with its currency."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    rows = db.execute(select(PurchaseOrderLine.code, PurchaseOrderLine.unit_price, PurchaseOrder.firm_id, PurchaseOrder.currency)
                      .join(PurchaseOrder).where(PurchaseOrderLine.code.in_(codes), PurchaseOrder.status != "cancelled")
                      .order_by(PurchaseOrder.id.desc(), PurchaseOrderLine.id.desc()))
    for code, price, firm_id, currency in rows:
        h = out[code]
        if "firm" not in h and firm_id in firms:
            h["firm"] = firms[firm_id]
        if "price" not in h and price is not None:
            h["price"], h["currency"] = price, currency
    return out


def _usable_firms(db: Session) -> dict[int, Firm]:
    return {f.id: f for f in db.scalars(select(Firm).where(Firm.active.is_(True)))}


def suggestions(db: Session) -> list[dict[str, Any]]:
    on_order = _on_order(db)
    low = []
    for i in db.scalars(select(StockItem).where(StockItem.min_qty > 0).order_by(StockItem.code)):
        available = erp._num(i.qty + on_order.get(i.code, 0.0))
        if available + erp.EPS < i.min_qty:
            low.append((i, available))
    firms = _usable_firms(db)
    history = _history(db, [i.code for i, _ in low], firms)
    out = []
    for i, available in low:
        h = history.get(i.code, {})
        preferred = firms.get(i.preferred_firm_id or 0)
        firm = preferred or h.get("firm")
        out.append({"item_id": i.id, "code": i.code, "name": i.name, "unit": i.unit, "qty": i.qty, "min_qty": i.min_qty,
                    "on_order": erp._num(on_order.get(i.code, 0.0)), "available": available, "reorder_qty": i.reorder_qty,
                    "suggested_qty": erp._num(max(i.reorder_qty, i.min_qty - available)),
                    "firm_id": firm.id if firm else None, "firm_name": firm.name if firm else "",
                    "firm_source": "preferred" if preferred else "last_order" if firm else "",
                    "firm_missing": i.preferred_firm_id is not None and preferred is None,
                    "last_price": h.get("price"), "last_currency": h.get("currency")})
    return out


def create_orders(db: Session, user: User, rows: list[dict[str, Any]]) -> list[PurchaseOrder]:
    """One draft per firm. Any bad row stops the whole request: the errors name each item and nothing is created."""
    items = {i.id: i for i in db.scalars(select(StockItem).where(StockItem.id.in_([r["item_id"] for r in rows])))}
    firms = _usable_firms(db)
    errors: list[dict[str, Any]] = []
    seen: set[int] = set()
    by_firm: dict[int, list[tuple[StockItem, float]]] = defaultdict(list)
    for r in rows:
        item = items.get(r["item_id"])
        if item is None:
            problem = "Stok kartı bulunamadı"
        elif r["item_id"] in seen:
            problem = "Aynı kalem iki kez seçilmiş"
        elif r.get("firm_id") is None:
            problem = "Firma seçilmemiş"
        elif r["firm_id"] not in firms:
            problem = "Firma bulunamadı veya pasif"
        else:
            seen.add(r["item_id"])
            by_firm[r["firm_id"]].append((item, r["qty"]))
            continue
        errors.append({"item_id": r["item_id"], "code": item.code if item else "", "error": problem})
    if errors:
        names = ", ".join(f'{e["code"] or e["item_id"]}: {e["error"]}' for e in errors[:5])
        raise HTTPException(400, {"message": tx("Sipariş oluşturulmadı. {0}", names), "errors": errors})

    currency = system.system(db)["commerce"]["currency"]
    history = _history(db, [i.code for lines in by_firm.values() for i, _ in lines], firms)
    out = []
    for firm_id, lines in by_firm.items():
        firm = firms[firm_id]
        po = PurchaseOrder(no=erp.next_no(db, PurchaseOrder), firm_id=firm.id, firm_name=firm.name, project_id=None,
                           status="draft", currency=currency, note="Sipariş önerisinden oluşturuldu",
                           created_by=user.username)
        # A price in another currency would be wrong on this order, so that line waits for a price
        erp.set_lines(po, [{"code": i.code, "kind": i.kind, "description": i.name, "unit": i.unit, "qty": qty,
                            "unit_price": history[i.code].get("price") if history[i.code].get("currency") == currency else None}
                           for i, qty in lines])
        db.add(po)
        db.flush()
        audit.record(db, user, "purchase_order", po.no, "no", None, po.no, None, action="create")
        out.append(po)
    return out
