"""Personel ve zaman: employee cards and time entries (work hours per project / work order).
Hours with a known hourly cost show up in the project cost as "İşçilik"."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Employee, Project, TimeEntry, User, WorkOrder
from ..permissions import require
from ..services import audit
from .deps import any_user, get_db, project_or_404

hr_view, hr_edit = require("hr", "view"), require("hr", "edit")

router = APIRouter(tags=["hr"])


class EmployeeIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=100)
    department: str = Field(default="", max_length=100)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=120)
    hourly_cost: float | None = Field(default=None, ge=0)
    start_date: date | None = None
    active: bool = True
    note: str = ""
    user_id: int | None = None


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    hourly_cost: float | None = Field(default=None, ge=0)
    start_date: date | None = None
    active: bool | None = None
    note: str | None = None
    user_id: int | None = None


class TimeIn(BaseModel):
    employee_id: int
    work_date: date | None = None
    hours: float = Field(gt=0, le=24)
    project_id: int | None = None
    work_order_id: int | None = None
    note: str = Field(default="", max_length=300)


def _emp_out(e: Employee, hours_30d: float = 0.0) -> dict[str, Any]:
    return {"id": e.id, "name": e.name, "title": e.title, "department": e.department, "phone": e.phone,
            "email": e.email, "hourly_cost": e.hourly_cost,
            "start_date": e.start_date.isoformat() if e.start_date else None, "active": e.active, "note": e.note,
            "user_id": e.user_id, "hours_30d": round(hours_30d, 2)}


def _emp_or_404(db: Session, emp_id: int) -> Employee:
    e = db.get(Employee, emp_id)
    if e is None:
        raise HTTPException(404, "Personel bulunamadı")
    return e


def _check_user(db: Session, user_id: int | None, emp_id: int | None = None) -> None:
    """A login belongs to at most one personnel card."""
    if user_id is None:
        return
    if db.get(User, user_id) is None:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    other = db.scalar(select(Employee).where(Employee.user_id == user_id, Employee.id != (emp_id or 0)))
    if other is not None:
        raise HTTPException(409, f"Bu kullanıcı zaten {other.name} kartına bağlı")


def _my_card(db: Session, me: User) -> Employee | None:
    """The card linked to this login; a card with the same e-mail counts when no card is linked yet."""
    e = db.scalar(select(Employee).where(Employee.user_id == me.id))
    if e is None and (me.email or "").strip():
        e = db.scalar(select(Employee).where(Employee.user_id.is_(None),
                                             func.lower(Employee.email) == me.email.strip().lower()))
    return e


@router.get("/hr/me")
def my_card(me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Every employee sees only their own card and hours, with no hr rights needed."""
    e = _my_card(db, me)
    if e is None:
        return {"employee": None, "rows": [], "total_hours": 0.0, "total_cost": 0.0}
    since = date.today() - timedelta(days=90)
    q = (select(TimeEntry).where(TimeEntry.employee_id == e.id, TimeEntry.work_date >= since)
         .order_by(TimeEntry.work_date.desc(), TimeEntry.id.desc()))
    projects = dict(db.execute(select(Project.id, Project.name)).all())
    wos = dict(db.execute(select(WorkOrder.id, WorkOrder.no)).all())
    rows = [_time_out(t, e.name, projects.get(t.project_id or 0), wos.get(t.work_order_id or 0))
            for t in db.scalars(q.limit(500))]
    month = date.today().replace(day=1).isoformat()
    return {"employee": _emp_out(e, sum(r["hours"] for r in rows
                                        if r["work_date"] >= (date.today() - timedelta(days=30)).isoformat())),
            "rows": rows, "total_hours": round(sum(r["hours"] for r in rows), 2),
            "month_hours": round(sum(r["hours"] for r in rows if r["work_date"] >= month), 2),
            "total_cost": round(sum(r["cost"] or 0.0 for r in rows), 2)}


@router.get("/hr/users")
def linkable_users(_: User = Depends(hr_edit), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Logins for the "Kullanıcı hesabı" picker on the personnel card."""
    q = select(User).where(User.pending.is_(False)).order_by(User.full_name, User.username)
    return [{"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email} for u in db.scalars(q)]


@router.get("/employees")
def list_employees(active: bool | None = None, _: User = Depends(hr_view),
                   db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(Employee).order_by(Employee.active.desc(), Employee.name)
    if active is not None:
        q = q.where(Employee.active.is_(active))
    since = date.today() - timedelta(days=30)
    hours: dict[int, float] = defaultdict(float)
    for eid, h in db.execute(select(TimeEntry.employee_id, TimeEntry.hours).where(TimeEntry.work_date >= since)):
        hours[eid] += h
    return [_emp_out(e, hours[e.id]) for e in db.scalars(q)]


@router.post("/employees", status_code=201)
def create_employee(body: EmployeeIn, me: User = Depends(hr_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    _check_user(db, body.user_id)
    e = Employee(**{**body.model_dump(), "name": body.name.strip()})
    db.add(e)
    db.flush()
    audit.record(db, me, "employee", e.id, "name", None, e.name, action="create")
    db.commit()
    return _emp_out(e)


@router.put("/employees/{emp_id}")
def update_employee(emp_id: int, body: EmployeeUpdate, me: User = Depends(hr_edit),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _emp_or_404(db, emp_id)
    changes = {k: getattr(body, k) for k in body.model_fields_set
               if getattr(body, k) is not None or k in ("hourly_cost", "start_date", "user_id")}
    if "user_id" in changes:
        _check_user(db, changes["user_id"], e.id)
    audit.record_changes(db, me, e, changes, "employee", e.id)
    db.commit()
    return _emp_out(e)


@router.delete("/employees/{emp_id}")
def delete_employee(emp_id: int, me: User = Depends(hr_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Delete only without time entries; otherwise mark the employee inactive (keeps the labor cost history)."""
    e = _emp_or_404(db, emp_id)
    if db.scalar(select(TimeEntry.id).where(TimeEntry.employee_id == e.id).limit(1)):
        raise HTTPException(400, "Zaman kaydı olan personel silinemez; pasif yapın")
    audit.record(db, me, "employee", e.id, "name", e.name, None, action="delete")
    db.delete(e)
    db.commit()
    return {"ok": True}


def _time_out(t: TimeEntry, emp: str, project: str | None, wo: str | None) -> dict[str, Any]:
    return {"id": t.id, "employee_id": t.employee_id, "employee_name": emp, "work_date": t.work_date.isoformat(),
            "hours": t.hours, "project_id": t.project_id, "project_name": project, "work_order_id": t.work_order_id,
            "work_order_no": wo, "hourly_cost": t.hourly_cost,
            "cost": round(t.hours * t.hourly_cost, 2) if t.hourly_cost is not None else None,
            "note": t.note, "created_by": t.created_by}


@router.get("/time-entries")
def list_time(employee_id: int | None = None, project_id: int | None = None, date_from: date | None = None,
              date_to: date | None = None, _: User = Depends(hr_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    q = (select(TimeEntry, Employee.name).join(Employee)
         .order_by(TimeEntry.work_date.desc(), TimeEntry.id.desc()))
    if employee_id is not None:
        q = q.where(TimeEntry.employee_id == employee_id)
    if project_id is not None:
        q = q.where(TimeEntry.project_id == project_id)
    if date_from:
        q = q.where(TimeEntry.work_date >= date_from)
    if date_to:
        q = q.where(TimeEntry.work_date <= date_to)
    projects = dict(db.execute(select(Project.id, Project.name)).all())
    wos = dict(db.execute(select(WorkOrder.id, WorkOrder.no)).all())
    rows = [_time_out(t, name, projects.get(t.project_id or 0), wos.get(t.work_order_id or 0))
            for t, name in db.execute(q.limit(2000))]
    by_project: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        acc = by_project[r["project_name"] or "(Proje dışı)"]
        acc[0] += r["hours"]
        acc[1] += r["cost"] or 0.0
    return {"rows": rows, "total_hours": round(sum(r["hours"] for r in rows), 2),
            "total_cost": round(sum(r["cost"] or 0.0 for r in rows), 2),
            "by_project": sorted(({"name": k, "hours": round(h, 2), "cost": round(c, 2)}
                                  for k, (h, c) in by_project.items()), key=lambda x: -x["hours"])}


@router.post("/time-entries", status_code=201)
def create_time(body: TimeIn, me: User = Depends(hr_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _emp_or_404(db, body.employee_id)
    wo = db.get(WorkOrder, body.work_order_id) if body.work_order_id is not None else None
    if body.work_order_id is not None and wo is None:
        raise HTTPException(404, "İş emri bulunamadı")
    project_id = body.project_id if body.project_id is not None else (wo.project_id if wo else None)
    if project_id is not None:
        project_or_404(db, project_id)
    t = TimeEntry(employee_id=e.id, work_date=body.work_date or date.today(), hours=body.hours,
                  project_id=project_id, work_order_id=wo.id if wo else None, hourly_cost=e.hourly_cost,
                  note=body.note, created_by=me.username)
    db.add(t)
    db.flush()
    audit.record(db, me, "time_entry", t.id, "hours", None, t.hours, project_id, action="create")
    db.commit()
    p = db.get(Project, project_id) if project_id else None
    return _time_out(t, e.name, p.name if p else None, wo.no if wo else None)


@router.delete("/time-entries/{entry_id}")
def delete_time(entry_id: int, me: User = Depends(hr_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    t = db.get(TimeEntry, entry_id)
    if t is None:
        raise HTTPException(404, "Kayıt bulunamadı")
    audit.record(db, me, "time_entry", t.id, "hours", t.hours, None, t.project_id, action="delete")
    db.delete(t)
    db.commit()
    return {"ok": True}
