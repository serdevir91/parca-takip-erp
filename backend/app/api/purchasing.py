"""Satın alma: supplier list for pickers, purchase orders, goods receipt and the order form export."""
from __future__ import annotations

import io
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Firm, Project, PurchaseOrder, PurchaseOrderLine, User
from ..services import audit, commerce, erp, system, xlsafe
from ..permissions import can, require
from .deps import any_user, get_db, project_or_404

purchasing_view, purchasing_edit = require("purchasing", "view"), require("purchasing", "edit")
planning_view, stock_edit = require("planning", "view"), require("stock", "edit")

router = APIRouter(tags=["purchasing"])


@router.get("/firms")
def firms(kind: str | None = None, me: User = Depends(any_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Active firms for pickers (the full card editor is under /admin/firms)."""
    q = select(Firm).where(Firm.active.is_(True)).order_by(Firm.name)
    if kind:
        q = q.where(Firm.kind.in_([kind] if kind == "customer" else [kind, "both"]))
    # Contact details only for users who may see the address book
    details = can(me, "contacts", "view")
    return [{"id": f.id, "name": f.name, "kind": f.kind, "lead_days": f.lead_days,
             **({"contact": f.contact, "phone": f.phone, "email": f.email} if details else {})}
            for f in db.scalars(q)]


class LineIn(BaseModel):
    code: str = Field(default="", max_length=200)
    kind: str = "part"
    description: str = Field(default="", max_length=300)
    unit: str = Field(default="Adet", max_length=20)
    qty: float = Field(gt=0)
    unit_price: float | None = Field(default=None, ge=0)


class PoIn(BaseModel):
    firm_id: int | None = None
    project_id: int | None = None
    due_date: date | None = None
    order_date: date | None = None
    currency: str = Field(default="", max_length=8)
    note: str = ""
    lines: list[LineIn] = []


class PoUpdate(BaseModel):
    firm_id: int | None = None
    project_id: int | None = None
    due_date: date | None = None
    order_date: date | None = None
    currency: str | None = Field(default=None, max_length=8)
    note: str | None = None
    lines: list[LineIn] | None = None


class StatusIn(BaseModel):
    status: str


class ReceiveLine(BaseModel):
    line_id: int
    qty: float = Field(ge=0)


class ReceiveIn(BaseModel):
    lines: list[ReceiveLine]
    note: str = ""


def _po_or_404(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "Sipariş bulunamadı")
    return po


def _firm(db: Session, firm_id: int | None) -> Firm | None:
    if firm_id is None:
        return None
    f = db.get(Firm, firm_id)
    if f is None:
        raise HTTPException(404, "Firma bulunamadı")
    return f


def _project_names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Project.id, Project.name)).all())


def _out(db: Session, po: PurchaseOrder, with_lines: bool = True) -> dict[str, Any]:
    p = db.get(Project, po.project_id) if po.project_id else None
    return erp.po_out(po, with_lines, p.name if p else None)


@router.get("/purchase-orders")
def list_orders(project_id: int | None = None, status: str | None = None, firm_id: int | None = None,
                _: User = Depends(purchasing_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    q = select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    if project_id is not None:
        q = q.where(PurchaseOrder.project_id == project_id)
    if status == "open":
        q = q.where(PurchaseOrder.status.in_(erp.PO_OPEN))
    elif status:
        q = q.where(PurchaseOrder.status == status)
    if firm_id is not None:
        q = q.where(PurchaseOrder.firm_id == firm_id)
    names = _project_names(db)
    rows = [erp.po_out(po, False, names.get(po.project_id or 0)) for po in db.scalars(q)]
    return {"rows": rows, "statuses": erp.PO_STATUS}


@router.post("/purchase-orders", status_code=201)
def create_order(body: PoIn, me: User = Depends(purchasing_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    firm = _firm(db, body.firm_id)
    if body.project_id is not None:
        project_or_404(db, body.project_id)
    po = PurchaseOrder(no=erp.next_no(db, PurchaseOrder), firm_id=firm.id if firm else None,
                       firm_name=firm.name if firm else "", project_id=body.project_id, status="draft",
                       due_date=body.due_date, order_date=body.order_date,
                       currency=body.currency or system.system(db)["commerce"]["currency"],
                       note=body.note, created_by=me.username)
    erp.set_lines(po, [l.model_dump() for l in body.lines])
    db.add(po)
    db.flush()
    audit.record(db, me, "purchase_order", po.no, "no", None, po.no, po.project_id, action="create")
    db.commit()
    return _out(db, po)


@router.get("/purchase-orders/{po_id}")
def get_order(po_id: int, _: User = Depends(purchasing_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _out(db, _po_or_404(db, po_id))


@router.put("/purchase-orders/{po_id}")
def update_order(po_id: int, body: PoUpdate, me: User = Depends(purchasing_edit),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    po = _po_or_404(db, po_id)
    if po.status in ("received", "cancelled"):
        raise HTTPException(400, f"{erp.PO_STATUS[po.status]} durumundaki sipariş düzenlenemez")
    sent = body.model_fields_set
    changes: dict[str, Any] = {}
    if "firm_id" in sent:
        firm = _firm(db, body.firm_id)
        changes.update(firm_id=firm.id if firm else None, firm_name=firm.name if firm else "")
    if "project_id" in sent:
        if po.status != "draft":
            raise HTTPException(400, "Proje yalnızca taslak siparişte değiştirilebilir")
        if body.project_id is not None:
            project_or_404(db, body.project_id)
        changes["project_id"] = body.project_id
    for k in ("due_date", "order_date", "currency", "note"):
        if k in sent and (getattr(body, k) is not None or k in ("due_date", "order_date")):
            changes[k] = getattr(body, k)
    audit.record_changes(db, me, po, changes, "purchase_order", po.no, po.project_id)
    if body.lines is not None:
        if po.status != "draft":
            raise HTTPException(400, "Satırlar yalnızca taslak siparişte değiştirilebilir")
        erp.set_lines(po, [l.model_dump() for l in body.lines])
        audit.record(db, me, "purchase_order", po.no, "lines", None, len(body.lines), po.project_id)
    db.commit()
    return _out(db, po)


@router.post("/purchase-orders/{po_id}/status")
def order_status(po_id: int, body: StatusIn, me: User = Depends(purchasing_edit),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    po = _po_or_404(db, po_id)
    erp.set_po_status(db, me, po, body.status)
    db.commit()
    return _out(db, po)


@router.post("/purchase-orders/{po_id}/receive")
def receive(po_id: int, body: ReceiveIn, me: User = Depends(purchasing_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    po = _po_or_404(db, po_id)
    by_id = {l.id: l for l in po.lines}
    items: list[tuple[PurchaseOrderLine, float]] = []
    for r in body.lines:
        line = by_id.get(r.line_id)
        if line is None:
            raise HTTPException(400, f"Satır bu siparişe ait değil: {r.line_id}")
        if r.qty > 0:
            items.append((line, r.qty))
    if not items:
        raise HTTPException(400, "Teslim alınan miktar girin")
    erp.receive(db, me, po, items, body.note)
    db.commit()
    return _out(db, po)


@router.delete("/purchase-orders/{po_id}")
def delete_order(po_id: int, me: User = Depends(purchasing_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    po = _po_or_404(db, po_id)
    if po.status != "draft":
        raise HTTPException(400, "Yalnızca taslak sipariş silinebilir; gönderilmiş siparişi iptal edin")
    audit.record(db, me, "purchase_order", po.no, "no", po.no, None, po.project_id, action="delete")
    db.delete(po)
    db.commit()
    return {"ok": True}


@router.get("/purchase-orders/{po_id}/xlsx")
def order_xlsx(po_id: int, _: User = Depends(purchasing_view), db: Session = Depends(get_db)) -> StreamingResponse:
    """Sipariş formu to send to the supplier."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    po = _po_or_404(db, po_id)
    firm = db.get(Firm, po.firm_id) if po.firm_id else None
    project = db.get(Project, po.project_id) if po.project_id else None
    wb = Workbook()
    ws = wb.active
    ws.title = "Sipariş"
    bold = Font(bold=True)
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws["A1"] = "SATIN ALMA SİPARİŞİ"
    ws["A1"].font = Font(bold=True, size=14)
    commerce.company_header(ws, system.system(db)["company"])
    info = [("Sipariş no", po.no), ("Sipariş tarihi", po.order_date.strftime("%d.%m.%Y") if po.order_date else ""),
            ("Termin", po.due_date.strftime("%d.%m.%Y") if po.due_date else ""),
            ("Firma", po.firm_name), ("İletişim", " / ".join(x for x in (
                firm.contact, firm.phone, firm.email) if x) if firm else ""),
            ("Adres", firm.address if firm else ""),
            ("Vergi dairesi / no", f"{firm.tax_office} {firm.tax_no}".strip() if firm else ""),
            ("Proje", project.name if project else ""), ("Not", po.note)]
    for i, (k, v) in enumerate(info, 3):
        ws.cell(i, 1, k).font = bold
        ws.cell(i, 2, v)
    head = ["#", "Kod", "Açıklama", "Birim", "Miktar", f"Birim fiyat ({po.currency})", f"Tutar ({po.currency})"]
    r0 = len(info) + 4
    fill = PatternFill("solid", fgColor="D9E1F2")
    for c, h in enumerate(head, 1):
        cell = ws.cell(r0, c, h)
        cell.font, cell.fill, cell.border = bold, fill, box
    for i, l in enumerate(po.lines, 1):
        r = r0 + i
        vals: list[Any] = [i, l.code, l.description, l.unit, l.qty, l.unit_price]
        for c, v in enumerate(vals, 1):
            ws.cell(r, c, v).border = box
        amount = ws.cell(r, 7, f"=IF(F{r}=\"\",\"\",E{r}*F{r})")
        amount.border = box
        ws.cell(r, 6).number_format = ws.cell(r, 7).number_format = "#,##0.00"
    last = r0 + len(po.lines)
    ws.cell(last + 1, 6, "Toplam").font = bold
    total = ws.cell(last + 1, 7, f"=SUM(G{r0 + 1}:G{last})" if po.lines else 0)
    total.font, total.number_format = bold, "#,##0.00"
    for col, w in zip("ABCDEFG", (18, 28, 46, 8, 10, 16, 16)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=3, max_row=len(info) + 2, min_col=2, max_col=2):
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    xlsafe.neutralize(wb).save(buf)
    buf.seek(0)
    fname = f"{po.no}.xlsx"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- requirement planning (MRP) ----------
class FromNeedIn(BaseModel):
    codes: list[str] = Field(min_length=1)
    firm_id: int | None = None
    due_date: date | None = None


@router.get("/projects/{pid}/requirements")
def requirements(pid: int, _: User = Depends(planning_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = erp.requirements(db, project_or_404(db, pid))
    return {"rows": rows,
            "summary": {"items": len(rows), "shortage": sum(1 for r in rows if r["shortage"] > 0),
                        "from_stock": sum(1 for r in rows if r["from_stock"] > 0),
                        "covered": sum(1 for r in rows if r["net_need"] <= 0)}}


@router.post("/projects/{pid}/requirements/purchase-order", status_code=201)
def need_to_order(pid: int, body: FromNeedIn, me: User = Depends(purchasing_edit),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    """Draft purchase order for the shortage of the chosen items."""
    project = project_or_404(db, pid)
    firm = _firm(db, body.firm_id)
    need = {r["code"]: r for r in erp.requirements(db, project)}
    lines = []
    for code in dict.fromkeys(body.codes):
        r = need.get(code)
        if r is None or r["shortage"] <= 0:
            continue
        price = r["unit_price"] if r["unit_price"] is not None else r["unit_cost"]
        lines.append({"code": code, "kind": r["kind"], "description": r["description"], "unit": r["unit"],
                      "qty": r["shortage"], "unit_price": price})
    if not lines:
        raise HTTPException(400, "Seçilen kalemlerde eksik yok")
    po = PurchaseOrder(no=erp.next_no(db, PurchaseOrder), firm_id=firm.id if firm else None,
                       firm_name=firm.name if firm else "", project_id=project.id, status="draft",
                       due_date=body.due_date, currency=system.system(db)["commerce"]["currency"],
                       created_by=me.username, note="İhtiyaç analizinden oluşturuldu")
    erp.set_lines(po, lines)
    db.add(po)
    db.flush()
    audit.record(db, me, "purchase_order", po.no, "no", None, po.no, project.id, action="create")
    db.commit()
    return _out(db, po)


class IssueIn(BaseModel):
    code: str
    qty: float | None = Field(default=None, gt=0)
    note: str = ""


@router.post("/projects/{pid}/requirements/issue")
def need_from_stock(pid: int, body: list[IssueIn], me: User = Depends(stock_edit),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    """Stoktan karşıla: issue free stock to the project (qty omitted = what the analysis suggests)."""
    project = project_or_404(db, pid)
    need = {r["code"]: r for r in erp.requirements(db, project)}
    n = 0
    for it in body:
        qty = it.qty if it.qty is not None else need.get(it.code, {}).get("from_stock", 0)
        if qty and qty > 0:
            erp.issue_from_stock(db, me, project, it.code, qty, it.note)
            n += 1
    if not n:
        raise HTTPException(400, "Stoktan karşılanacak kalem yok")
    db.commit()
    return {"issued": n}


@router.get("/projects/{pid}/costs")
def costs(pid: int, me: User = Depends(planning_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    return erp.project_costs(db, project_or_404(db, pid), show_people=can(me, "hr"))
