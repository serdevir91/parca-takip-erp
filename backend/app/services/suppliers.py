"""Tedarikçi performansı: delivery, spend and returns per firm, and price history per code, from purchase orders."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PurchaseOrder, PurchaseOrderLine, PurchaseReceipt
from . import fx
from .erp import EPS


def receipt_rows(db: Session, po: PurchaseOrder) -> list[dict[str, Any]]:
    """Receipts and reversals of an order, oldest first."""
    lines = {l.id: l for l in po.lines}
    out = []
    for r in db.scalars(select(PurchaseReceipt).where(PurchaseReceipt.po_id == po.id)
                        .order_by(PurchaseReceipt.received_at, PurchaseReceipt.id)):
        l = lines.get(r.line_id or 0)
        out.append({"id": r.id, "line_id": r.line_id, "code": l.code if l else "", "description": l.description if l else "",
                    "unit": l.unit if l else "", "qty": r.qty, "received_at": r.received_at.isoformat() if r.received_at else None,
                    "username": r.username, "note": r.note})
    return out


def _local_day(ts: datetime) -> date:
    """Timestamps are stored in UTC; a due date is a day on the site's calendar."""
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone().date()


def _finished_day(po: PurchaseOrder, receipts: list[PurchaseReceipt]) -> date | None:
    """Day of the receipt that completed the order. A reversal reopens it, so the last completion counts.
    An order that never added up (closed short, or received before receipts were recorded) ends with its last receipt."""
    got: dict[int, float] = defaultdict(float)
    done, last = None, None
    for r in receipts:
        was_done = all(got[l.id] + EPS >= l.qty for l in po.lines)
        got[r.line_id or 0] += r.qty
        if r.qty > 0:
            last = r.received_at
        if not was_done and all(got[l.id] + EPS >= l.qty for l in po.lines):
            done = r.received_at
    end = done or last
    return _local_day(end) if end else None


def performance(db: Session) -> dict[str, Any]:
    """Per firm: on-time rate, average delay (early counts as 0), spend and return rate.
    An order is measured once its outcome is known: finished, or still open past its due date (late so far).
    Orders with no due date, no receipts or an open order not yet due are left out and counted."""
    book = fx.Book(db)
    today = date.today()
    pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.not_in(("draft", "cancelled")))))
    receipts: dict[int, list[PurchaseReceipt]] = defaultdict(list)
    for r in db.scalars(select(PurchaseReceipt).order_by(PurchaseReceipt.received_at, PurchaseReceipt.id)):
        receipts[r.po_id].append(r)
    firms: dict[tuple[int | None, str], dict[str, Any]] = {}
    for po in pos:
        f = firms.setdefault((po.firm_id, po.firm_name), {
            "firm_id": po.firm_id, "firm_name": po.firm_name or "(Firma yok)", "orders": 0, "measured": 0, "on_time": 0,
            "left_out": 0, "delay": 0, "spend": 0.0, "unconverted": defaultdict(float), "in": 0.0, "back": 0.0})
        f["orders"] += 1
        rows = receipts.get(po.id, [])
        f["in"] += sum(r.qty for r in rows if r.qty > 0)
        f["back"] += sum(-r.qty for r in rows if r.qty < 0)
        value = sum(min(l.received_qty, l.qty) * l.unit_price for l in po.lines if l.unit_price is not None)
        rate = book.doc(po.currency, po.rate, po.order_date, po.created_at)
        if rate is None:
            f["unconverted"][po.currency] += value
        else:
            f["spend"] += value * rate
        finished = po.status in ("received", "closed")
        if po.due_date is None or not rows or (not finished and po.due_date >= today):
            f["left_out"] += 1
            continue
        end = _finished_day(po, rows) if finished else today
        if end is None:
            f["left_out"] += 1
            continue
        late = (end - po.due_date).days
        f["measured"] += 1
        f["on_time"] += late <= 0
        f["delay"] += max(late, 0)
    out = []
    for f in firms.values():
        n = f["measured"]
        out.append({"firm_id": f["firm_id"], "firm_name": f["firm_name"], "orders": f["orders"], "measured": n,
                    "left_out": f["left_out"], "on_time": f["on_time"],
                    "on_time_pct": round(100 * f["on_time"] / n, 1) if n else None,
                    "avg_delay_days": round(f["delay"] / n, 1) if n else None, "spend": round(f["spend"], 2),
                    "unconverted": [{"currency": k, "amount": round(v, 2)} for k, v in f["unconverted"].items() if v],
                    "received_qty": round(f["in"], 6), "returned_qty": round(f["back"], 6),
                    "return_pct": round(100 * f["back"] / f["in"], 1) if f["in"] > EPS else 0.0})
    return {"base": book.base, "rows": sorted(out, key=lambda r: -r["spend"])}


def price_history(db: Session, code: str) -> dict[str, Any]:
    """Unit price of one code per order and firm over time, in the base currency. Prices whose rate is unknown are
    shown in their own currency but stay out of last and lowest."""
    book = fx.Book(db)
    q = (select(PurchaseOrderLine, PurchaseOrder).join(PurchaseOrder)
         .where(PurchaseOrderLine.code == code, PurchaseOrderLine.unit_price.is_not(None),
                PurchaseOrder.status.not_in(("draft", "cancelled"))))
    firms: dict[tuple[int | None, str], dict[str, Any]] = {}
    for l, po in db.execute(q):
        day = fx.first_day(po.order_date, po.created_at)
        rate = book.doc(po.currency, po.rate, po.order_date, po.created_at)
        f = firms.setdefault((po.firm_id, po.firm_name), {"firm_id": po.firm_id, "firm_name": po.firm_name or "(Firma yok)",
                                                          "points": []})
        f["points"].append({"date": day.isoformat(), "po_id": po.id, "po_no": po.no, "qty": l.qty,
                            "unit_price": l.unit_price, "currency": po.currency, "rate": rate,
                            "base_price": round(l.unit_price * rate, 4) if rate is not None else None})
    rows = []
    for f in firms.values():
        f["points"].sort(key=lambda p: (p["date"], p["po_id"]))
        known = [p["base_price"] for p in f["points"] if p["base_price"] is not None]
        rows.append({**f, "orders": len(f["points"]), "last_price": known[-1] if known else None,
                     "lowest_price": min(known) if known else None})
    rows.sort(key=lambda r: (r["last_price"] is None, r["last_price"] or 0.0))
    near: list[str] = []
    if not rows:    # a mistyped or partial code: offer what exists
        near = list(db.scalars(select(PurchaseOrderLine.code).where(PurchaseOrderLine.code.icontains(code, autoescape=True))
                               .distinct().order_by(PurchaseOrderLine.code).limit(10)))
    return {"code": code, "base": book.base, "firms": rows, "suggestions": near}
