"""Finans: sales and purchase invoices, payments (tahsilat / ödeme) and the current account (cari) per firm."""
from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Firm, Invoice, Payment, Project, PurchaseOrder, User
from ..permissions import require
from ..services import audit, commerce, fx, system
from .deps import get_db, project_or_404

finance_view, finance_edit = require("finance", "view"), require("finance", "edit")

router = APIRouter(tags=["finance"])


class LineIn(BaseModel):
    code: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=300)
    unit: str = Field(default="Adet", max_length=20)
    qty: float = Field(gt=0)
    unit_price: float = Field(default=0.0, ge=0)
    source_line_id: int | None = None       # the order line of an invoice made from an order


class InvoiceIn(BaseModel):
    kind: str = "sales"
    no: str = Field(default="", max_length=40)        # purchase: the supplier's invoice number
    firm_id: int | None = None
    firm_name: str = Field(default="", max_length=200)
    project_id: int | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = Field(default="", max_length=8)
    rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    note: str = ""
    lines: list[LineIn] = []


class InvoiceUpdate(BaseModel):
    no: str | None = Field(default=None, max_length=40)
    firm_id: int | None = None
    project_id: int | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, max_length=8)
    rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)    # null = take it from the table again
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    note: str | None = None
    lines: list[LineIn] | None = None


class InvoicePick(BaseModel):
    line_id: int
    qty: float = Field(gt=0, allow_inf_nan=False)


class FromPoIn(BaseModel):
    no: str = Field(max_length=40)
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    lines: list[InvoicePick] | None = None      # omitted = what was received and not billed yet


class StatusIn(BaseModel):
    status: str


class PaymentIn(BaseModel):
    direction: str = "in"
    firm_id: int | None = None
    invoice_id: int | None = None
    pay_date: date | None = None
    amount: float = Field(gt=0)
    currency: str = Field(default="", max_length=8)
    rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    method: str = Field(default="Havale/EFT", max_length=30)
    note: str = ""


def _inv_or_404(db: Session, inv_id: int) -> Invoice:
    inv = db.get(Invoice, inv_id)
    if inv is None:
        raise HTTPException(404, "Fatura bulunamadı")
    return inv


def _out(db: Session, inv: Invoice) -> dict[str, Any]:
    p = db.get(Project, inv.project_id) if inv.project_id else None
    book = fx.Book(db)
    out = commerce.inv_out(inv, commerce.paid_by_invoice(db, [inv.id]).get(inv.id, 0.0), True, p.name if p else None, book)
    out["payments"] = [commerce.pay_out(x, inv.no, book) for x in
                       db.scalars(select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.pay_date))]
    return out


@router.get("/finance/meta")
def meta(_: User = Depends(finance_view)) -> dict[str, Any]:
    return {"kinds": commerce.INV_KINDS, "statuses": commerce.INV_STATUS, "pay_states": commerce.PAY_STATE,
            "directions": commerce.PAY_DIRECTIONS, "methods": commerce.PAY_METHODS}


@router.get("/invoices")
def list_invoices(kind: str | None = None, status: str | None = None, firm_id: int | None = None,
                  project_id: int | None = None, pay_state: str | None = None,
                  _: User = Depends(finance_view), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(Invoice).order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
    if kind:
        q = q.where(Invoice.kind == kind)
    if status:
        q = q.where(Invoice.status == status)
    if firm_id is not None:
        q = q.where(Invoice.firm_id == firm_id)
    if project_id is not None:
        q = q.where(Invoice.project_id == project_id)
    invs = list(db.scalars(q))
    paid = commerce.paid_by_invoice(db, [i.id for i in invs])
    names = dict(db.execute(select(Project.id, Project.name)).all())
    book = fx.Book(db)
    rows = [commerce.inv_out(i, paid.get(i.id, 0.0), False, names.get(i.project_id or 0), book) for i in invs]
    if pay_state == "open":
        rows = [r for r in rows if r["pay_state"] in ("unpaid", "partial", "overdue")]
    elif pay_state:
        rows = [r for r in rows if r["pay_state"] == pay_state]
    return rows


@router.post("/invoices", status_code=201)
def create_invoice(body: InvoiceIn, me: User = Depends(finance_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    firm = commerce.firm_or_404(db, body.firm_id)
    if not firm and not body.firm_name.strip():
        raise HTTPException(400, "Firma seçin")
    if body.project_id is not None:
        project_or_404(db, body.project_id)
    sets = system.system(db)["commerce"]
    currency = fx.clean_currency(body.currency or sets["currency"])
    inv = commerce.new_invoice(db, me, body.kind, firm=firm, no=body.no, project_id=body.project_id,
                               invoice_date=body.invoice_date, due_date=body.due_date, currency=currency,
                               rate=body.rate if body.rate is not None else fx.rate_on(db, currency, body.invoice_date),
                               tax_rate=sets["vat"] if body.tax_rate is None else body.tax_rate, note=body.note)
    if not firm:
        inv.firm_name = body.firm_name.strip()
    commerce.set_inv_lines(inv, [{**l.model_dump(), "source_line_id": None} for l in body.lines])
    db.flush()
    audit.record(db, me, "invoice", inv.no, "no", None, inv.no, inv.project_id, action="create")
    db.commit()
    return _out(db, inv)


@router.post("/purchase-orders/{po_id}/invoice", status_code=201)
def invoice_from_po(po_id: int, body: FromPoIn, me: User = Depends(finance_edit),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "Sipariş bulunamadı")
    inv = commerce.invoice_from_po(db, me, po, body.no,
                                   system.system(db)["commerce"]["vat"] if body.tax_rate is None else body.tax_rate,
                                   [(l.line_id, l.qty) for l in body.lines] if body.lines is not None else None, body.rate)
    db.commit()
    return _out(db, inv)


@router.get("/invoices/{inv_id}")
def get_invoice(inv_id: int, _: User = Depends(finance_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _out(db, _inv_or_404(db, inv_id))


@router.put("/invoices/{inv_id}")
def update_invoice(inv_id: int, body: InvoiceUpdate, me: User = Depends(finance_edit),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    inv = _inv_or_404(db, inv_id)
    if inv.status != "draft":
        raise HTTPException(400, "Yalnızca taslak fatura düzenlenebilir")
    sent = body.model_fields_set
    changes: dict[str, Any] = {}
    if "firm_id" in sent:
        firm = commerce.firm_or_404(db, body.firm_id)
        changes.update(firm_id=firm.id if firm else None, firm_name=firm.name if firm else inv.firm_name)
    if "project_id" in sent:
        if body.project_id is not None:
            project_or_404(db, body.project_id)
        changes["project_id"] = body.project_id
    if body.no is not None and inv.kind == "purchase":
        if not body.no.strip():
            raise HTTPException(400, "Fatura numarası boş olamaz")
        changes["no"] = body.no.strip()
    for k in ("invoice_date", "due_date", "currency", "tax_rate", "note"):
        if k in sent and (getattr(body, k) is not None or k == "due_date"):
            changes[k] = getattr(body, k)
    if "currency" in changes:
        changes["currency"] = fx.clean_currency(changes["currency"])
        if (inv.sales_order_id or inv.purchase_order_id) and changes["currency"] != fx.norm(inv.currency):
            raise HTTPException(400, "Siparişten oluşan faturanın para birimi değiştirilemez")
    if "rate" in sent or changes.get("currency", inv.currency) != inv.currency:
        changes["rate"] = body.rate if body.rate is not None else fx.rate_on(
            db, changes.get("currency", inv.currency),
            fx.first_day(changes.get("invoice_date"), inv.invoice_date, inv.created_at))
    audit.record_changes(db, me, inv, changes, "invoice", inv.no, inv.project_id)
    if body.lines is not None:
        commerce.set_order_inv_lines(db, inv, [l.model_dump() for l in body.lines])
        audit.record(db, me, "invoice", inv.no, "lines", None, len(body.lines), inv.project_id)
    db.commit()
    return _out(db, inv)


@router.post("/invoices/{inv_id}/status")
def invoice_status(inv_id: int, body: StatusIn, me: User = Depends(finance_edit),
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    """draft -> issued (kesildi, counts in the balance) -> cancelled. A paid invoice cannot be cancelled."""
    inv = _inv_or_404(db, inv_id)
    allowed = {"draft": {"issued", "cancelled"}, "issued": {"cancelled"}}.get(inv.status, set())
    if body.status not in allowed:
        raise HTTPException(400, "Bu durum değişikliği yapılamaz")
    if body.status == "issued" and not inv.lines:
        raise HTTPException(400, "Satırı olmayan fatura kesilemez")
    if body.status == "cancelled" and commerce.paid_by_invoice(db, [inv.id]).get(inv.id):
        raise HTTPException(400, "Ödemesi girilmiş fatura iptal edilemez; önce ödemeleri silin")
    if body.status == "issued" and inv.rate is None:
        inv.rate = fx.rate_on(db, inv.currency, fx.first_day(inv.invoice_date, inv.created_at))
    audit.record(db, me, "invoice", inv.no, "status", inv.status, body.status, inv.project_id)
    inv.status = body.status
    db.commit()
    return _out(db, inv)


@router.delete("/invoices/{inv_id}")
def delete_invoice(inv_id: int, me: User = Depends(finance_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    inv = _inv_or_404(db, inv_id)
    if inv.status != "draft":
        raise HTTPException(400, "Yalnızca taslak fatura silinebilir; kesilmiş faturayı iptal edin")
    audit.record(db, me, "invoice", inv.no, "no", inv.no, None, inv.project_id, action="delete")
    db.delete(inv)
    db.commit()
    return {"ok": True}


@router.get("/invoices/{inv_id}/xlsx")
def invoice_xlsx(inv_id: int, _: User = Depends(finance_view), db: Session = Depends(get_db)) -> Response:
    inv = _inv_or_404(db, inv_id)
    firm = db.get(Firm, inv.firm_id) if inv.firm_id else None
    d = lambda v: v.strftime("%d.%m.%Y") if v else ""  # noqa: E731
    info = [("Fatura no", inv.no), ("Fatura tarihi", d(inv.invoice_date)), ("Vade", d(inv.due_date)),
            ("Firma", inv.firm_name), ("Adres", firm.address if firm else ""),
            ("Vergi dairesi / no", f"{firm.tax_office} {firm.tax_no}".strip() if firm else ""), ("Not", inv.note)]
    body = commerce.form_xlsx(commerce.INV_KINDS[inv.kind], info, inv.currency, inv.lines,
                              commerce.totals(inv.lines, inv.tax_rate), inv.tax_rate,
                              company=system.system(db)["company"])
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(inv.no or 'fatura')}.xlsx"})


# ---------- payments ----------
@router.get("/payments")
def list_payments(direction: str | None = None, firm_id: int | None = None, _: User = Depends(finance_view),
                  db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(Payment).order_by(Payment.pay_date.desc(), Payment.id.desc())
    if direction:
        q = q.where(Payment.direction == direction)
    if firm_id is not None:
        q = q.where(Payment.firm_id == firm_id)
    nos = dict(db.execute(select(Invoice.id, Invoice.no)).all())
    book = fx.Book(db)
    return [commerce.pay_out(p, nos.get(p.invoice_id or 0), book) for p in db.scalars(q)]


@router.post("/payments", status_code=201)
def create_payment(body: PaymentIn, me: User = Depends(finance_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.direction not in commerce.PAY_DIRECTIONS:
        raise HTTPException(400, "Yön tahsilat veya ödeme olmalı")
    inv = _inv_or_404(db, body.invoice_id) if body.invoice_id is not None else None
    firm_id = body.firm_id
    currency = fx.clean_currency(body.currency or (inv.currency if inv else system.system(db)["commerce"]["currency"]))
    if inv is not None:
        if currency != fx.norm(inv.currency):
            raise HTTPException(400, f"Faturaya bağlı ödeme faturanın para biriminde ({inv.currency}) girilir")
        if inv.status != "issued":
            raise HTTPException(400, "Ödeme yalnızca kesilmiş faturaya bağlanabilir")
        want = "in" if inv.kind == "sales" else "out"
        if body.direction != want:
            raise HTTPException(400, "Satış faturasına tahsilat, alış faturasına ödeme girilir")
        rest = commerce.inv_out(inv, commerce.paid_by_invoice(db, [inv.id]).get(inv.id, 0.0), False)["remaining"]
        if body.amount > rest + commerce.EPS:
            raise HTTPException(400, f"Tutar faturanın kalan borcundan ({rest:,.2f}) büyük")
        firm_id = inv.firm_id
    firm = commerce.firm_or_404(db, firm_id)
    if firm is None and inv is None:
        raise HTTPException(400, "Firma veya fatura seçin")
    pay_date = body.pay_date or date.today()
    p = Payment(direction=body.direction, firm_id=firm.id if firm else None,
                firm_name=firm.name if firm else (inv.firm_name if inv else ""), invoice_id=inv.id if inv else None,
                pay_date=pay_date, amount=body.amount, currency=currency, method=body.method, note=body.note,
                rate=body.rate if body.rate is not None else fx.rate_on(db, currency, pay_date), created_by=me.username)
    db.add(p)
    db.flush()
    audit.record(db, me, "payment", p.id, "amount", None, p.amount, inv.project_id if inv else None, action="create")
    db.commit()
    return commerce.pay_out(p, inv.no if inv else None)


@router.delete("/payments/{pay_id}")
def delete_payment(pay_id: int, me: User = Depends(finance_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    p = db.get(Payment, pay_id)
    if p is None:
        raise HTTPException(404, "Ödeme bulunamadı")
    audit.record(db, me, "payment", p.id, "amount", p.amount, None, action="delete")
    db.delete(p)
    db.commit()
    return {"ok": True}


# ---------- current account ----------
@router.get("/balances")
def balances(_: User = Depends(finance_view), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return commerce.balances(db)


@router.get("/firms/{firm_id}/ledger")
def ledger(firm_id: int, _: User = Depends(finance_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    firm = commerce.firm_or_404(db, firm_id)
    assert firm is not None
    return {"firm": {"id": firm.id, "name": firm.name, "kind": firm.kind}, **commerce.ledger(db, firm_id)}
