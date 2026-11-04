"""Ticari modüller: sales orders and quotes, invoices, payments and the per-firm current account (cari).

Money rule: a document total is sum(qty * unit_price), minus the discount, plus KDV (tax_rate %).
A firm's balance is positive when the firm owes us:
  + issued sales invoice, + payment we made (out); - issued purchase invoice, - payment we received (in).
A document keeps its own currency; `fx` converts for totals. A payment on an invoice is always in the invoice's
currency, so an invoice is settled exactly in that currency. A firm's base total values each open balance at
today's rate, so a settled account is zero whatever the rates did in between.
Like `erp`, these functions do not commit; the API layer commits.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (Firm, Invoice, InvoiceLine, Payment, PurchaseOrder, SalesDelivery, SalesOrder, SalesOrderLine,
                      StockItem, StockMove, User)
from . import audit, erp, fx, xlsafe
from .erp import next_no

SO_STATUS = {"draft": "Taslak", "quoted": "Teklif verildi", "confirmed": "Onaylandı", "partial": "Kısmi teslim",
             "delivered": "Teslim edildi", "cancelled": "İptal", "lost": "Kaybedildi"}
SO_OPEN = ("draft", "quoted", "confirmed", "partial")
SO_SHIPPING = ("confirmed", "partial")
# allowed moves; delivered/cancelled/lost are final except that a lost quote can be quoted again.
# partial and the way back to confirmed come from deliveries and returns; goods out must come back before cancelling
SO_NEXT = {"draft": {"quoted", "confirmed", "cancelled"}, "quoted": {"confirmed", "lost", "cancelled", "draft"},
           "confirmed": {"delivered", "cancelled"}, "partial": {"delivered"}, "lost": {"quoted"}, "delivered": set(),
           "cancelled": set()}
INV_STATUS = {"draft": "Taslak", "issued": "Kesildi", "cancelled": "İptal"}
INV_KINDS = {"sales": "Satış faturası", "purchase": "Alış faturası"}
PAY_STATE = {"unpaid": "Ödenmedi", "partial": "Kısmi ödendi", "paid": "Ödendi", "overdue": "Vadesi geçti"}
PAY_DIRECTIONS = {"in": "Tahsilat", "out": "Ödeme"}
PAY_METHODS = ["Havale/EFT", "Nakit", "Kredi kartı", "Çek", "Senet", "Mahsup"]
EPS = 0.005         # money
QTY_EPS = erp.EPS


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def totals(lines: list[Any], tax_rate: float, discount_pct: float = 0.0) -> dict[str, float]:
    sub = sum(l.qty * (l.unit_price or 0.0) for l in lines)
    disc = sub * (discount_pct or 0.0) / 100
    tax = (sub - disc) * (tax_rate or 0.0) / 100
    return {"subtotal": round(sub, 2), "discount": round(disc, 2), "tax": round(tax, 2),
            "total": round(sub - disc + tax, 2)}


def _check_lines(lines: list[dict[str, Any]]) -> None:
    for i, l in enumerate(lines, 1):
        if l["qty"] <= 0:
            raise HTTPException(400, f"Satır {i}: miktar sıfırdan büyük olmalı")
        if not (l.get("code") or "").strip() and not (l.get("description") or "").strip():
            raise HTTPException(400, f"Satır {i}: kod veya açıklama gerekli")


def _line(model: type[Any], i: int, l: dict[str, Any]) -> Any:
    return model(seq=i, code=(l.get("code") or "").strip(), description=(l.get("description") or "").strip(),
                 unit=l.get("unit") or "Adet", qty=float(l["qty"]), unit_price=l.get("unit_price"))


def line_out(l: Any) -> dict[str, Any]:
    out = {"id": l.id, "seq": l.seq, "code": l.code, "description": l.description, "unit": l.unit, "qty": l.qty,
           "unit_price": l.unit_price,
           "amount": round(l.qty * l.unit_price, 2) if l.unit_price is not None else None}
    if isinstance(l, InvoiceLine):
        out["source_line_id"] = l.source_line_id
    elif isinstance(l, SalesOrderLine):
        out.update(delivered_qty=l.delivered_qty, remaining=max(0.0, round(l.qty - l.delivered_qty, 6)))
    return out


def firm_or_404(db: Session, firm_id: int | None) -> Firm | None:
    if firm_id is None:
        return None
    f = db.get(Firm, firm_id)
    if f is None:
        raise HTTPException(404, "Firma bulunamadı")
    return f


# ---------- sales orders / quotes ----------
def so_out(so: SalesOrder, with_lines: bool = True, project_name: str | None = None,
           invoiced: float = 0.0, book: fx.Book | None = None) -> dict[str, Any]:
    t = totals(so.lines, so.tax_rate, so.discount_pct)
    rate = book.doc(so.currency, so.rate, so.order_date, so.created_at) if book else so.rate
    qty = sum(l.qty for l in so.lines)
    out: dict[str, Any] = {
        "id": so.id, "no": so.no, "firm_id": so.firm_id, "firm_name": so.firm_name, "project_id": so.project_id,
        "project_name": project_name, "status": so.status, "status_label": SO_STATUS.get(so.status, so.status),
        "order_date": _iso(so.order_date), "valid_until": _iso(so.valid_until), "due_date": _iso(so.due_date),
        "expired": bool(so.valid_until and so.valid_until < date.today() and so.status in ("draft", "quoted")),
        "late": bool(so.due_date and so.due_date < date.today() and so.status in SO_SHIPPING),
        "currency": so.currency, "rate": so.rate, "base_total": round(t["total"] * rate, 2) if rate is not None else None,
        "delivered_pct": round(100 * sum(min(l.delivered_qty, l.qty) for l in so.lines) / qty, 1) if qty else 0.0,
        "tax_rate": so.tax_rate, "discount_pct": so.discount_pct, "note": so.note,
        "created_at": so.created_at.isoformat() if so.created_at else None, "created_by": so.created_by,
        "line_count": len(so.lines), **t, "invoiced": round(invoiced, 2),
        "missing_price": sum(1 for l in so.lines if l.unit_price is None),
        "next_statuses": sorted(SO_NEXT.get(so.status, set())),
    }
    if with_lines:
        out["lines"] = [line_out(l) for l in so.lines]
    return out


def set_so_lines(so: SalesOrder, lines: list[dict[str, Any]]) -> None:
    _check_lines(lines)
    so.lines.clear()
    so.lines.extend(_line(SalesOrderLine, i, l) for i, l in enumerate(lines, 1))


def set_so_status(db: Session, user: User, so: SalesOrder, status: str) -> None:
    if status not in SO_STATUS:
        raise HTTPException(400, "Geçersiz durum")
    if status == so.status:
        return
    if status not in SO_NEXT.get(so.status, set()):
        raise HTTPException(400, f"{SO_STATUS[so.status]} → {SO_STATUS[status]} geçişi yapılamaz")
    if status in ("quoted", "confirmed") and not so.lines:
        raise HTTPException(400, "Satırı olmayan teklif gönderilemez")
    if status == "delivered":   # "everything went out": same path as a delivery, so stock and history stay right
        deliver(db, user, so, [(l, l.qty - l.delivered_qty) for l in so.lines if l.qty - l.delivered_qty > QTY_EPS])
        return
    if status == "confirmed":
        if so.order_date is None:
            so.order_date = date.today()
        if so.rate is None:
            so.rate = fx.rate_on(db, so.currency, fx.first_day(so.order_date, so.created_at))
    audit.record(db, user, "sales_order", so.no, "status", so.status, status, so.project_id)
    so.status = status


# ---------- deliveries (sevk) and returns ----------
def _sale_moved(db: Session, so: SalesOrder, item: StockItem) -> float:
    """What this order took out of stock so far, net of returns."""
    return -float(db.scalar(select(func.sum(StockMove.qty))
                            .where(StockMove.item_id == item.id, StockMove.ref == so.no,
                                   StockMove.kind.in_(("sale", "sale_return")))) or 0)


def _ship(db: Session, user: User, so: SalesOrder, line: SalesOrderLine, item: StockItem, qty: float, note: str) -> None:
    """Stock goes out once. Goods made or bought for a project already left stock when they were issued to it, so a
    project order ships those first and takes only the rest from free stock."""
    take = qty
    if so.project_id:
        shipped = sum(l.delivered_qty for l in so.lines if l.code == line.code)  # counts this delivery's earlier lines
        held = erp.project_held(db, so.project_id, item.id) - (shipped - _sale_moved(db, so, item))
        take = max(0.0, qty - max(held, 0.0))
    if take > QTY_EPS:
        erp.move(db, user, item, "sale", take, project_id=so.project_id, ref=so.no, note=note)


def _take_back(db: Session, user: User, so: SalesOrder, item: StockItem, qty: float, note: str) -> None:
    """A return goes back to stock only as far as this order took it from stock, at the cost it left."""
    back = min(qty, _sale_moved(db, so, item))
    if back > QTY_EPS:
        cost = db.scalar(select(StockMove.unit_cost).where(StockMove.item_id == item.id, StockMove.ref == so.no,
                                                           StockMove.kind == "sale")
                         .order_by(StockMove.id.desc()).limit(1))
        erp.move(db, user, item, "sale_return", back, project_id=so.project_id, ref=so.no, note=note, unit_cost=cost)


def delivery_rows(db: Session, so: SalesOrder) -> list[dict[str, Any]]:
    """Deliveries and returns of an order, oldest first."""
    lines = {l.id: l for l in so.lines}
    out = []
    for r in db.scalars(select(SalesDelivery).where(SalesDelivery.so_id == so.id)
                        .order_by(SalesDelivery.delivered_at, SalesDelivery.id)):
        l = lines.get(r.line_id or 0)
        out.append({"id": r.id, "line_id": r.line_id, "code": l.code if l else "", "description": l.description if l else "",
                    "unit": l.unit if l else "", "qty": r.qty,
                    "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
                    "username": r.username, "note": r.note})
    return out


def deliver(db: Session, user: User, so: SalesOrder, items: list[tuple[SalesOrderLine, float]], note: str = "") -> None:
    """Sevk: a positive quantity ships, a negative one takes goods back. Each writes a SalesDelivery row."""
    erp.lock_order(db, so)
    for line, qty in items:
        if qty > 0 and so.status not in SO_SHIPPING:
            raise HTTPException(400, "Sevk yalnızca onaylanmış siparişte yapılır")
        if qty < 0 and so.status not in ("partial", "delivered"):
            raise HTTPException(400, "Bu siparişte iade alınacak teslimat yok")
        label = line.code or line.description
        if line.delivered_qty + qty > line.qty + QTY_EPS:
            raise HTTPException(400, f"{label}: en fazla {max(line.qty - line.delivered_qty, 0.0):g} {line.unit} daha "
                                     f"teslim edilebilir (sipariş {line.qty:g}, teslim {line.delivered_qty:g})")
        if line.delivered_qty + qty < -QTY_EPS:
            raise HTTPException(400, f"{label}: teslim edilen {line.delivered_qty:g}, en fazla bu kadar iade alınır")
        item = db.scalar(select(StockItem).where(StockItem.code == line.code)) if line.code else None
        if item is not None:
            if qty > 0:
                _ship(db, user, so, line, item, qty, note)
            else:
                _take_back(db, user, so, item, -qty, note)
        line.delivered_qty = round(line.delivered_qty + qty, 6)
        db.add(SalesDelivery(so_id=so.id, line_id=line.id, qty=qty, username=user.username, note=note[:300]))
        audit.record(db, user, "sales_order", so.no, f"{'sevk' if qty > 0 else 'iade'} {label}", None, abs(qty),
                     so.project_id)
    if all(l.delivered_qty + QTY_EPS >= l.qty for l in so.lines):
        status = "delivered"
    else:
        status = "partial" if any(l.delivered_qty > QTY_EPS for l in so.lines) else "confirmed"
    if status != so.status:
        audit.record(db, user, "sales_order", so.no, "status", so.status, status, so.project_id)
        so.status = status


def invoiced_by_so(db: Session) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    q = select(Invoice).where(Invoice.sales_order_id.is_not(None), Invoice.status != "cancelled")
    for inv in db.scalars(q):
        out[inv.sales_order_id or 0] += totals(inv.lines, inv.tax_rate)["total"]
    return out


# ---------- invoices ----------
def paid_by_invoice(db: Session, ids: list[int] | None = None) -> dict[int, float]:
    q = select(Payment.invoice_id, func.sum(Payment.amount)).where(Payment.invoice_id.is_not(None))
    if ids is not None:
        q = q.where(Payment.invoice_id.in_(ids))
    return {i: float(v or 0) for i, v in db.execute(q.group_by(Payment.invoice_id)).all()}


def inv_out(inv: Invoice, paid: float = 0.0, with_lines: bool = True, project_name: str | None = None,
            book: fx.Book | None = None) -> dict[str, Any]:
    t = totals(inv.lines, inv.tax_rate)
    rate = book.doc(inv.currency, inv.rate, inv.invoice_date, inv.created_at) if book else inv.rate
    remaining = round(max(0.0, t["total"] - paid), 2) if inv.status == "issued" else 0.0
    if inv.status != "issued":
        pay = None
    elif remaining <= EPS:
        pay = "paid"
    elif inv.due_date and inv.due_date < date.today():
        pay = "overdue"
    else:
        pay = "partial" if paid > EPS else "unpaid"
    out: dict[str, Any] = {
        "id": inv.id, "kind": inv.kind, "kind_label": INV_KINDS.get(inv.kind, inv.kind), "no": inv.no,
        "firm_id": inv.firm_id, "firm_name": inv.firm_name, "project_id": inv.project_id, "project_name": project_name,
        "sales_order_id": inv.sales_order_id, "purchase_order_id": inv.purchase_order_id,
        "status": inv.status, "status_label": INV_STATUS.get(inv.status, inv.status),
        "pay_state": pay, "pay_label": PAY_STATE.get(pay or "", ""),
        "invoice_date": _iso(inv.invoice_date), "due_date": _iso(inv.due_date), "currency": inv.currency, "rate": inv.rate,
        "base_total": round(t["total"] * rate, 2) if rate is not None else None,
        "base_remaining": round(remaining * rate, 2) if rate is not None else None, "tax_rate": inv.tax_rate, "note": inv.note, "created_by": inv.created_by, "line_count": len(inv.lines),
        **{k: v for k, v in t.items() if k != "discount"}, "paid": round(paid, 2), "remaining": remaining,
    }
    if with_lines:
        out["lines"] = [line_out(l) for l in inv.lines]
    return out


def set_inv_lines(inv: Invoice, lines: list[dict[str, Any]]) -> None:
    _check_lines(lines)
    inv.lines.clear()
    for i, l in enumerate(lines, 1):
        row = _line(InvoiceLine, i, {**l, "unit_price": l.get("unit_price") or 0.0})
        row.source_line_id = l.get("source_line_id")
        inv.lines.append(row)


# ---------- billing an order line by line ----------
def _got(order: Any, line: Any) -> float:
    return line.delivered_qty if isinstance(order, SalesOrder) else line.received_qty


def billed_by_line(db: Session, order: SalesOrder | PurchaseOrder) -> dict[int, float]:
    """Quantity billed per order line by the order's invoices; cancelled ones free theirs. Invoices from before
    source_line_id count by (code, description), first lines first."""
    link = Invoice.sales_order_id if isinstance(order, SalesOrder) else Invoice.purchase_order_id
    ids = {l.id for l in order.lines}
    billed: dict[int, float] = defaultdict(float)
    old: dict[tuple[str, str], float] = defaultdict(float)
    for inv in db.scalars(select(Invoice).where(link == order.id, Invoice.status != "cancelled")):
        for l in inv.lines:
            if l.source_line_id in ids:
                billed[l.source_line_id] += l.qty
            elif l.source_line_id is None:
                old[(l.code, l.description)] += l.qty
    for l in order.lines:
        take = min(old[(l.code, l.description)], max(0.0, l.qty - billed[l.id]))
        billed[l.id] += take
        old[(l.code, l.description)] -= take
    return billed


def bill_plan(db: Session, order: SalesOrder | PurchaseOrder) -> dict[int, dict[str, float]]:
    """Per order line: billed, room (the most that can still be billed) and suggested (the default of a new invoice).
    The suggestion is what was delivered or received and not billed; on an order with no goods moved yet it is the
    whole rest, an advance invoice. A closed order has nothing more coming, so only what came can be billed."""
    billed = billed_by_line(db, order)
    closed = order.status == "closed"
    moved = any(_got(order, l) > QTY_EPS for l in order.lines)
    plan = {}
    for l in order.lines:
        done = min(_got(order, l), l.qty)
        room = max(0.0, (done if closed else l.qty) - billed[l.id])
        plan[l.id] = {"billed": round(billed[l.id], 6), "room": round(room, 6),
                      "suggested": round(max(0.0, done - billed[l.id]) if moved else room, 6)}
    return plan


def with_billing(db: Session, order: SalesOrder | PurchaseOrder, out: dict[str, Any]) -> dict[str, Any]:
    """Adds billed, billable and to_bill to the lines of an order detail."""
    plan = bill_plan(db, order)
    for row in out.get("lines", []):
        p = plan[row["id"]]
        row.update(billed_qty=p["billed"], billable=p["room"], to_bill=p["suggested"])
    return out


def _chosen_lines(db: Session, order: SalesOrder | PurchaseOrder,
                  picks: list[tuple[int, float]] | None) -> list[tuple[Any, float]]:
    """The caller holds the order's row lock, so two users cannot both bill the same room."""
    plan = bill_plan(db, order)
    if picks is None:
        chosen = [(l, plan[l.id]["suggested"]) for l in order.lines]
    else:
        by_id = {l.id: l for l in order.lines}
        want: dict[int, float] = defaultdict(float)
        for line_id, qty in picks:
            if line_id not in by_id:
                raise HTTPException(400, f"Satır bu siparişe ait değil: {line_id}")
            want[line_id] += qty
        for line_id, qty in want.items():
            if qty > plan[line_id]["room"] + QTY_EPS:
                l = by_id[line_id]
                raise HTTPException(400, f"{l.code or l.description}: en fazla {plan[line_id]['room']:g} {l.unit} "
                                         f"faturalanabilir (sipariş {l.qty:g}, faturalanan {plan[line_id]['billed']:g})")
        chosen = [(by_id[i], q) for i, q in want.items()]
    chosen = [(l, q) for l, q in chosen if q > QTY_EPS]
    if not chosen:
        any_bill = any(p["billed"] > QTY_EPS for p in plan.values())
        raise HTTPException(400, "Bu siparişin faturası zaten var, faturalanacak miktar kalmadı" if any_bill
                            else "Bu siparişte faturalanacak miktar yok")
    return chosen


def set_order_inv_lines(db: Session, inv: Invoice, lines: list[dict[str, Any]]) -> None:
    """Edit a draft invoice. Lines of an order's invoice stay tied to their order lines and under the same limit."""
    order: Any = None
    if inv.sales_order_id:
        order = db.get(SalesOrder, inv.sales_order_id)
    elif inv.purchase_order_id:
        order = db.get(PurchaseOrder, inv.purchase_order_id)
    if order is None:
        set_inv_lines(inv, [{**l, "source_line_id": None} for l in lines])
        return
    erp.lock_order(db, order)
    ids = {l.id for l in order.lines}
    by_text: dict[tuple[str, str], int] = {}
    for l in order.lines:
        by_text.setdefault((l.code, l.description), l.id)
    rows = []
    for l in lines:
        sid = l.get("source_line_id")
        if sid not in ids:
            sid = by_text.get(((l.get("code") or "").strip(), (l.get("description") or "").strip()))
        rows.append({**l, "source_line_id": sid})
    set_inv_lines(inv, rows)
    db.flush()
    plan = bill_plan(db, order)
    touched = {r["source_line_id"] for r in rows}
    for l in order.lines:
        cap = min(_got(order, l), l.qty) if order.status == "closed" else l.qty
        if l.id in touched and plan[l.id]["billed"] > cap + QTY_EPS:
            raise HTTPException(400, f"{l.code or l.description}: toplam faturalanan {plan[l.id]['billed']:g}, "
                                     f"en fazla {cap:g} olabilir")


def new_invoice(db: Session, user: User, kind: str, *, firm: Firm | None, no: str = "", **kw: Any) -> Invoice:
    if kind not in INV_KINDS:
        raise HTTPException(400, "Fatura türü satış veya alış olmalı")
    if kind == "sales":
        no = next_no(db, Invoice)
    elif not no.strip():
        raise HTTPException(400, "Alış faturasında tedarikçinin fatura numarasını girin")
    inv = Invoice(kind=kind, no=no.strip(), firm_id=firm.id if firm else None, firm_name=firm.name if firm else "",
                  status="draft", created_by=user.username, invoice_date=kw.pop("invoice_date", None) or date.today(),
                  **kw)
    db.add(inv)
    return inv


def _invoice_rate(db: Session, order: SalesOrder | PurchaseOrder, rate: float | None) -> float | None:
    """A document rate typed by the user, else the table's rate of today, else the order's."""
    if rate is not None:
        return rate
    found = fx.rate_on(db, order.currency, date.today())
    return found if found is not None else order.rate


def invoice_from_so(db: Session, user: User, so: SalesOrder, picks: list[tuple[int, float]] | None = None,
                    rate: float | None = None) -> Invoice:
    """Sales invoice for the chosen lines and quantities (default: delivered and not billed yet).
    The order discount goes into the unit prices."""
    erp.lock_order(db, so)
    if so.status not in ("confirmed", "partial", "delivered"):
        raise HTTPException(400, "Yalnızca onaylanmış veya teslim edilmiş siparişin faturası kesilir")
    chosen = _chosen_lines(db, so, picks)
    if any(l.unit_price is None for l, _ in chosen):
        raise HTTPException(400, "Fiyatı girilmemiş satır var")
    firm = db.get(Firm, so.firm_id) if so.firm_id else None
    inv = new_invoice(db, user, "sales", firm=firm, project_id=so.project_id, sales_order_id=so.id,
                      currency=so.currency, tax_rate=so.tax_rate, rate=_invoice_rate(db, so, rate),
                      note=f"{so.no} siparişinden" + (f", %{so.discount_pct:g} iskonto" if so.discount_pct else ""))
    if not firm:
        inv.firm_name = so.firm_name
    k = 1 - (so.discount_pct or 0) / 100
    set_inv_lines(inv, [{"code": l.code, "description": l.description, "unit": l.unit, "qty": q,
                         "unit_price": round((l.unit_price or 0) * k, 6), "source_line_id": l.id} for l, q in chosen])
    db.flush()
    audit.record(db, user, "invoice", inv.no, "no", None, inv.no, inv.project_id, action="create")
    return inv


def invoice_from_po(db: Session, user: User, po: PurchaseOrder, no: str, tax_rate: float,
                    picks: list[tuple[int, float]] | None = None, rate: float | None = None) -> Invoice:
    """Purchase invoice for the chosen lines and quantities (default: received and not billed yet)."""
    erp.lock_order(db, po)
    if po.status in ("draft", "cancelled"):
        raise HTTPException(400, "Taslak veya iptal edilmiş siparişin faturası girilemez")
    chosen = _chosen_lines(db, po, picks)
    firm = db.get(Firm, po.firm_id) if po.firm_id else None
    inv = new_invoice(db, user, "purchase", firm=firm, no=no, project_id=po.project_id, purchase_order_id=po.id,
                      currency=po.currency, tax_rate=tax_rate, rate=_invoice_rate(db, po, rate),
                      note=f"{po.no} siparişinden")
    if not firm:
        inv.firm_name = po.firm_name
    set_inv_lines(inv, [{"code": l.code, "description": l.description, "unit": l.unit, "qty": q,
                         "unit_price": l.unit_price or 0.0, "source_line_id": l.id} for l, q in chosen])
    db.flush()
    audit.record(db, user, "invoice", inv.no, "no", None, inv.no, inv.project_id, action="create")
    return inv


# ---------- payments ----------
def pay_out(p: Payment, invoice_no: str | None = None, book: fx.Book | None = None) -> dict[str, Any]:
    rate = book.doc(p.currency, p.rate, p.pay_date, p.created_at) if book else p.rate
    return {"id": p.id, "direction": p.direction, "direction_label": PAY_DIRECTIONS.get(p.direction, p.direction),
            "firm_id": p.firm_id, "firm_name": p.firm_name, "invoice_id": p.invoice_id, "invoice_no": invoice_no,
            "pay_date": _iso(p.pay_date), "amount": round(p.amount, 2), "currency": p.currency, "rate": p.rate,
            "base_amount": round(p.amount * rate, 2) if rate is not None else None, "method": p.method,
            "note": p.note, "created_by": p.created_by}


# ---------- current account (cari) ----------
def _entries(db: Session, firm_id: int | None = None) -> list[dict[str, Any]]:
    """Every balance-moving document as {firm_id, firm_name, date, currency, rate, amount (+ firm owes us), ...}.
    rate is the document's own, None when unknown."""
    book = fx.Book(db)
    rows: list[dict[str, Any]] = []
    q = select(Invoice).where(Invoice.status == "issued")
    if firm_id is not None:
        q = q.where(Invoice.firm_id == firm_id)
    for inv in db.scalars(q):
        total = totals(inv.lines, inv.tax_rate)["total"]
        rows.append({"firm_id": inv.firm_id, "firm_name": inv.firm_name, "date": inv.invoice_date,
                     "due_date": inv.due_date, "currency": inv.currency, "kind": inv.kind, "doc": "invoice",
                     "rate": book.doc(inv.currency, inv.rate, inv.invoice_date, inv.created_at),
                     "id": inv.id, "no": inv.no, "label": INV_KINDS[inv.kind],
                     "amount": total if inv.kind == "sales" else -total})
    q2 = select(Payment)
    if firm_id is not None:
        q2 = q2.where(Payment.firm_id == firm_id)
    for p in db.scalars(q2):
        rows.append({"firm_id": p.firm_id, "firm_name": p.firm_name, "date": p.pay_date, "due_date": None,
                     "currency": p.currency, "kind": p.direction, "doc": "payment", "id": p.id,
                     "rate": book.doc(p.currency, p.rate, p.pay_date, p.created_at),
                     "no": p.method, "label": PAY_DIRECTIONS[p.direction],
                     "amount": -p.amount if p.direction == "in" else p.amount})
    return rows


def balances(db: Session) -> list[dict[str, Any]]:
    """One row per firm and currency: receivable (they owe us), payable (we owe them), overdue amounts, each with
    its base_ value at today's rate. Those are None when the currency has no rate; rows of one firm add up to its
    base total."""
    book = fx.Book(db)
    acc: dict[tuple[Any, str, str], dict[str, float]] = defaultdict(
        lambda: {"sales": 0.0, "purchase": 0.0, "in": 0.0, "out": 0.0})
    for e in _entries(db):
        acc[(e["firm_id"], e["firm_name"], e["currency"])][e["kind"]] += abs(e["amount"])
    # overdue = unpaid remainder of issued invoices past their due date
    overdue: dict[tuple[Any, str, str], dict[str, float]] = defaultdict(lambda: {"sales": 0.0, "purchase": 0.0})
    invs = list(db.scalars(select(Invoice).where(Invoice.status == "issued", Invoice.due_date < date.today())))
    paid = paid_by_invoice(db, [i.id for i in invs])
    for inv in invs:
        rest = totals(inv.lines, inv.tax_rate)["total"] - paid.get(inv.id, 0.0)
        if rest > EPS:
            overdue[(inv.firm_id, inv.firm_name, inv.currency)][inv.kind] += rest
    kinds = dict(db.execute(select(Firm.id, Firm.kind)).all())
    out = []
    for (fid, name, cur), v in acc.items():
        net = v["sales"] - v["in"] - v["purchase"] + v["out"]
        od = overdue.get((fid, name, cur), {"sales": 0.0, "purchase": 0.0})
        rate = book.on(cur)
        base = (lambda x: round(x * rate, 2)) if rate is not None else (lambda x: None)  # noqa: B023
        out.append({"firm_id": fid, "firm_name": name or "(Firma yok)", "firm_kind": kinds.get(fid), "currency": cur,
                    "rate": rate, "base_balance": base(net), "base_receivable": base(max(net, 0)),
                    "base_payable": base(max(-net, 0)), "base_overdue_receivable": base(od["sales"]),
                    "base_overdue_payable": base(od["purchase"]),
                    "sales": round(v["sales"], 2), "collected": round(v["in"], 2),
                    "purchases": round(v["purchase"], 2), "paid": round(v["out"], 2), "balance": round(net, 2),
                    "receivable": round(max(net, 0), 2), "payable": round(max(-net, 0), 2),
                    "overdue_receivable": round(od["sales"], 2), "overdue_payable": round(od["purchase"], 2)})
    return sorted(out, key=lambda r: -abs(r["balance"]))


def ledger(db: Session, firm_id: int) -> dict[str, Any]:
    """Firm statement (cari ekstre): documents by date with a running balance per currency. Each row shows its base
    value at the document's rate; base_balance values what is open at today's rate."""
    rows = sorted(_entries(db, firm_id), key=lambda e: (e["date"] or date.min, e["doc"] != "invoice", e["id"]))
    run: dict[str, float] = defaultdict(float)
    out = []
    for e in rows:
        run[e["currency"]] += e["amount"]
        out.append({"date": _iso(e["date"]), "due_date": _iso(e["due_date"]), "doc": e["doc"], "id": e["id"],
                    "no": e["no"], "label": e["label"], "currency": e["currency"], "rate": e["rate"],
                    "base_amount": round(e["amount"] * e["rate"], 2) if e["rate"] is not None else None,
                    "debit": round(e["amount"], 2) if e["amount"] > 0 else 0.0,
                    "credit": round(-e["amount"], 2) if e["amount"] < 0 else 0.0,
                    "balance": round(run[e["currency"]], 2)})
    book = fx.Book(db)
    rates = {k: book.on(k) for k, v in run.items() if abs(v) > EPS}
    return {"rows": out, "balance": {k: round(v, 2) for k, v in run.items()}, "base": book.base,
            "base_balance": round(sum(run[k] * r for k, r in rates.items() if r is not None), 2),
            "unconverted": sorted(k for k, r in rates.items() if r is None)}


# ---------- printable form ----------
def company_header(ws: Any, c: dict[str, Any]) -> None:
    """Our own name and address, top right of a printed form (empty until set in Sistem Ayarları)."""
    from openpyxl.styles import Font

    rows = [c["name"], c["address"], " / ".join(x for x in (c["phone"], c["email"], c["web"]) if x),
            f'{c["tax_office"]} {c["tax_no"]}'.strip()]
    for i, text in enumerate((x for x in rows if x), 1):
        ws.cell(i, 5, text).font = Font(bold=i == 1 and bool(c["name"]))


def form_xlsx(title: str, info: list[tuple[str, Any]], currency: str, lines: list[Any],
              t: dict[str, float], tax_rate: float, discount_pct: float = 0.0,
              company: dict[str, Any] | None = None) -> bytes:
    """Teklif / sipariş / fatura form as an Excel file (same layout as the purchase order form)."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = title[:30]
    bold = Font(bold=True)
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws["A1"] = title.replace("i", "İ").replace("ı", "I").upper()  # Turkish dotted/dotless i
    ws["A1"].font = Font(bold=True, size=14)
    if company:
        company_header(ws, company)
    for i, (k, v) in enumerate(info, 3):
        ws.cell(i, 1, k).font = bold
        ws.cell(i, 2, v).alignment = Alignment(wrap_text=True, vertical="top")
    head = ["#", "Kod", "Açıklama", "Birim", "Miktar", f"Birim fiyat ({currency})", f"Tutar ({currency})"]
    r0 = len(info) + 4
    fill = PatternFill("solid", fgColor="D9E1F2")
    for c, h in enumerate(head, 1):
        cell = ws.cell(r0, c, h)
        cell.font, cell.fill, cell.border = bold, fill, box
    for i, l in enumerate(lines, 1):
        r = r0 + i
        for c, v in enumerate([i, l.code, l.description, l.unit, l.qty, l.unit_price,
                               round(l.qty * l.unit_price, 2) if l.unit_price is not None else None], 1):
            ws.cell(r, c, v).border = box
        ws.cell(r, 6).number_format = ws.cell(r, 7).number_format = "#,##0.00"
    r = r0 + len(lines) + 1
    sums = [("Ara toplam", t["subtotal"])]
    if discount_pct:
        sums.append((f"İskonto (%{discount_pct:g})", -t["discount"]))
    sums += [(f"KDV (%{tax_rate:g})", t["tax"]), ("Genel toplam", t["total"])]
    for k, v in sums:
        ws.cell(r, 6, k).font = bold
        cell = ws.cell(r, 7, v)
        cell.number_format = "#,##0.00"
        cell.font = bold
        r += 1
    for col, w in zip("ABCDEFG", (18, 28, 46, 8, 10, 18, 16)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    xlsafe.neutralize(wb).save(buf)
    return buf.getvalue()
