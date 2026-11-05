"""Barkod / QR: turns a scanned payload into a record and the actions this user may take on it.
Payloads: STK:<code>, WO:<no>, PO:<no> or a bare stock code. The card shows no money."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, PurchaseOrder, StockItem, User, WorkOrder
from ..permissions import can
from ..services import erp, womaterials
from .deps import any_user, get_db
from app.core.i18n import tx

router = APIRouter(tags=["scan"])

MODULES = ("stock", "purchasing", "workorders")
PREFIXES = {"STK": "stock", "WO": "workorders", "PO": "purchasing"}
# A scanner set to a US layout, typing into a Turkish Q keyboard: what arrives -> what the label says
TURKISH_Q = str.maketrans({"Ş": ":", "ş": ";", "*": "-", "?": "_", ".": "/", "ç": ".", "ö": ",", ";": "|", ",": "\\",
                           "ı": "i", "ğ": "[", "ü": "]"})


class ResolveIn(BaseModel):
    payload: str = Field(min_length=1, max_length=300)


def _stock(me: User, i: StockItem) -> dict[str, Any]:
    return {"type": "stock", "id": i.id, "label": f"{i.code} {i.name}".strip(),
            "actions": ["in", "out", "count"] if can(me, "stock", "edit") else [],
            "detail": {"code": i.code, "name": i.name, "kind_label": erp.ITEM_KINDS.get(i.kind, i.kind), "unit": i.unit,
                       "qty": i.qty, "min_qty": i.min_qty, "location": i.location}}


def _po(me: User, po: PurchaseOrder) -> dict[str, Any]:
    can_receive = can(me, "purchasing", "edit") and po.status in ("sent", "partial")
    lines = [{k: v for k, v in erp.line_out(l).items() if k not in ("unit_price", "amount")} for l in po.lines]
    return {"type": "po", "id": po.id, "label": f"{po.no} {po.firm_name}".strip(), "actions": ["receive"] if can_receive else [],
            "detail": {"no": po.no, "firm_name": po.firm_name, "status": po.status,
                       "status_label": erp.PO_STATUS.get(po.status, po.status),
                       "due_date": po.due_date.isoformat() if po.due_date else None,
                       "lines": [l for l in lines if l["remaining"] > erp.EPS]}}


def _wo(db: Session, me: User, w: WorkOrder) -> dict[str, Any]:
    is_open = w.status in erp.WO_OPEN
    materials = womaterials.materials_out(db, w, can(me, "stock", "view"))
    actions: list[str] = []
    if can(me, "workorders", "edit") and is_open:
        actions = ["start"] if w.status == "planned" else []
        actions += ["complete"] + (["issue"] if materials else [])
    project = db.get(Project, w.project_id) if w.project_id else None
    return {"type": "wo", "id": w.id, "label": f"{w.no} {w.part_no}", "actions": actions,
            "detail": {"no": w.no, "part_no": w.part_no, "description": w.description, "qty": w.qty, "done_qty": w.done_qty,
                       "remaining": max(0.0, erp._num(w.qty - w.done_qty)) if w.status != "closed" else 0.0,
                       "status": w.status, "status_label": erp.WO_STATUS.get(w.status, w.status),
                       "project_name": project.name if project else None, "materials": materials}}


def _find(db: Session, me: User, text: str) -> dict[str, Any] | None:
    head, sep, rest = text.partition(":")
    kind = head.upper() if sep else ""
    module = PREFIXES.get(kind, "stock")
    # Asked before the lookup: without the right, a number that exists looks the same as one that does not
    if not can(me, module, "view"):
        raise HTTPException(403, tx("Bu kaydı görme yetkiniz yok"))
    if kind == "WO":
        w = db.scalar(select(WorkOrder).where(WorkOrder.no == rest.strip()))
        return _wo(db, me, w) if w else None
    if kind == "PO":
        po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.no == rest.strip()))
        return _po(me, po) if po else None
    code = rest.strip() if kind == "STK" else text
    i = db.scalar(select(StockItem).where(StockItem.code == code))
    return _stock(me, i) if i else None


@router.post("/scan/resolve")
def resolve(body: ResolveIn, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if not any(can(me, m, "view") for m in MODULES):
        raise HTTPException(403, tx("Tarama için stok, satın alma veya iş emri yetkisi gerekli"))
    text = body.payload.strip()
    if not text:
        raise HTTPException(400, tx("Boş okuma"))
    denied: HTTPException | None = None
    for candidate in dict.fromkeys((text, text.translate(TURKISH_Q))):
        try:
            hit = _find(db, me, candidate)
        except HTTPException as e:
            denied = e
            continue
        if hit is not None:
            return hit
    raise denied or HTTPException(404, tx("Kayıt bulunamadı: {0}", text))
