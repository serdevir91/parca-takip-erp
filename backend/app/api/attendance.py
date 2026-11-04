"""Mesai takibi: shifts with clock-in and clock-out. An employee sees and stamps only their own shifts, with the
server's clock; the attendance module sees everyone and corrects the records."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.attendance import (MAX_SHIFT_HOURS, default_break, is_forgotten, week_start, weekly_overtime,
                               worked_hours)
from ..models import Attendance, Employee, User
from ..permissions import require
from ..services import audit
from ..services.system import system
from .deps import any_user, get_db
from .hr import _emp_or_404, _my_card

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


def _rules(db: Session) -> tuple[float, int]:
    p = system(db)["production"]
    return float(p["week_hours"]), int(p["break_minutes"])


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


def _open_shift(db: Session, employee_id: int) -> Attendance | None:
    """The shift this person is in now; older open ones are forgotten clock-outs for a manager to correct."""
    since = datetime.now() - timedelta(hours=MAX_SHIFT_HOURS)
    return db.scalar(select(Attendance).where(Attendance.employee_id == employee_id, Attendance.clock_out.is_(None),
                                              Attendance.clock_in >= since).order_by(Attendance.clock_in.desc()))


def _enabled() -> None:
    if "attendance" in get_settings().disabled_modules:
        raise HTTPException(403, "Mesai takibi kapalı")


def _self(db: Session, me: User) -> Employee:
    _enabled()
    e = _my_card(db, me)
    if e is None:
        raise HTTPException(400, "Hesabınıza bağlı personel kartı yok; yöneticinize başvurun")
    if not e.active:
        raise HTTPException(403, "Personel kartınız pasif")
    return db.get(Employee, e.id, with_for_update=True)    # two quick taps must not open two shifts


@router.get("/attendance/me")
def my_shifts(month: str | None = None, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    _enabled()
    e = _my_card(db, me)
    if e is None:
        return {"employee": None, "open": None, "rows": [], "summary": _sum([])}
    first, last = _month(month)
    week_hours, _ = _rules(db)
    rows = _rows(_load(db, first, last, e.id), {e.id: e.name}, first, last, week_hours)
    shift = _open_shift(db, e.id)
    return {"employee": {"id": e.id, "name": e.name}, "rows": rows, "summary": _sum(rows), "week_hours": week_hours,
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
    # Active people with no shift stay in the list: who did not come is part of the answer
    summary = [{"employee_id": e.id, "name": e.name, "department": e.department, "inside": e.id in inside,
                **_sum(by_emp[e.id])}
               for e in people if (e.active or by_emp[e.id]) and employee_id in (None, e.id)]
    return {"rows": rows, "people": summary, "total": _sum(rows), "inside": len(inside),
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


@router.post("/attendance", status_code=201)
def add_shift(body: ShiftNew, me: User = Depends(att_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    e = _emp_or_404(db, body.employee_id)
    start, end = _times(body)
    _check_overlap(db, e.id, start, end)
    a = Attendance(employee_id=e.id, work_date=body.work_date, clock_in=start, clock_out=end, note=body.note,
                   break_minutes=_pick_break(body, start, end, _rules(db)[1]), created_by=me.username,
                   updated_by=me.username)
    db.add(a)
    db.flush()
    audit.record(db, me, "attendance", a.id, "mesai", None, f"{e.name}: {_text(a)}", action="create")
    db.commit()
    return {"id": a.id}


@router.put("/attendance/{shift_id}")
def edit_shift(shift_id: int, body: ShiftIn, me: User = Depends(att_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    a = db.get(Attendance, shift_id)
    if a is None:
        raise HTTPException(404, "Mesai bulunamadı")
    start, end = _times(body)
    _check_overlap(db, a.employee_id, start, end, a.id)
    old = _text(a)
    a.work_date, a.clock_in, a.clock_out = body.work_date, start, end
    a.break_minutes = _pick_break(body, start, end, _rules(db)[1])
    a.note, a.updated_by = body.note, me.username
    audit.record(db, me, "attendance", a.id, "mesai", old, _text(a))
    db.commit()
    return {"id": a.id}


@router.delete("/attendance/{shift_id}")
def delete_shift(shift_id: int, me: User = Depends(att_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    a = db.get(Attendance, shift_id)
    if a is None:
        raise HTTPException(404, "Mesai bulunamadı")
    audit.record(db, me, "attendance", a.id, "mesai", _text(a), None, action="delete")
    db.delete(a)
    db.commit()
    return {"ok": True}
