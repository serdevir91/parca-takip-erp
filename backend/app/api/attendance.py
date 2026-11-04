"""Mesai takibi: shifts with clock-in and clock-out. An employee sees and stamps only their own shifts, with the
server's clock; the attendance module sees everyone and corrects the records."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.attendance import (MAX_SHIFT_HOURS, day_balance, default_break, is_forgotten, week_start,
                               weekly_overtime, worked_hours)
from ..models import Attendance, AttendanceRequest, Employee, User, utcnow
from ..permissions import require
from ..services import audit
from ..services.system import system
from .deps import any_user, get_db
from .hr import _active_card, _lock_card, _my_card
from .leave import KINDS, STATUS, DecideIn, attendance_on, leave_map, pending_count

att_view, att_edit = require("attendance", "view"), require("attendance", "edit")

router = APIRouter(tags=["attendance"])


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=300)


class ShiftIn(BaseModel):
    work_date: date
    start: time
    end: time | None = None
    break_minutes: int | None = Field(default=None, ge=0, le=600)
    note: str = Field(default="", max_length=300)


class ShiftNew(ShiftIn):
    employee_id: int


class FixIn(BaseModel):
    """A worker's correction request. attendance_id names the shift to change; without it a new shift is asked for."""
    attendance_id: int | None = None
    work_date: date
    clock_in: time
    clock_out: time | None = None
    reason: str = Field(default="", max_length=300)


def _rules(db: Session) -> tuple[float, int]:
    p = system(db)["production"]
    return float(p["week_hours"]), int(p["break_minutes"])


def _work_hours(db: Session) -> float:
    return float(system(db)["production"]["work_hours"])


def _rows(shifts: list[Attendance], names: dict[int, str], first: date, last: date,
          week_hours: float) -> list[dict[str, Any]]:
    """Output rows of one period, newest first. `shifts` start on the Monday of `first`, so overtime is right."""
    now = datetime.now()
    per_emp: dict[int, list[tuple[int, date, float]]] = defaultdict(list)
    for a in sorted(shifts, key=lambda s: s.clock_in):
        per_emp[a.employee_id].append((a.id, a.work_date, worked_hours(a.clock_in, a.clock_out, a.break_minutes)))
    overtime: dict[int, float] = {}
    for items in per_emp.values():
        overtime.update(weekly_overtime(items, week_hours))
    out = []
    for a in sorted(shifts, key=lambda s: s.clock_in, reverse=True):
        if not first <= a.work_date <= last:
            continue
        status = "done" if a.clock_out else "forgot" if is_forgotten(a.clock_in, a.clock_out, now) else "open"
        out.append({"id": a.id, "employee_id": a.employee_id, "employee_name": names.get(a.employee_id, ""),
                    "work_date": a.work_date.isoformat(), "start": a.clock_in.strftime("%H:%M"),
                    "end": a.clock_out.strftime("%H:%M") if a.clock_out else None,
                    "clock_in": a.clock_in.isoformat(timespec="seconds"),
                    "next_day": bool(a.clock_out and a.clock_out.date() != a.clock_in.date()),
                    "break_minutes": a.break_minutes,
                    "hours": worked_hours(a.clock_in, a.clock_out, a.break_minutes),
                    "overtime": overtime.get(a.id, 0.0), "status": status, "note": a.note,
                    "corrected_by": a.updated_by})
    return out


def _load(db: Session, first: date, last: date, employee_id: int | None = None) -> list[Attendance]:
    q = select(Attendance).where(Attendance.work_date >= week_start(first), Attendance.work_date <= last)
    if employee_id is not None:
        q = q.where(Attendance.employee_id == employee_id)
    return list(db.scalars(q))


def _month(month: str | None) -> tuple[date, date]:
    try:
        first = datetime.strptime(month, "%Y-%m").date() if month else date.today().replace(day=1)
    except ValueError:
        raise HTTPException(400, "Ay YYYY-AA biçiminde olmalı") from None
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def _sum(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"hours": round(sum(r["hours"] for r in rows), 2), "overtime": round(sum(r["overtime"] for r in rows), 2),
            "days": len({r["work_date"] for r in rows if r["status"] == "done"}),
            "forgot": sum(r["status"] == "forgot" for r in rows)}


def _balance(rows: list[dict[str, Any]], e: Employee, first: date, last: date, work_hours: float,
             leaves: dict[date, str]) -> dict[str, Any]:
    """Expected hours against shifts and approved leave. `rows` are this person's output rows of the period."""
    worked: dict[date, float] = defaultdict(float)
    for r in rows:
        worked[date.fromisoformat(r["work_date"])] += r["hours"]
    return day_balance(first, last, date.today(), work_hours, dict(worked), leaves, e.start_date, e.active)


def _leave_rows(leaves: dict[date, str], e: Employee) -> list[dict[str, Any]]:
    return [{"employee_id": e.id, "employee_name": e.name, "work_date": d.isoformat(), "kind": k,
             "label": KINDS.get(k, k)} for d, k in sorted(leaves.items(), reverse=True)]


def _open_shift(db: Session, employee_id: int) -> Attendance | None:
    """The shift this person is in now; older open ones are forgotten clock-outs for a manager to correct."""
    since = datetime.now() - timedelta(hours=MAX_SHIFT_HOURS)
    return db.scalar(select(Attendance).where(Attendance.employee_id == employee_id, Attendance.clock_out.is_(None),
                                              Attendance.clock_in >= since).order_by(Attendance.clock_in.desc()))


def _self(db: Session, me: User) -> Employee:
    attendance_on()
    return _active_card(db, me)             # locked: two quick taps must not open two shifts


@router.get("/attendance/me")
def my_shifts(month: str | None = None, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    attendance_on()
    e = _my_card(db, me)
    if e is None:
        return {"employee": None, "open": None, "rows": [], "leave_days": [], "summary": _sum([])}
    first, last = _month(month)
    week_hours, _ = _rules(db)
    rows = _rows(_load(db, first, last, e.id), {e.id: e.name}, first, last, week_hours)
    shift = _open_shift(db, e.id)
    leaves = leave_map(db, first, last, e.id)[e.id]
    summary = {**_sum(rows), **_balance(rows, e, first, last, _work_hours(db), leaves)}
    return {"employee": {"id": e.id, "name": e.name}, "rows": rows, "leave_days": _leave_rows(leaves, e),
            "summary": summary, "week_hours": week_hours,
            "open": {"id": shift.id, "clock_in": shift.clock_in.isoformat(timespec="seconds")} if shift else None}


@router.post("/attendance/clock-in", status_code=201)
def clock_in(body: NoteIn, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _self(db, me)
    if _open_shift(db, e.id):
        raise HTTPException(409, "Zaten açık bir mesainiz var")
    now = datetime.now().replace(microsecond=0)
    a = Attendance(employee_id=e.id, work_date=now.date(), clock_in=now, note=body.note, created_by=me.username)
    db.add(a)
    db.flush()
    audit.record(db, me, "attendance", a.id, "clock_in", None, now.isoformat(), action="create")
    db.commit()
    return {"id": a.id, "clock_in": now.isoformat()}


@router.post("/attendance/clock-out")
def clock_out(body: NoteIn, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _self(db, me)
    a = _open_shift(db, e.id)
    if a is None:
        raise HTTPException(409, "Açık mesainiz yok")
    now = datetime.now().replace(microsecond=0)
    a.clock_out = now
    a.break_minutes = default_break(a.clock_in, now, _rules(db)[1])
    if body.note:
        a.note = body.note
    audit.record(db, me, "attendance", a.id, "clock_out", None, now.isoformat())
    db.commit()
    return {"id": a.id, "hours": worked_hours(a.clock_in, now, a.break_minutes), "break_minutes": a.break_minutes}


@router.get("/attendance")
def list_shifts(date_from: date | None = None, date_to: date | None = None, employee_id: int | None = None,
                _: User = Depends(att_view), db: Session = Depends(get_db)) -> dict[str, Any]:
    first, last = _month(None)
    first, last = date_from or first, date_to or last
    if first > last:
        raise HTTPException(400, "Başlangıç tarihi bitişten sonra olamaz")
    people = list(db.scalars(select(Employee).order_by(Employee.name)))
    names = {e.id: e.name for e in people}
    shifts = _load(db, first, last, employee_id)
    rows = _rows(shifts, names, first, last, _rules(db)[0])
    by_emp: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_emp[r["employee_id"]].append(r)
    since = datetime.now() - timedelta(hours=MAX_SHIFT_HOURS)
    inside = set(db.scalars(select(Attendance.employee_id).where(Attendance.clock_out.is_(None),
                                                                 Attendance.clock_in >= since)))
    leaves = leave_map(db, first, last, employee_id)
    work_hours = _work_hours(db)
    # Active people with no shift stay in the list: who did not come is part of the answer
    summary = [{"employee_id": e.id, "name": e.name, "department": e.department, "inside": e.id in inside,
                **_sum(by_emp[e.id]), **_balance(by_emp[e.id], e, first, last, work_hours, leaves[e.id])}
               for e in people if (e.active or by_emp[e.id] or leaves[e.id]) and employee_id in (None, e.id)]
    total = {**_sum(rows), **{k: round(sum(p[k] for p in summary), 2)
                              for k in ("expected", "covered", "missing_days", "short")}}
    return {"rows": rows, "people": summary, "total": total, "inside": len(inside),
            "leave_days": [x for e in people for x in _leave_rows(leaves[e.id], e)],
            "date_from": first.isoformat(), "date_to": last.isoformat()}


def _times(body: ShiftIn) -> tuple[datetime, datetime | None]:
    start = datetime.combine(body.work_date, body.start.replace(second=0, microsecond=0, tzinfo=None))
    if body.work_date > date.today():
        raise HTTPException(400, "İleri tarihli mesai girilemez")
    if body.end is None:
        return start, None
    end = datetime.combine(body.work_date, body.end.replace(second=0, microsecond=0, tzinfo=None))
    if end == start:
        raise HTTPException(400, "Giriş ve çıkış saati aynı olamaz")
    if end < start:                                     # night shift: ends on the next day
        end += timedelta(days=1)
    if end - start > timedelta(hours=MAX_SHIFT_HOURS):
        raise HTTPException(400, f"Bir mesai {MAX_SHIFT_HOURS} saatten uzun olamaz")
    return start, end


def _check_overlap(db: Session, employee_id: int, start: datetime, end: datetime | None, own_id: int = 0) -> None:
    stop = end or start + timedelta(minutes=1)
    near = db.scalars(select(Attendance).where(Attendance.employee_id == employee_id, Attendance.id != own_id,
                                               Attendance.clock_in < stop,
                                               Attendance.clock_in >= start - timedelta(days=2)))
    for a in near:
        other_end = a.clock_out or a.clock_in + timedelta(minutes=1)
        if a.clock_in < stop and start < other_end:
            raise HTTPException(409, f"{a.clock_in:%d.%m.%Y %H:%M} mesaisi ile çakışıyor")


def _pick_break(body: ShiftIn, start: datetime, end: datetime | None, standard: int) -> int:
    if end is None:
        return 0
    minutes = body.break_minutes if body.break_minutes is not None else default_break(start, end, standard)
    if minutes * 60 >= (end - start).total_seconds():
        raise HTTPException(400, "Mola mesaiden uzun olamaz")
    return minutes


def _text(a: Attendance) -> str:
    return f"{a.clock_in:%d.%m.%Y %H:%M} - {a.clock_out:%H:%M}" if a.clock_out else f"{a.clock_in:%d.%m.%Y %H:%M} -"


def _save_shift(db: Session, me: User, employee_id: int, body: ShiftIn, a: Attendance | None = None) -> Attendance:
    """The one way a manager's decision reaches a shift, so an approved request passes the same rules as an edit."""
    e = _lock_card(db, employee_id)
    if a is not None:
        db.refresh(a)
    start, end = _times(body)
    _check_overlap(db, e.id, start, end, a.id if a else 0)
    minutes = _pick_break(body, start, end, _rules(db)[1])
    old = _text(a) if a else None
    fresh = a is None
    if a is None:
        a = Attendance(employee_id=e.id, created_by=me.username)
        db.add(a)
    a.work_date, a.clock_in, a.clock_out, a.break_minutes = body.work_date, start, end, minutes
    a.note, a.updated_by = body.note, me.username
    db.flush()
    audit.record(db, me, "attendance", a.id, "mesai", old, f"{e.name}: {_text(a)}" if fresh else _text(a),
                 action="create" if fresh else "update")
    return a


@router.post("/attendance", status_code=201)
def add_shift(body: ShiftNew, me: User = Depends(att_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    a = _save_shift(db, me, body.employee_id, body)
    db.commit()
    return {"id": a.id}


@router.put("/attendance/{shift_id}")
def edit_shift(shift_id: int, body: ShiftIn, me: User = Depends(att_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    a = db.get(Attendance, shift_id)
    if a is None:
        raise HTTPException(404, "Mesai bulunamadı")
    _save_shift(db, me, a.employee_id, body, a)
    db.commit()
    return {"id": a.id}


@router.delete("/attendance/{shift_id}")
def delete_shift(shift_id: int, me: User = Depends(att_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    a = db.get(Attendance, shift_id)
    if a is None:
        raise HTTPException(404, "Mesai bulunamadı")
    _lock_card(db, a.employee_id)
    # Left open, a request about this shift would lose its link and bring the shift back as a new one when approved
    waiting = db.scalars(select(AttendanceRequest).where(AttendanceRequest.attendance_id == a.id,
                                                         AttendanceRequest.status == "pending"))
    for r in waiting:
        r.status, r.decided_by, r.decided_at, r.decision_note = "rejected", me.username, utcnow(), "Mesai silindi"
        audit.record(db, me, "attendance_request", r.id, "status", "pending", r.status)
    audit.record(db, me, "attendance", a.id, "mesai", _text(a), None, action="delete")
    db.delete(a)
    db.commit()
    return {"ok": True}


def _fix_body(work_date: date, clock_in: time, clock_out: time | None, a: Attendance | None, note: str) -> ShiftIn:
    """A request with no clock-out keeps the shift's own one: asking about the clock-in must not reopen the shift."""
    if clock_out is None and a is not None and a.clock_out is not None:
        clock_out = a.clock_out.time()
    minutes = a.break_minutes if a is not None and a.clock_out is not None else None
    return ShiftIn(work_date=work_date, start=clock_in, end=clock_out, break_minutes=minutes, note=note)


def _fix_out(r: AttendanceRequest, name: str, a: Attendance | None) -> dict[str, Any]:
    return {"id": r.id, "employee_id": r.employee_id, "employee_name": name, "attendance_id": r.attendance_id,
            "work_date": r.work_date.isoformat(), "start": r.clock_in.strftime("%H:%M"),
            "end": r.clock_out.strftime("%H:%M") if r.clock_out else None,
            "next_day": bool(r.clock_out and r.clock_out.date() != r.clock_in.date()),
            "current": _text(a) if a else None, "reason": r.reason, "status": r.status,
            "status_label": STATUS.get(r.status, r.status), "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None, "decided_by": r.decided_by,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None, "decision_note": r.decision_note}


def _fix_rows(db: Session, q: Any, names: dict[int, str]) -> list[dict[str, Any]]:
    reqs = list(db.scalars(q.order_by(AttendanceRequest.created_at.desc(), AttendanceRequest.id.desc()).limit(1000)))
    ids = {r.attendance_id for r in reqs if r.attendance_id}
    shifts = {a.id: a for a in db.scalars(select(Attendance).where(Attendance.id.in_(ids)))} if ids else {}
    return [_fix_out(r, names.get(r.employee_id, ""), shifts.get(r.attendance_id or 0)) for r in reqs]


def _fix_pending(db: Session) -> int:
    q = select(func.count()).select_from(AttendanceRequest).where(AttendanceRequest.status == "pending")
    return db.scalar(q) or 0


@router.get("/attendance/queue")
def queue(_: User = Depends(att_view), db: Session = Depends(get_db)) -> dict[str, int]:
    """Counts of what waits for a manager's decision."""
    return {"leave": pending_count(db), "shifts": _fix_pending(db)}


@router.get("/attendance/requests/me")
def my_fixes(me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    attendance_on()
    e = _my_card(db, me)
    if e is None:
        return {"employee": None, "rows": []}
    q = select(AttendanceRequest).where(AttendanceRequest.employee_id == e.id)
    return {"employee": {"id": e.id, "name": e.name}, "rows": _fix_rows(db, q, {e.id: e.name})}


@router.post("/attendance/requests", status_code=201)
def ask_fix(body: FixIn, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _self(db, me)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, "Gerekçe yazın")
    a = None
    if body.attendance_id is not None:
        a = db.get(Attendance, body.attendance_id)
        if a is None or a.employee_id != e.id:
            raise HTTPException(404, "Mesai bulunamadı")
    elif body.clock_out is None:
        raise HTTPException(400, "Eksik mesai için çıkış saatini de yazın")
    shift = _fix_body(body.work_date, body.clock_in, body.clock_out, a, reason)
    start, end = _times(shift)
    _check_overlap(db, e.id, start, end, a.id if a else 0)
    _pick_break(shift, start, end, _rules(db)[1])
    r = AttendanceRequest(employee_id=e.id, attendance_id=a.id if a else None, work_date=body.work_date, clock_in=start,
                          clock_out=end, reason=reason, created_by=me.username)
    db.add(r)
    db.flush()
    audit.record(db, me, "attendance_request", r.id, "talep", _text(a) if a else None,
                 f"{e.name}: {start:%d.%m.%Y %H:%M} - {end:%H:%M}" if end else f"{e.name}: {start:%d.%m.%Y %H:%M} -",
                 action="create")
    db.commit()
    return _fix_out(r, e.name, a)


@router.post("/attendance/requests/{request_id}/cancel")
def cancel_fix(request_id: int, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _self(db, me)
    r = db.get(AttendanceRequest, request_id, populate_existing=True)
    if r is None or r.employee_id != e.id:
        raise HTTPException(404, "Talep bulunamadı")
    if r.status != "pending":
        raise HTTPException(409, "Yalnızca bekleyen talep iptal edilebilir")
    r.status = "cancelled"
    audit.record(db, me, "attendance_request", r.id, "status", "pending", r.status)
    db.commit()
    return _fix_out(r, e.name, db.get(Attendance, r.attendance_id) if r.attendance_id else None)


@router.get("/attendance/requests")
def list_fixes(status: str | None = None, employee_id: int | None = None, _: User = Depends(att_view),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    q = select(AttendanceRequest)
    if status:
        q = q.where(AttendanceRequest.status == status)
    if employee_id is not None:
        q = q.where(AttendanceRequest.employee_id == employee_id)
    names = dict(db.execute(select(Employee.id, Employee.name)).all())
    return {"rows": _fix_rows(db, q, names), "pending": _fix_pending(db)}


@router.post("/attendance/requests/{request_id}/decide")
def decide_fix(request_id: int, body: DecideIn, me: User = Depends(att_edit),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    """The rules are checked again here: the shifts may have changed since the worker asked."""
    emp_id = db.scalar(select(AttendanceRequest.employee_id).where(AttendanceRequest.id == request_id))
    if emp_id is None:
        raise HTTPException(404, "Talep bulunamadı")
    e = _lock_card(db, emp_id)
    r = db.get(AttendanceRequest, request_id, populate_existing=True)   # read after the lock: two managers, one answer
    if r.status != "pending":
        raise HTTPException(409, "Bu talep zaten sonuçlanmış")
    a = None
    if body.approve:
        a = db.get(Attendance, r.attendance_id) if r.attendance_id else None
        shift = _fix_body(r.work_date, r.clock_in.time(), r.clock_out.time() if r.clock_out else None, a,
                          a.note if a else r.reason)
        a = _save_shift(db, me, r.employee_id, shift, a)
        r.attendance_id = a.id
    r.status = "approved" if body.approve else "rejected"
    r.decided_by, r.decided_at, r.decision_note = me.username, utcnow(), body.note
    audit.record(db, me, "attendance_request", r.id, "status", "pending", r.status)
    db.commit()
    return _fix_out(r, e.name, a)
