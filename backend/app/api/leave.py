"""İzin ve rapor: leave requests. A worker asks for and cancels their own; the attendance module sees everyone,
decides, enters leave directly and cancels approved leave. Only annual leave uses the balance. Approved days show
up in the shift report (api/attendance.py)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import numbers as num
from ..config import get_settings
from ..core.attendance import working_days
from ..services.holidays import off_days
from ..models import Employee, LeaveRequest, User, utcnow
from ..permissions import require
from ..services import audit
from ..services.system import system
from .deps import any_user, get_db
from .hr import _active_card, _lock_card, _my_card
from app.core.i18n import tx

att_view, att_edit = require("attendance", "view"), require("attendance", "edit")

router = APIRouter(tags=["leave"])

KINDS = {"annual": "Yıllık izin", "sick": "Rapor", "excuse": "Mazeret", "unpaid": "Ücretsiz izin"}
STATUS = {"pending": "Bekliyor", "approved": "Onaylandı", "rejected": "Reddedildi", "cancelled": "İptal"}
LIVE = ("pending", "approved")         # these hold their days: no overlap, and they count on the balance
MAX_SPAN_DAYS = 366
Kind = Literal["annual", "sick", "excuse", "unpaid"]


class LeaveIn(BaseModel):
    kind: Kind = "annual"
    start_date: date
    end_date: date
    note: str = Field(default="", max_length=300)


class LeaveEntry(LeaveIn):
    employee_id: int


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=300)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=300)


def attendance_on() -> None:
    if "attendance" in get_settings().disabled_modules:
        raise HTTPException(403, tx("Mesai takibi kapalı"))


def _year_days(r: LeaveRequest, year: int, off: dict[date, float]) -> float:
    """Working days of a request inside one year; leave across New Year counts on both years, each for its part.
    `off` are the public holidays of the year, which leave does not use up."""
    return working_days(max(r.start_date, date(year, 1, 1)), min(r.end_date, date(year, 12, 31)), off)


def _entitled(db: Session, e: Employee) -> float:
    if e.annual_leave_days is not None:         # 0 is a real entitlement, not "use the default"
        return e.annual_leave_days
    return float(system(db)["production"]["annual_leave_days"])


def balance(db: Session, e: Employee, year: int) -> dict[str, Any]:
    """`remaining` is what is still free to ask for, so waiting requests are taken out of it."""
    q = select(LeaveRequest).where(LeaveRequest.employee_id == e.id, LeaveRequest.kind == "annual",
                                   LeaveRequest.status.in_(LIVE), LeaveRequest.start_date <= date(year, 12, 31),
                                   LeaveRequest.end_date >= date(year, 1, 1))
    held = {"pending": 0.0, "approved": 0.0}
    off = off_days(db, date(year, 1, 1), date(year, 12, 31))
    for r in db.scalars(q):
        held[r.status] += _year_days(r, year, off)
    entitled = _entitled(db, e)
    return {"year": year, "entitled": entitled, "used": held["approved"], "pending": held["pending"],
            "remaining": entitled - held["approved"] - held["pending"]}


def _check_range(db: Session, e: Employee, body: LeaveIn) -> int:
    if body.end_date < body.start_date:
        raise HTTPException(400, tx("Bitiş tarihi başlangıçtan önce olamaz"))
    if (body.end_date - body.start_date).days > MAX_SPAN_DAYS:
        raise HTTPException(400, tx("Bir izin kaydı bir yıldan uzun olamaz; bölerek girin"))
    days = working_days(body.start_date, body.end_date, off_days(db, body.start_date, body.end_date))
    if days == 0:
        raise HTTPException(400, tx("Seçilen aralıkta iş günü yok"))
    clash = db.scalar(select(LeaveRequest).where(LeaveRequest.employee_id == e.id, LeaveRequest.status.in_(LIVE),
                                                 LeaveRequest.start_date <= body.end_date,
                                                 LeaveRequest.end_date >= body.start_date))
    if clash is not None:
        raise HTTPException(409, tx("{0} - {1} izni ile çakışıyor", f"{clash.start_date:%d.%m.%Y}", f"{clash.end_date:%d.%m.%Y}"))
    return days


def _check_balance(db: Session, e: Employee, r: LeaveRequest) -> None:
    """At approval only approved days count: what merely waits must not block the request being decided."""
    if r.kind != "annual":
        return
    for year in range(r.start_date.year, r.end_date.year + 1):
        b = balance(db, e, year)
        free = b["entitled"] - b["used"]
        need = _year_days(r, year, off_days(db, date(year, 1, 1), date(year, 12, 31)))
        if need > free:
            raise HTTPException(409, tx("{0} yıllık izin bakiyesi yetersiz: kalan {1} gün, istenen {2} gün", year, num.text(free), num.text(need)))


def _out(r: LeaveRequest, name: str = "") -> dict[str, Any]:
    return {"id": r.id, "employee_id": r.employee_id, "employee_name": name, "kind": r.kind,
            "kind_label": KINDS.get(r.kind, r.kind), "start_date": r.start_date.isoformat(),
            "end_date": r.end_date.isoformat(), "days": r.days, "status": r.status,
            "status_label": STATUS.get(r.status, r.status), "note": r.note, "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None, "decided_by": r.decided_by,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None, "decision_note": r.decision_note}


def _text(r: LeaveRequest, name: str) -> str:
    return f"{name}: {KINDS.get(r.kind, r.kind)} {r.start_date:%d.%m.%Y} - {r.end_date:%d.%m.%Y} ({num.text(r.days)} gün)"


def _new(db: Session, me: User, e: Employee, body: LeaveIn, status: str) -> LeaveRequest:
    r = LeaveRequest(employee_id=e.id, kind=body.kind, start_date=body.start_date, end_date=body.end_date,
                     days=_check_range(db, e, body), status=status, note=body.note, created_by=me.username)
    if status == "approved":
        _check_balance(db, e, r)
        r.decided_by, r.decided_at = me.username, utcnow()
    db.add(r)
    db.flush()
    audit.record(db, me, "leave", r.id, "izin", None, _text(r, e.name), action="create")
    return r


def _locked(db: Session, leave_id: int) -> tuple[Employee, LeaveRequest]:
    """The request as it stands once the card is locked: a decision made a moment ago is seen, not overwritten."""
    emp_id = db.scalar(select(LeaveRequest.employee_id).where(LeaveRequest.id == leave_id))
    if emp_id is None:
        raise HTTPException(404, tx("İzin kaydı bulunamadı"))
    e = _lock_card(db, emp_id)
    return e, db.get(LeaveRequest, leave_id, populate_existing=True)


def _close(db: Session, me: User, r: LeaveRequest, status: str, note: str | None = None) -> None:
    old, r.status = r.status, status
    r.decided_by, r.decided_at = me.username, utcnow()
    if note is not None:
        r.decision_note = note
    audit.record(db, me, "leave", r.id, "status", old, status)


def leave_map(db: Session, first: date, last: date, employee_id: int | None = None) -> dict[int, dict[date, str]]:
    """Approved leave by employee and working day inside the period."""
    q = select(LeaveRequest).where(LeaveRequest.status == "approved", LeaveRequest.start_date <= last,
                                   LeaveRequest.end_date >= first)
    if employee_id is not None:
        q = q.where(LeaveRequest.employee_id == employee_id)
    out: dict[int, dict[date, str]] = defaultdict(dict)
    off = off_days(db, first, last)
    for r in db.scalars(q):
        d, stop = max(r.start_date, first), min(r.end_date, last)
        while d <= stop:
            if d.weekday() < 5 and off.get(d, 0.0) < 1:
                out[r.employee_id][d] = r.kind
            d += timedelta(days=1)
    return out


def pending_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(LeaveRequest).where(LeaveRequest.status == "pending")) or 0


@router.get("/leave/me")
def my_leave(year: int | None = None, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    attendance_on()
    year = year or date.today().year
    if not 2000 <= year <= 2100:
        raise HTTPException(400, tx("Geçersiz yıl"))
    e = _my_card(db, me)
    if e is None:
        return {"employee": None, "balance": None, "rows": []}
    q = (select(LeaveRequest).where(LeaveRequest.employee_id == e.id)
         .order_by(LeaveRequest.start_date.desc(), LeaveRequest.id.desc()).limit(500))
    return {"employee": {"id": e.id, "name": e.name}, "balance": balance(db, e, year),
            "rows": [_out(r, e.name) for r in db.scalars(q)]}


@router.post("/leave/me", status_code=201)
def request_leave(body: LeaveIn, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    attendance_on()
    e = _active_card(db, me)
    r = _new(db, me, e, body, "pending")
    db.commit()
    return _out(r, e.name)


@router.post("/leave/me/{leave_id}/cancel")
def cancel_my_leave(leave_id: int, me: User = Depends(any_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    attendance_on()
    e = _active_card(db, me)
    r = db.get(LeaveRequest, leave_id, populate_existing=True)
    if r is None or r.employee_id != e.id:
        raise HTTPException(404, tx("İzin kaydı bulunamadı"))
    if r.status != "pending":
        raise HTTPException(409, tx("Yalnızca bekleyen talep iptal edilebilir"))
    old, r.status = r.status, "cancelled"
    audit.record(db, me, "leave", r.id, "status", old, r.status)
    db.commit()
    return _out(r, e.name)


@router.get("/leave")
def list_leave(status: str | None = None, kind: str | None = None, employee_id: int | None = None,
               date_from: date | None = None, date_to: date | None = None, _: User = Depends(att_view),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    q = select(LeaveRequest, Employee).join(Employee).order_by(LeaveRequest.start_date.desc(), LeaveRequest.id.desc())
    if status:
        q = q.where(LeaveRequest.status == status)
    if kind:
        q = q.where(LeaveRequest.kind == kind)
    if employee_id is not None:
        q = q.where(LeaveRequest.employee_id == employee_id)
    if date_from:
        q = q.where(LeaveRequest.end_date >= date_from)
    if date_to:
        q = q.where(LeaveRequest.start_date <= date_to)
    rows = []
    for r, e in db.execute(q.limit(2000)):
        row = _out(r, e.name)
        if r.status == "pending" and r.kind == "annual":       # the manager decides with the balance in sight
            b = balance(db, e, r.start_date.year)
            row["free_days"] = b["entitled"] - b["used"]
        rows.append(row)
    return {"rows": rows, "pending": pending_count(db)}


@router.post("/leave", status_code=201)
def enter_leave(body: LeaveEntry, me: User = Depends(att_edit), db: Session = Depends(get_db)) -> dict[str, Any]:
    """A leave a manager writes down directly, approved at once under the same rules."""
    e = _lock_card(db, body.employee_id)
    r = _new(db, me, e, body, "approved")
    db.commit()
    return _out(r, e.name)


@router.post("/leave/{leave_id}/decide")
def decide_leave(leave_id: int, body: DecideIn, me: User = Depends(att_edit),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    e, r = _locked(db, leave_id)
    if r.status != "pending":
        raise HTTPException(409, tx("Bu talep zaten sonuçlanmış"))
    if body.approve:
        _check_balance(db, e, r)
    _close(db, me, r, "approved" if body.approve else "rejected", body.note)
    db.commit()
    return _out(r, e.name)


@router.post("/leave/{leave_id}/cancel")
def cancel_leave(leave_id: int, body: NoteIn, me: User = Depends(att_edit),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    e, r = _locked(db, leave_id)
    if r.status != "approved":
        raise HTTPException(409, tx("Yalnızca onaylı izin iptal edilebilir"))
    _close(db, me, r, "cancelled", body.note or r.decision_note)
    db.commit()
    return _out(r, e.name)
