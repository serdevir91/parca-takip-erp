"""Satış: quotes and sales orders, status flow, sales invoice from an order and the quote form export."""
from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Firm, Project, SalesOrder, User
from ..permissions import require
from ..services import audit, commerce, fx, system
from .deps import get_db, project_or_404

sales_view, sales_edit = require("sales", "view"), require("sales", "edit")
finance_edit = require("finance", "edit")

router = APIRouter(tags=["sales"])


class LineIn(BaseModel):
    code: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=300)
    unit: str = Field(default="Adet", max_length=20)
    qty: float = Field(gt=0)
    unit_price: float | None = Field(default=None, ge=0)


class SoIn(BaseModel):
    firm_id: int | None = None
    firm_name: str = Field(default="", max_length=200)   # walk-in customer without a card
    project_id: int | None = None
    order_date: date | None = None
    valid_until: date | None = None
    due_date: date | None = None
    currency: str = Field(default="", max_length=8)
    rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    discount_pct: float = Field(default=0.0, ge=0, le=100)
    note: str = ""
    lines: list[LineIn] = []


class SoUpdate(BaseModel):
    firm_id: int | None = None
    firm_name: str | None = Field(default=None, max_length=200)
    project_id: int | None = None
    order_date: date | None = None
    valid_until: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, max_length=8)
    rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)    # null = take it from the table again
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    discount_pct: float | None = Field(default=None, ge=0, le=100)
    note: str | None = None
    lines: list[LineIn] | None = None


class StatusIn(BaseModel):
    status: str


class DeliverLine(BaseModel):
    line_id: int
    qty: float = Field(allow_inf_nan=False)     # negative takes goods back


class DeliverIn(BaseModel):
    lines: list[DeliverLine]
    note: str = Field(default="", max_length=300)


class InvoicePick(BaseModel):
    line_id: int
    qty: float = Field(gt=0, allow_inf_nan=False)


class FromSoIn(BaseModel):
    lines: list[InvoicePick] | None = None      # omitted = what was delivered and not billed yet
    rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)


def _so_or_404(db: Session, so_id: int) -> SalesOrder:
    so = db.get(SalesOrder, so_id)
    if so is None:
        raise HTTPException(404, "Sipariş bulunamadı")
    return so


def _out(db: Session, so: SalesOrder) -> dict[str, Any]:
    p = db.get(Project, so.project_id) if so.project_id else None
    out = commerce.so_out(so, True, p.name if p else None, commerce.invoiced_by_so(db).get(so.id, 0.0), fx.Book(db))
    out["deliveries"] = commerce.delivery_rows(db, so)
    return commerce.with_billing(db, so, out)


@router.get("/sales-orders")
def list_orders(status: str | None = None, firm_id: int | None = None, project_id: int | None = None,
                _: User = Depends(sales_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    q = select(SalesOrder).order_by(SalesOrder.id.desc())
    if status == "open":
        q = q.where(SalesOrder.status.in_(commerce.SO_OPEN))
    elif status:
        q = q.where(SalesOrder.status == status)
    if firm_id is not None:
        q = q.where(SalesOrder.firm_id == firm_id)
    if project_id is not None:
        q = q.where(SalesOrder.project_id == project_id)
    names = dict(db.execute(select(Project.id, Project.name)).all())
    inv = commerce.invoiced_by_so(db)
    book = fx.Book(db)
    return {"rows": [commerce.so_out(so, False, names.get(so.project_id or 0), inv.get(so.id, 0.0), book)
                     for so in db.scalars(q)], "statuses": commerce.SO_STATUS, "base": book.base}


@router.post("/sales-orders", status_code=201)
def create_order(body: SoIn, me: User = Depends(sales_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    firm = commerce.firm_or_404(db, body.firm_id)
    if body.project_id is not None:
        project_or_404(db, body.project_id)
    if not firm and not body.firm_name.strip():
        raise HTTPException(400, "Müşteri seçin")
    sets = system.system(db)["commerce"]
    currency = fx.clean_currency(body.currency or sets["currency"])
    so = SalesOrder(no=commerce.next_no(db, SalesOrder), firm_id=firm.id if firm else None,
                    firm_name=firm.name if firm else body.firm_name.strip(), project_id=body.project_id,
                    status="draft", order_date=body.order_date or date.today(), valid_until=body.valid_until,
                    due_date=body.due_date, currency=currency,
                    rate=body.rate if body.rate is not None else fx.rate_on(db, currency, body.order_date),
                    tax_rate=sets["vat"] if body.tax_rate is None else body.tax_rate,
                    discount_pct=body.discount_pct, note=body.note, created_by=me.username)
    commerce.set_so_lines(so, [l.model_dump() for l in body.lines])
    db.add(so)
    db.flush()
    audit.record(db, me, "sales_order", so.no, "no", None, so.no, so.project_id, action="create")
    db.commit()
    return _out(db, so)


@router.get("/sales-orders/{so_id}")
def get_order(so_id: int, _: User = Depends(sales_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _out(db, _so_or_404(db, so_id))


@router.put("/sales-orders/{so_id}")
def update_order(so_id: int, body: SoUpdate, me: User = Depends(sales_edit),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    so = _so_or_404(db, so_id)
    if so.status in ("delivered", "cancelled"):
        raise HTTPException(400, f"{commerce.SO_STATUS[so.status]} durumundaki sipariş düzenlenemez")
    sent = body.model_fields_set
    changes: dict[str, Any] = {}
    if "firm_id" in sent:
        firm = commerce.firm_or_404(db, body.firm_id)
        changes.update(firm_id=firm.id if firm else None,
                       firm_name=firm.name if firm else (body.firm_name or so.firm_name))
    elif body.firm_name is not None and so.firm_id is None:
        changes["firm_name"] = body.firm_name.strip()
    if "project_id" in sent:
        if body.project_id is not None:
            project_or_404(db, body.project_id)
        changes["project_id"] = body.project_id
    for k in ("order_date", "valid_until", "due_date", "currency", "tax_rate", "discount_pct", "note"):
        if k in sent and (getattr(body, k) is not None or k.endswith(("_date", "_until"))):
            changes[k] = getattr(body, k)
    if "currency" in changes:
        changes["currency"] = fx.clean_currency(changes["currency"])
    if "rate" in sent or changes.get("currency", so.currency) != so.currency:
        changes["rate"] = body.rate if body.rate is not None else fx.rate_on(
            db, changes.get("currency", so.currency), fx.first_day(changes.get("order_date"), so.order_date, so.created_at))
    if so.status in commerce.SO_SHIPPING and (
            any(k in changes and changes[k] != getattr(so, k) for k in ("tax_rate", "discount_pct", "currency", "rate"))
            or body.lines is not None):
        raise HTTPException(400, "Onaylanmış siparişin fiyatları değiştirilemez; önce iptal edip yenisini açın")
    audit.record_changes(db, me, so, changes, "sales_order", so.no, so.project_id)
    if body.lines is not None:
        commerce.set_so_lines(so, [l.model_dump() for l in body.lines])
        audit.record(db, me, "sales_order", so.no, "lines", None, len(body.lines), so.project_id)
    db.commit()
    return _out(db, so)


@router.post("/sales-orders/{so_id}/status")
def order_status(so_id: int, body: StatusIn, me: User = Depends(sales_edit),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    so = _so_or_404(db, so_id)
    commerce.set_so_status(db, me, so, body.status)
    db.commit()
    return _out(db, so)


def _picked(so: SalesOrder, rows: list[DeliverLine]) -> list[tuple[Any, float]]:
    by_id = {l.id: l for l in so.lines}
    items = []
    for r in rows:
        if r.line_id not in by_id:
            raise HTTPException(400, f"Satır bu siparişe ait değil: {r.line_id}")
        if r.qty:
            items.append((by_id[r.line_id], r.qty))
    if not items:
        raise HTTPException(400, "Miktar girin")
    return items


@router.post("/sales-orders/{so_id}/deliver")
def deliver(so_id: int, body: DeliverIn, me: User = Depends(sales_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Sevk: positive quantities ship, negative ones come back."""
    so = _so_or_404(db, so_id)
    commerce.deliver(db, me, so, _picked(so, body.lines), body.note)
    db.commit()
    return _out(db, so)


@router.post("/sales-orders/{so_id}/return")
def take_back(so_id: int, body: DeliverIn, me: User = Depends(sales_edit),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    """Müşteriden iade: quantities are positive here."""
    so = _so_or_404(db, so_id)
    items = _picked(so, body.lines)
    if any(q < 0 for _, q in items):
        raise HTTPException(400, "İade miktarı sıfırdan büyük olmalı")
    commerce.deliver(db, me, so, [(l, -q) for l, q in items], body.note)
    db.commit()
    return _out(db, so)


@router.post("/sales-orders/{so_id}/invoice", status_code=201)
def make_invoice(so_id: int, body: FromSoIn | None = None, me: User = Depends(finance_edit),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    """Draft sales invoice from the order (needs finance edit permission)."""
    so = _so_or_404(db, so_id)
    picks = [(l.line_id, l.qty) for l in body.lines] if body and body.lines is not None else None
    inv = commerce.invoice_from_so(db, me, so, picks, body.rate if body else None)
    db.commit()
    return commerce.inv_out(inv)


@router.post("/sales-orders/{so_id}/copy", status_code=201)
def copy_order(so_id: int, me: User = Depends(sales_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    """New draft with the same customer and lines (revised quote, repeat order)."""
    src = _so_or_404(db, so_id)
    so = SalesOrder(no=commerce.next_no(db, SalesOrder), firm_id=src.firm_id, firm_name=src.firm_name,
                    project_id=src.project_id, status="draft", order_date=date.today(), currency=src.currency,
                    rate=fx.rate_on(db, src.currency), tax_rate=src.tax_rate, discount_pct=src.discount_pct, note=src.note, created_by=me.username)
    commerce.set_so_lines(so, [commerce.line_out(l) for l in src.lines])
    db.add(so)
    db.flush()
    audit.record(db, me, "sales_order", so.no, "copy_of", None, src.no, so.project_id, action="create")
    db.commit()
    return _out(db, so)


@router.delete("/sales-orders/{so_id}")
def delete_order(so_id: int, me: User = Depends(sales_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    so = _so_or_404(db, so_id)
    if so.status != "draft":
        raise HTTPException(400, "Yalnızca taslak silinebilir; gönderilmiş teklifi iptal edin")
    audit.record(db, me, "sales_order", so.no, "no", so.no, None, so.project_id, action="delete")
    db.delete(so)
    db.commit()
    return {"ok": True}


@router.get("/sales-orders/{so_id}/xlsx")
def order_xlsx(so_id: int, _: User = Depends(sales_view), db: Session = Depends(get_db)) -> Response:
    """Teklif formu (draft/quoted) or sipariş onayı (confirmed and later) to send to the customer."""
    so = _so_or_404(db, so_id)
    firm = db.get(Firm, so.firm_id) if so.firm_id else None
    project = db.get(Project, so.project_id) if so.project_id else None
    quote_doc = so.status in ("draft", "quoted", "lost")
    d = lambda v: v.strftime("%d.%m.%Y") if v else ""  # noqa: E731
    info = [("Teklif no" if quote_doc else "Sipariş no", so.no), ("Tarih", d(so.order_date)),
            ("Geçerlilik" if quote_doc else "Teslim tarihi", d(so.valid_until if quote_doc else so.due_date)),
            ("Müşteri", so.firm_name),
            ("İletişim", " / ".join(x for x in (firm.contact, firm.phone, firm.email) if x) if firm else ""),
            ("Adres", firm.address if firm else ""),
            ("Vergi dairesi / no", f"{firm.tax_office} {firm.tax_no}".strip() if firm else ""),
            ("Proje", project.name if project else ""), ("Not", so.note)]
    body = commerce.form_xlsx("Fiyat teklifi" if quote_doc else "Sipariş onayı", info, so.currency, so.lines,
                              commerce.totals(so.lines, so.tax_rate, so.discount_pct), so.tax_rate, so.discount_pct,
                              company=system.system(db)["company"])
    name = f"{so.no}.xlsx"
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
