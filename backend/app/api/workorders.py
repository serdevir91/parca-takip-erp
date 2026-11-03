"""İş emirleri: production orders for manufactured parts, in-house or fason (subcontract)."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, User, WorkOrder
from ..services import audit, erp
from ..permissions import require
from .deps import get_db, project_or_404

workorders_view, workorders_edit = require("workorders", "view"), require("workorders", "edit")

router = APIRouter(tags=["work-orders"])


class WoIn(BaseModel):
    project_id: int | None = None
    part_no: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=300)
    qty: float = Field(gt=0)
    firm_name: str = Field(default="", max_length=200)
    start_date: date | None = None
    due_date: date | None = None
    unit_cost: float | None = Field(default=None, ge=0)
    note: str = ""


class WoUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=300)
    qty: float | None = Field(default=None, gt=0)
    firm_name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    due_date: date | None = None
    unit_cost: float | None = Field(default=None, ge=0)
    note: str | None = None


class StatusIn(BaseModel):
    status: str


class CompleteIn(BaseModel):
    qty: float = Field(gt=0)
    note: str = ""


class FromNeedIn(BaseModel):
    codes: list[str] = Field(min_length=1)
    firm_name: str = Field(default="", max_length=200)
    due_date: date | None = None


def _wo_or_404(db: Session, wo_id: int) -> WorkOrder:
    w = db.get(WorkOrder, wo_id)
    if w is None:
        raise HTTPException(404, "İş emri bulunamadı")
    return w


def _out(db: Session, w: WorkOrder) -> dict[str, Any]:
    p = db.get(Project, w.project_id) if w.project_id else None
    return erp.wo_out(w, p.name if p else None)


def _new(db: Session, me: User, **kw: Any) -> WorkOrder:
    w = WorkOrder(no=erp.next_no(db, WorkOrder, "IE"), status="planned", done_qty=0.0, created_by=me.username, **kw)
    db.add(w)
    db.flush()
    audit.record(db, me, "work_order", w.no, "no", None, w.no, w.project_id, action="create")
    return w


@router.get("/work-orders")
def list_work_orders(project_id: int | None = None, status: str | None = None, _: User = Depends(workorders_view),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    q = select(WorkOrder).order_by(WorkOrder.id.desc())
    if project_id is not None:
        q = q.where(WorkOrder.project_id == project_id)
    if status == "open":
        q = q.where(WorkOrder.status.in_(erp.WO_OPEN))
    elif status:
        q = q.where(WorkOrder.status == status)
    names = dict(db.execute(select(Project.id, Project.name)).all())
    return {"rows": [erp.wo_out(w, names.get(w.project_id or 0)) for w in db.scalars(q)], "statuses": erp.WO_STATUS}


@router.post("/work-orders", status_code=201)
def create_work_order(body: WoIn, me: User = Depends(workorders_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.project_id is not None:
        project_or_404(db, body.project_id)
    data = body.model_dump()
    data["part_no"] = data["part_no"].strip()
    data["firm_name"] = data["firm_name"].strip()
    w = _new(db, me, **data)
    db.commit()
    return _out(db, w)


@router.put("/work-orders/{wo_id}")
def update_work_order(wo_id: int, body: WoUpdate, me: User = Depends(workorders_edit),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    w = _wo_or_404(db, wo_id)
    if w.status in ("done", "cancelled"):
        raise HTTPException(400, f"{erp.WO_STATUS[w.status]} durumundaki iş emri düzenlenemez")
    changes = {k: v for k, v in body.model_dump().items() if k in body.model_fields_set}
    for k in ("description", "qty", "firm_name", "note"):
        if k in changes and changes[k] is None:
            del changes[k]
    if "qty" in changes and changes["qty"] + erp.EPS < w.done_qty:
        raise HTTPException(400, "Miktar üretilen miktarın altına indirilemez")
    audit.record_changes(db, me, w, changes, "work_order", w.no, w.project_id)
    db.commit()
    return _out(db, w)


@router.post("/work-orders/{wo_id}/status")
def work_order_status(wo_id: int, body: StatusIn, me: User = Depends(workorders_edit),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    w = _wo_or_404(db, wo_id)
    erp.set_wo_status(db, me, w, body.status)
    db.commit()
    return _out(db, w)


@router.post("/work-orders/{wo_id}/complete")
def complete(wo_id: int, body: CompleteIn, me: User = Depends(workorders_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    w = _wo_or_404(db, wo_id)
    erp.complete_work(db, me, w, body.qty, body.note)
    db.commit()
    return _out(db, w)


@router.delete("/work-orders/{wo_id}")
def delete_work_order(wo_id: int, me: User = Depends(workorders_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    w = _wo_or_404(db, wo_id)
    if w.status != "planned":
        raise HTTPException(400, "Yalnızca planlanmış iş emri silinebilir; başlamış olanı iptal edin")
    audit.record(db, me, "work_order", w.no, "no", w.no, None, w.project_id, action="delete")
    db.delete(w)
    db.commit()
    return {"ok": True}


@router.post("/projects/{pid}/requirements/work-orders", status_code=201)
def need_to_work_orders(pid: int, body: FromNeedIn, me: User = Depends(workorders_edit),
                        db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """One planned work order per chosen part for its shortage."""
    project = project_or_404(db, pid)
    need = {r["code"]: r for r in erp.requirements(db, project)}
    out = []
    for code in dict.fromkeys(body.codes):
        r = need.get(code)
        if r is None or r["kind"] != "part" or r["shortage"] <= 0:
            continue
        w = _new(db, me, project_id=project.id, part_no=code, description=r["description"], qty=r["shortage"],
                 firm_name=body.firm_name.strip(), due_date=body.due_date, unit_cost=r["unit_cost"],
                 note="İhtiyaç analizinden oluşturuldu")
        out.append(w)
    if not out:
        raise HTTPException(400, "Seçilen kalemlerde iş emri açılacak eksik parça yok")
    db.commit()
    return [_out(db, w) for w in out]
