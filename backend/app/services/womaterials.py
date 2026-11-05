"""Work order materials and route: issue to the order, return, automatic issue on completion, operation steps.

How material cost is counted exactly once:
- Order with a project: the issue carries the project and ref STOCK_REF, the one ref erp.project_costs prices, so it
  shows as "Stoktan". The order's number goes in the note. WorkOrder.unit_cost stays the conversion cost (labour or
  fason price) and never includes these materials.
- Order without a project: no project to charge yet, so the issue carries the order's number and its value goes into
  the unit cost of the finished parts' production move. A project that later takes those parts from stock pays for
  the material through the average cost.
A return is a reversed issue at the cost it left at, so both routes net to zero.
These functions do not commit; the API layer commits.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..core import numbers as num
from ..models import Project, StockItem, User, WorkOrder, WorkOrderMaterial, WorkOrderOp, utcnow
from . import audit, erp, system

OP_STATUS = {"pending": "Bekliyor", "in_progress": "Devam ediyor", "done": "Tamamlandı"}


def _open_or_400(w: WorkOrder) -> None:
    if w.status in erp.WO_FINAL:
        raise HTTPException(400, f"{erp.WO_STATUS[w.status]} durumundaki iş emri değiştirilemez")


def materials(db: Session, w: WorkOrder) -> list[WorkOrderMaterial]:
    return list(db.scalars(select(WorkOrderMaterial).where(WorkOrderMaterial.wo_id == w.id)
                           .order_by(WorkOrderMaterial.seq, WorkOrderMaterial.id)))


def ops(db: Session, w: WorkOrder) -> list[WorkOrderOp]:
    return list(db.scalars(select(WorkOrderOp).where(WorkOrderOp.wo_id == w.id).order_by(WorkOrderOp.seq, WorkOrderOp.id)))


def materials_out(db: Session, w: WorkOrder, show_stock: bool) -> list[dict[str, Any]]:
    """show_stock: the free stock figure only for users of the stock module."""
    rows = materials(db, w)
    stock = {i.code: i.qty for i in db.scalars(select(StockItem).where(StockItem.code.in_([m.code for m in rows])))}
    return [{"id": m.id, "seq": m.seq, "code": m.code, "description": m.description, "unit": m.unit,
             "planned_qty": m.planned_qty, "issued_qty": m.issued_qty,
             "remaining": max(0.0, erp._num(m.planned_qty - m.issued_qty)), "has_card": m.code in stock,
             "stock_qty": stock.get(m.code) if show_stock else None} for m in rows]


def op_out(o: WorkOrderOp) -> dict[str, Any]:
    return {"id": o.id, "seq": o.seq, "name": o.name, "planned_hours": o.planned_hours, "status": o.status,
            "status_label": OP_STATUS.get(o.status, o.status), "done_by": o.done_by,
            "done_at": o.done_at.isoformat() if o.done_at else None, "note": o.note}


def set_materials(db: Session, user: User, w: WorkOrder, rows: list[dict[str, Any]]) -> None:
    """Replace the list. A row with issued material stays until it is returned, and keeps its code."""
    erp.lock_wo(db, w)
    _open_or_400(w)
    current = {m.id: m for m in materials(db, w)}
    kept: set[int] = set()
    seen: set[str] = set()
    unit = system.system(db)["production"]["unit"]
    for seq, r in enumerate(rows, 1):
        code = r["code"].strip()
        if not code:
            raise HTTPException(400, f"Satır {seq}: malzeme kodu gerekli")
        if code == w.part_no:
            raise HTTPException(400, f"{code}: iş emrinin ürettiği parça kendi malzemesi olamaz")
        if code in seen:
            raise HTTPException(400, f"{code}: aynı malzeme iki kez yazılmış")
        seen.add(code)
        m = current.get(r["id"]) if r.get("id") is not None else None
        if r.get("id") is not None and m is None:
            raise HTTPException(400, f"Satır {seq}: bu iş emrine ait değil")
        if m is None:
            card = db.scalar(select(StockItem).where(StockItem.code == code))
            m = WorkOrderMaterial(wo_id=w.id, code=code, issued_qty=0.0, issued_value=0.0, booked_value=0.0,
                                  description=(r.get("description") or "").strip() or (card.name if card else ""),
                                  unit=(r.get("unit") or "").strip() or (card.unit if card else unit))
            db.add(m)
        else:
            kept.add(m.id)
            if m.issued_qty > erp.EPS and code != m.code:
                raise HTTPException(400, f"{m.code}: çıkışı yapılmış malzemenin kodu değiştirilemez")
            if r["planned_qty"] + erp.EPS < m.issued_qty:
                raise HTTPException(400, f"{m.code}: planlanan miktar çıkılan miktarın altına indirilemez")
            m.code = code
            m.description = (r.get("description") or "").strip() or m.description
            m.unit = (r.get("unit") or "").strip() or m.unit
        m.seq, m.planned_qty = seq, float(r["planned_qty"])
    for mid, m in current.items():
        if mid not in kept:
            if m.issued_qty > erp.EPS:
                raise HTTPException(400, f"{m.code}: çıkışı yapılmış malzeme silinemez; önce iade edin")
            db.delete(m)
    audit.record(db, user, "work_order", w.no, "malzemeler", len(current), len(rows), w.project_id)


def _card(db: Session, code: str) -> StockItem | None:
    return db.scalar(select(StockItem).where(StockItem.code == code))


def _ref(w: WorkOrder) -> str:
    return erp.STOCK_REF if w.project_id else w.no


def _book(db: Session, user: User, w: WorkOrder, m: WorkOrderMaterial, item: StockItem, qty: float, note: str) -> None:
    mv = erp.move(db, user, item, "issue", qty, project_id=w.project_id, ref=_ref(w), note=note or f"{w.no} malzeme")
    m.issued_qty = erp._num(m.issued_qty + qty)
    m.issued_value = round(m.issued_value + qty * (mv.unit_cost or 0.0), 4)
    audit.record(db, user, "work_order", w.no, f"malzeme {m.code}", None, qty, w.project_id)


def _sync(db: Session, user: User, w: WorkOrder, codes: set[str]) -> None:
    project = db.get(Project, w.project_id) if w.project_id else None
    if project is not None:
        erp.sync_delivery(db, user, project, codes)


def issue(db: Session, user: User, w: WorkOrder, m: WorkOrderMaterial, qty: float, note: str = "") -> None:
    erp.lock_wo(db, w)
    _open_or_400(w)
    db.refresh(m)
    item = _card(db, m.code)
    if item is None:
        raise HTTPException(400, f"{m.code}: stok kartı yok")
    _book(db, user, w, m, item, qty, note)
    _sync(db, user, w, {m.code})


def give_back(db: Session, user: User, w: WorkOrder, m: WorkOrderMaterial, qty: float, note: str = "") -> None:
    erp.lock_wo(db, w)
    _open_or_400(w)
    db.refresh(m)
    if qty > m.issued_qty + erp.EPS:
        raise HTTPException(400, f"{m.code}: iade çıkılan miktarı aşamaz (çıkılan {num.text(m.issued_qty)})")
    item = _card(db, m.code)
    if item is None:
        raise HTTPException(400, f"{m.code}: stok kartı yok")
    cost = m.issued_value / m.issued_qty if m.issued_value > 0 else None
    erp.move(db, user, item, "issue_return", qty, project_id=w.project_id, ref=_ref(w), note=note or f"{w.no} malzeme iadesi",
             unit_cost=cost)
    m.issued_qty = erp._num(m.issued_qty - qty)
    m.issued_value = max(0.0, round(m.issued_value - qty * (cost or 0.0), 4)) if m.issued_qty > erp.EPS else 0.0
    audit.record(db, user, "work_order", w.no, f"malzeme iade {m.code}", None, qty, w.project_id)


def consume(db: Session, user: User, w: WorkOrder) -> tuple[list[dict[str, Any]], float]:
    """Bring every material up to its share of done_qty, as far as stock allows.
    A shortage issues what exists and goes in the warnings: the parts were made, so the completion stands.
    Returns the warnings and the material value the finished parts of a project-less order must carry."""
    share = min(1.0, w.done_qty / w.qty) if w.qty > 0 else 1.0
    rows = materials(db, w)
    warnings: list[dict[str, Any]] = []
    codes: set[str] = set()
    for m in rows:
        need = erp._num(m.planned_qty * share - m.issued_qty)
        if need <= erp.EPS:
            continue
        item = _card(db, m.code)
        take = 0.0
        if item is not None:
            db.execute(update(StockItem).where(StockItem.id == item.id).values(qty=StockItem.qty))
            db.refresh(item)
            take = min(need, max(item.qty, 0.0))
        if take > erp.EPS:
            _book(db, user, w, m, item, take, f"{w.no} otomatik malzeme çıkışı")
            codes.add(m.code)
        short = erp._num(need - take)
        if short > erp.EPS:
            audit.record(db, user, "work_order", w.no, f"malzeme eksik {m.code}", None, short, w.project_id)
            reason = "stokta yeterli yok" if item is not None else "stok kartı yok"
            warnings.append({"code": m.code, "description": m.description, "unit": m.unit, "needed": need, "issued": take,
                             "short": short, "message": f"{m.code}: {num.text(short)} {m.unit} çıkılamadı ({reason})"})
    _sync(db, user, w, codes)
    if w.project_id:
        return warnings, 0.0
    value = sum(m.issued_value - m.booked_value for m in rows)
    if value <= erp.EPS:
        return warnings, 0.0
    for m in rows:
        m.booked_value = m.issued_value
    return warnings, value


def set_ops(db: Session, user: User, w: WorkOrder, rows: list[dict[str, Any]]) -> None:
    """Replace the route. A step that has started stays; its status never changes here."""
    erp.lock_wo(db, w)
    _open_or_400(w)
    current = {o.id: o for o in ops(db, w)}
    kept: set[int] = set()
    for seq, r in enumerate(rows, 1):
        name = r["name"].strip()
        if not name:
            raise HTTPException(400, f"Satır {seq}: operasyon adı gerekli")
        o = current.get(r["id"]) if r.get("id") is not None else None
        if r.get("id") is not None and o is None:
            raise HTTPException(400, f"Satır {seq}: bu iş emrine ait değil")
        if o is None:
            o = WorkOrderOp(wo_id=w.id, status="pending", done_by="")
            db.add(o)
        else:
            kept.add(o.id)
        o.seq, o.name, o.planned_hours, o.note = seq, name, r.get("planned_hours"), (r.get("note") or "").strip()
    for oid, o in current.items():
        if oid not in kept:
            if o.status != "pending":
                raise HTTPException(400, f"{o.name}: başlamış operasyon silinemez")
            db.delete(o)
    audit.record(db, user, "work_order", w.no, "operasyonlar", len(current), len(rows), w.project_id)


def set_op_status(db: Session, user: User, w: WorkOrder, o: WorkOrderOp, status: str) -> None:
    if status not in OP_STATUS:
        raise HTTPException(400, "Durum bekliyor, devam ediyor veya tamamlandı olabilir")
    erp.lock_wo(db, w)
    _open_or_400(w)
    db.refresh(o)
    if o.status == status:
        return
    if w.status == "planned" and status != "pending":
        erp.set_wo_status(db, user, w, "in_progress")
    audit.record(db, user, "work_order", w.no, f"operasyon {o.name}", o.status, status, w.project_id)
    o.status = status
    o.done_by = user.username if status == "done" else ""
    o.done_at = utcnow() if status == "done" else None
