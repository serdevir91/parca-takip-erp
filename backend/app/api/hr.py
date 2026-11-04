"""Personel ve zaman: employee cards and time entries (work hours per project / work order).
Hours with a known hourly cost show up in the project cost as "İşçilik"."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..core.attendance import default_break, is_forgotten, worked_hours
from ..models import Attendance, Employee, LeaveRequest, Project, TimeEntry, User, WorkOrder
from ..permissions import require
from ..services import audit
from ..services.erp import WO_OPEN
from ..services.system import system
from .deps import any_user, get_db, project_or_404

hr_view, hr_edit = require("hr", "view"), require("hr", "edit")

SELF_EDIT_DAYS = 7     # a worker fixes own hours this far back; older ones are for a manager

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
    annual_leave_days: float | None = Field(default=None, ge=0, le=60)


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
    annual_leave_days: float | None = Field(default=None, ge=0, le=60)


class TimeIn(BaseModel):
    employee_id: int
    work_date: date | None = None
    hours: float = Field(gt=0, le=24)
    project_id: int | None = None
    work_order_id: int | None = None
    note: str = Field(default="", max_length=300)


class TimeEdit(BaseModel):
    work_date: date
    hours: float = Field(gt=0, le=24)
    project_id: int | None = None
    work_order_id: int | None = None
    note: str = Field(default="", max_length=300)


def _emp_out(e: Employee, hours_30d: float = 0.0) -> dict[str, Any]:
    return {"id": e.id, "name": e.name, "title": e.title, "department": e.department, "phone": e.phone,
            "email": e.email, "hourly_cost": e.hourly_cost,
            "start_date": e.start_date.isoformat() if e.start_date else None, "active": e.active, "note": e.note,
            "user_id": e.user_id, "annual_leave_days": e.annual_leave_days, "hours_30d": round(hours_30d, 2)}


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
    """The card an admin linked to this login. Never matched by e-mail: users set their own e-mail freely."""
    return db.scalar(select(Employee).where(Employee.user_id == me.id))


def _lock_card(db: Session, emp_id: int) -> Employee:
    """Hold the card's row lock until commit, so everything one employee's rules read (leave balance, overlapping
    shifts, the hours of a day) queues up instead of two writers passing the same check."""
    db.execute(update(Employee).where(Employee.id == emp_id).values(name=Employee.name))
    e = db.get(Employee, emp_id, populate_existing=True)
    if e is None:
        raise HTTPException(404, "Personel bulunamadı")
    return e


def _active_card(db: Session, me: User) -> Employee:
    """The caller's own card for a self-service write, locked."""
    e = _my_card(db, me)
    if e is None:
        raise HTTPException(400, "Hesabınıza bağlı personel kartı yok; yöneticinize başvurun")
    if not e.active:
        raise HTTPException(403, "Personel kartınız pasif")
    return _lock_card(db, e.id)


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


def _attended(db: Session, emp_id: int, day: date) -> tuple[float | None, bool, bool]:
    """Net hours of the shifts begun on `day`: (None without a shift, open now, forgotten clock-out). A shift
    still open counts up to this moment, so hours can be split before clocking out."""
    shifts = list(db.scalars(select(Attendance).where(Attendance.employee_id == emp_id, Attendance.work_date == day)))
    if not shifts:
        return None, False, False
    now = datetime.now().replace(microsecond=0)
    standard = int(system(db)["production"]["break_minutes"])
    total, running, forgot = 0.0, False, False
    for a in shifts:
        if a.clock_out is not None:
            total += worked_hours(a.clock_in, a.clock_out, a.break_minutes)
        elif is_forgotten(a.clock_in, None, now):
            forgot = True
        else:
            running = True
            total += worked_hours(a.clock_in, now, default_break(a.clock_in, now, standard))
    return round(total, 2), running, forgot


def _day_hours(db: Session, emp_id: int, day: date, own_id: int = 0) -> float:
    q = select(TimeEntry.hours).where(TimeEntry.employee_id == emp_id, TimeEntry.work_date == day,
                                      TimeEntry.id != own_id)
    return round(sum(db.scalars(q)), 2)


def _check_day(db: Session, emp_id: int, day: date, hours: float, own_id: int = 0) -> None:
    total = round(_day_hours(db, emp_id, day, own_id) + hours, 2)
    attended, _, forgot = _attended(db, emp_id, day)
    if attended is None:
        if total > 24:
            raise HTTPException(400, f"Bir güne en çok 24 saat yazılabilir; toplam {total:g} saat oluyor")
    elif total > attended:
        hint = " Çıkışınız unutulmuş; önce mesai düzeltme talebi açın." if forgot else ""
        raise HTTPException(400, f"Bu günkü net mesainiz {attended:g} saat; toplam {total:g} saat yazılamaz.{hint}")


def _check_recent(day: date) -> None:
    if day > date.today():
        raise HTTPException(400, "İleri tarihe saat yazılamaz")
    if day < date.today() - timedelta(days=SELF_EDIT_DAYS):
        raise HTTPException(403, f"{SELF_EDIT_DAYS} günden eski saatleri yalnızca yönetici değiştirir")


def _my_target(db: Session, body: TimeEdit, entry: TimeEntry | None = None) -> tuple[int | None, int | None]:
    """(project_id, work_order_id) for a worker's entry. Only what the pick list offers, except what the entry
    already holds: an order closed since then must not block fixing the hours."""
    if body.work_order_id is None and body.project_id is None:
        raise HTTPException(400, "İş emri veya proje seçin")
    project_id = body.project_id
    if body.work_order_id is not None:
        wo = db.get(WorkOrder, body.work_order_id)
        if wo is None:
            raise HTTPException(404, "İş emri bulunamadı")
        if wo.status not in WO_OPEN and not (entry and entry.work_order_id == wo.id):
            raise HTTPException(400, f"{wo.no} açık bir iş emri değil")
        if wo.project_id is not None:
            if project_id not in (None, wo.project_id):
                raise HTTPException(400, f"{wo.no} seçilen projeye ait değil")
            project_id = wo.project_id
    if project_id is not None:
        p = db.get(Project, project_id)
        if p is None:
            raise HTTPException(404, "Proje bulunamadı")
        if p.archived and not (entry and entry.project_id == p.id):
            raise HTTPException(400, f"{p.name} arşivde")
    return project_id, body.work_order_id


def _my_time_out(t: TimeEntry, project: str | None, wo: str | None) -> dict[str, Any]:
    """A worker's view of an entry: no wage in it."""
    return {"id": t.id, "work_date": t.work_date.isoformat(), "hours": t.hours, "project_id": t.project_id,
            "project_name": project, "work_order_id": t.work_order_id, "work_order_no": wo, "note": t.note,
            "created_by": t.created_by}


def _my_entry(db: Session, e: Employee, entry_id: int) -> TimeEntry:
    t = db.get(TimeEntry, entry_id, populate_existing=True)
    if t is None or t.employee_id != e.id:
        raise HTTPException(404, "Kayıt bulunamadı")
    _check_recent(t.work_date)
    return t


def _names(db: Session, t: TimeEntry) -> tuple[str | None, str | None]:
    p = db.get(Project, t.project_id) if t.project_id else None
    w = db.get(WorkOrder, t.work_order_id) if t.work_order_id else None
    return p.name if p else None, w.no if w else None


@router.get("/hr/me/time/options")
def my_time_options(_: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """The pick list for own hours; workers have no rights on projects or work orders, so nothing else is here."""
    live = select(Project.id).where(Project.archived.is_(False))
    q = (select(WorkOrder.id, WorkOrder.no, WorkOrder.description)
         .where(WorkOrder.status.in_(WO_OPEN), WorkOrder.project_id.is_(None) | WorkOrder.project_id.in_(live))
         .order_by(WorkOrder.no))
    return {"work_orders": [{"id": i, "no": no, "description": d} for i, no, d in db.execute(q)],
            "projects": [{"id": i, "name": n} for i, n in db.execute(
                select(Project.id, Project.name).where(Project.archived.is_(False)).order_by(Project.name))]}


@router.get("/hr/me/time")
def my_time(day: date | None = None, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """One day of the caller's own card: attended hours, hours given to jobs, and what is left to give."""
    day = day or date.today()
    e = _my_card(db, me)
    if e is None:
        return {"employee": None, "day": day.isoformat(), "rows": []}
    entries = db.scalars(select(TimeEntry).where(TimeEntry.employee_id == e.id, TimeEntry.work_date == day)
                         .order_by(TimeEntry.id))
    rows = [_my_time_out(t, *_names(db, t)) for t in entries]
    attended, running, forgot = _attended(db, e.id, day)
    allocated = round(sum(r["hours"] for r in rows), 2)
    limit = 24.0 if attended is None else attended
    return {"employee": {"id": e.id, "name": e.name}, "day": day.isoformat(), "attended": attended, "open": running,
            "forgot": forgot, "allocated": allocated, "remaining": round(max(limit - allocated, 0.0), 2),
            "editable": date.today() - timedelta(days=SELF_EDIT_DAYS) <= day <= date.today() and e.active,
            "edit_days": SELF_EDIT_DAYS, "rows": rows}


@router.post("/hr/me/time", status_code=201)
def add_my_time(body: TimeEdit, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _active_card(db, me)
    _check_recent(body.work_date)
    project_id, wo_id = _my_target(db, body)
    _check_day(db, e.id, body.work_date, body.hours)
    t = TimeEntry(employee_id=e.id, work_date=body.work_date, hours=body.hours, project_id=project_id,
                  work_order_id=wo_id, hourly_cost=e.hourly_cost, note=body.note, created_by=me.username)
    db.add(t)
    db.flush()
    audit.record(db, me, "time_entry", t.id, "hours", None, t.hours, project_id, action="create")
    db.commit()
    return _my_time_out(t, *_names(db, t))


@router.put("/hr/me/time/{entry_id}")
def edit_my_time(entry_id: int, body: TimeEdit, me: User = Depends(any_user),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    """The wage stays as it was snapshotted: a correction must not rewrite the cost history."""
    e = _active_card(db, me)
    t = _my_entry(db, e, entry_id)
    _check_recent(body.work_date)
    project_id, wo_id = _my_target(db, body, t)
    _check_day(db, e.id, body.work_date, body.hours, t.id)
    audit.record_changes(db, me, t, {"work_date": body.work_date, "hours": body.hours, "project_id": project_id,
                                     "work_order_id": wo_id, "note": body.note}, "time_entry", t.id, project_id)
    db.commit()
    return _my_time_out(t, *_names(db, t))


@router.delete("/hr/me/time/{entry_id}")
def delete_my_time(entry_id: int, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _active_card(db, me)
    t = _my_entry(db, e, entry_id)
    audit.record(db, me, "time_entry", t.id, "hours", t.hours, None, t.project_id, action="delete")
    db.delete(t)
    db.commit()
    return {"ok": True}


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
               if getattr(body, k) is not None or k in ("hourly_cost", "start_date", "user_id", "annual_leave_days")}
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
    if db.scalar(select(Attendance.id).where(Attendance.employee_id == e.id).limit(1)):
        raise HTTPException(400, "Mesai kaydı olan personel silinemez; pasif yapın")
    if db.scalar(select(LeaveRequest.id).where(LeaveRequest.employee_id == e.id).limit(1)):
        raise HTTPException(400, "İzin kaydı olan personel silinemez; pasif yapın")
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


def _target(db: Session, body: TimeIn | TimeEdit) -> tuple[int | None, WorkOrder | None]:
    wo = db.get(WorkOrder, body.work_order_id) if body.work_order_id is not None else None
    if body.work_order_id is not None and wo is None:
        raise HTTPException(404, "İş emri bulunamadı")
    project_id = body.project_id if body.project_id is not None else (wo.project_id if wo else None)
    if project_id is not None:
        project_or_404(db, project_id)
    return project_id, wo


@router.post("/time-entries", status_code=201)
def create_time(body: TimeIn, me: User = Depends(hr_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _emp_or_404(db, body.employee_id)
    project_id, wo = _target(db, body)
    t = TimeEntry(employee_id=e.id, work_date=body.work_date or date.today(), hours=body.hours,
                  project_id=project_id, work_order_id=wo.id if wo else None, hourly_cost=e.hourly_cost,
                  note=body.note, created_by=me.username)
    db.add(t)
    db.flush()
    audit.record(db, me, "time_entry", t.id, "hours", None, t.hours, project_id, action="create")
    db.commit()
    p = db.get(Project, project_id) if project_id else None
    return _time_out(t, e.name, p.name if p else None, wo.no if wo else None)


@router.put("/time-entries/{entry_id}")
def edit_time(entry_id: int, body: TimeEdit, me: User = Depends(hr_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    """A manager's correction of any entry; the wage snapshot stays."""
    t = db.get(TimeEntry, entry_id)
    if t is None:
        raise HTTPException(404, "Kayıt bulunamadı")
    project_id, wo = _target(db, body)
    audit.record_changes(db, me, t, {"work_date": body.work_date, "hours": body.hours, "project_id": project_id,
                                     "work_order_id": wo.id if wo else None, "note": body.note},
                         "time_entry", t.id, project_id)
    db.commit()
    p = db.get(Project, project_id) if project_id else None
    return _time_out(t, _emp_or_404(db, t.employee_id).name, p.name if p else None, wo.no if wo else None)


@router.delete("/time-entries/{entry_id}")
def delete_time(entry_id: int, me: User = Depends(hr_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    t = db.get(TimeEntry, entry_id)
    if t is None:
        raise HTTPException(404, "Kayıt bulunamadı")
    audit.record(db, me, "time_entry", t.id, "hours", t.hours, None, t.project_id, action="delete")
    db.delete(t)
    db.commit()
    return {"ok": True}
