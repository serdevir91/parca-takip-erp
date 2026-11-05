"""İş emirleri: production orders for manufactured parts, in-house or fason (subcontract)."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import Project, User, WorkOrder, WorkOrderMaterial, WorkOrderOp
from ..services import audit, conflict, erp, womaterials
from ..permissions import can, require
from .deps import get_db, project_or_404
from app.core.i18n import tx

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
    rev: int | None = None


class StatusIn(BaseModel):
    status: str


class CompleteIn(BaseModel):
    qty: float = Field(gt=0)
    note: str = ""


class FromNeedIn(BaseModel):
    codes: list[str] = Field(min_length=1)
    firm_name: str = Field(default="", max_length=200)
    due_date: date | None = None


class MaterialIn(BaseModel):
    id: int | None = None
    code: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=300)
    unit: str = Field(default="", max_length=20)
    planned_qty: float = Field(gt=0)


class MaterialsIn(BaseModel):
    rows: list[MaterialIn]
    rev: int | None = None


class IssueIn(BaseModel):
    qty: float = Field(gt=0)
    note: str = Field(default="", max_length=300)


class OpIn(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    planned_hours: float | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=300)


class OpsIn(BaseModel):
    rows: list[OpIn]
    rev: int | None = None


def _wo_or_404(db: Session, wo_id: int) -> WorkOrder:
    w = db.get(WorkOrder, wo_id)
    if w is None:
        raise HTTPException(404, tx("İş emri bulunamadı"))
    return w


def _material_or_404(db: Session, w: WorkOrder, mid: int) -> WorkOrderMaterial:
    m = db.get(WorkOrderMaterial, mid)
    if m is None or m.wo_id != w.id:
        raise HTTPException(404, tx("Malzeme bulunamadı"))
    return m


def _op_or_404(db: Session, w: WorkOrder, op_id: int) -> WorkOrderOp:
    o = db.get(WorkOrderOp, op_id)
    if o is None or o.wo_id != w.id:
        raise HTTPException(404, tx("Operasyon bulunamadı"))
    return o


def _op_counts(db: Session, wo_id: int | None = None) -> dict[int, tuple[int, int]]:
    """Work order id -> (steps done, steps in total)."""
    q = select(WorkOrderOp.wo_id, func.sum(case((WorkOrderOp.status == "done", 1), else_=0)), func.count()) \
        .group_by(WorkOrderOp.wo_id)
    if wo_id is not None:
        q = q.where(WorkOrderOp.wo_id == wo_id)
    return {i: (int(d or 0), int(n)) for i, d, n in db.execute(q)}


def _out(db: Session, w: WorkOrder) -> dict[str, Any]:
    p = db.get(Project, w.project_id) if w.project_id else None
    return erp.wo_out(w, p.name if p else None, _op_counts(db, w.id).get(w.id, (0, 0)))


def _new(db: Session, me: User, **kw: Any) -> WorkOrder:
    w = WorkOrder(no=erp.next_no(db, WorkOrder), status="planned", done_qty=0.0, created_by=me.username, **kw)
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
    counts = _op_counts(db)
    return {"rows": [erp.wo_out(w, names.get(w.project_id or 0), counts.get(w.id, (0, 0))) for w in db.scalars(q)],
            "statuses": erp.WO_STATUS}


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
    conflict.claim(db, w, body.rev, me)
    if w.status in erp.WO_FINAL:
        raise HTTPException(400, tx("{0} durumundaki iş emri düzenlenemez", erp.WO_STATUS[w.status]))
    changes = {k: v for k, v in body.model_dump().items() if k in body.model_fields_set and k != "rev"}
    for k in ("description", "qty", "firm_name", "note"):
        if k in changes and changes[k] is None:
            del changes[k]
    if "qty" in changes and changes["qty"] + erp.EPS < w.done_qty:
        raise HTTPException(400, tx("Miktar üretilen miktarın altına indirilemez"))
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
    warnings = erp.complete_work(db, me, w, body.qty, body.note)
    db.commit()
    return {**_out(db, w), "warnings": warnings}


@router.delete("/work-orders/{wo_id}")
def delete_work_order(wo_id: int, me: User = Depends(workorders_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    w = _wo_or_404(db, wo_id)
    if w.status != "planned":
        raise HTTPException(400, tx("Yalnızca planlanmış iş emri silinebilir; başlamış olanı iptal edin"))
    if any(m.issued_qty > erp.EPS for m in womaterials.materials(db, w)):
        raise HTTPException(400, tx("Malzeme çıkılmış iş emri silinemez; önce malzemeyi iade edin"))
    audit.record(db, me, "work_order", w.no, "no", w.no, None, w.project_id, action="delete")
    db.delete(w)
    db.commit()
    return {"ok": True}


def _materials_out(db: Session, me: User, w: WorkOrder) -> list[dict[str, Any]]:
    return womaterials.materials_out(db, w, can(me, "stock", "view"))


@router.get("/work-orders/{wo_id}/materials")
def get_materials(wo_id: int, me: User = Depends(workorders_view), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return _materials_out(db, me, _wo_or_404(db, wo_id))


@router.put("/work-orders/{wo_id}/materials")
def put_materials(wo_id: int, body: MaterialsIn, me: User = Depends(workorders_edit),
                  db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    w = _wo_or_404(db, wo_id)
    conflict.claim(db, w, body.rev, me)
    womaterials.set_materials(db, me, w, [r.model_dump() for r in body.rows])
    db.commit()
    return _materials_out(db, me, w)


@router.post("/work-orders/{wo_id}/materials/{mid}/issue")
def issue_material(wo_id: int, mid: int, body: IssueIn, me: User = Depends(workorders_edit),
                   db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """workorders edit is enough, stock rights are not needed: handing material to an order is the planner's job."""
    w = _wo_or_404(db, wo_id)
    womaterials.issue(db, me, w, _material_or_404(db, w, mid), body.qty, body.note)
    db.commit()
    return _materials_out(db, me, w)


@router.post("/work-orders/{wo_id}/materials/{mid}/return")
def return_material(wo_id: int, mid: int, body: IssueIn, me: User = Depends(workorders_edit),
                    db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    w = _wo_or_404(db, wo_id)
    womaterials.give_back(db, me, w, _material_or_404(db, w, mid), body.qty, body.note)
    db.commit()
    return _materials_out(db, me, w)


@router.get("/work-orders/{wo_id}/ops")
def get_ops(wo_id: int, _: User = Depends(workorders_view), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [womaterials.op_out(o) for o in womaterials.ops(db, _wo_or_404(db, wo_id))]


@router.put("/work-orders/{wo_id}/ops")
def put_ops(wo_id: int, body: OpsIn, me: User = Depends(workorders_edit),
            db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    w = _wo_or_404(db, wo_id)
    conflict.claim(db, w, body.rev, me)
    womaterials.set_ops(db, me, w, [r.model_dump() for r in body.rows])
    db.commit()
    return [womaterials.op_out(o) for o in womaterials.ops(db, w)]


@router.post("/work-orders/{wo_id}/ops/{op_id}/status")
def op_status(wo_id: int, op_id: int, body: StatusIn, me: User = Depends(workorders_edit),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    w = _wo_or_404(db, wo_id)
    o = _op_or_404(db, w, op_id)
    womaterials.set_op_status(db, me, w, o, body.status)
    db.commit()
    return {**_out(db, w), "op": womaterials.op_out(o)}


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
        raise HTTPException(400, tx("Seçilen kalemlerde iş emri açılacak eksik parça yok"))
    db.commit()
    return [_out(db, w) for w in out]
