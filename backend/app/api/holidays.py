"""Resmi tatil listesi: everyone may read it, admins keep it."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Holiday, User
from ..services import audit
from ..services import holidays as svc
from .deps import admin, any_user, get_db
from app.core.i18n import tx

router = APIRouter(tags=["holidays"])


class HolidayIn(BaseModel):
    day: date
    until: date | None = None
    name: str = Field(min_length=1, max_length=100)
    half_day: bool = False


class HolidayEdit(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    half_day: bool = False


class FixedIn(BaseModel):
    year: int = Field(ge=2000, le=2100)


def _holiday_or_404(db: Session, holiday_id: int) -> Holiday:
    h = db.get(Holiday, holiday_id)
    if h is None:
        raise HTTPException(404, tx("Tatil bulunamadı"))
    return h


@router.get("/holidays")
def list_holidays(year: int | None = None, _: User = Depends(any_user),
                  db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(Holiday).order_by(Holiday.day)
    if year is not None:
        q = q.where(Holiday.day >= date(year, 1, 1), Holiday.day <= date(year, 12, 31))
    return [svc.holiday_out(h) for h in db.scalars(q)]


@router.post("/holidays", status_code=201)
def add_holiday(body: HolidayIn, me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    made = svc.add_range(db, me, body.day, body.until, body.name.strip(), body.half_day)
    if not made:
        raise HTTPException(409, tx("Bu günler listede zaten var"))
    db.commit()
    return {"added": len(made)}


@router.post("/holidays/fixed", status_code=201)
def add_fixed(body: FixedIn, me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    made = svc.add_fixed(db, me, body.year)
    db.commit()
    return {"added": len(made)}


@router.put("/holidays/{holiday_id}")
def edit_holiday(holiday_id: int, body: HolidayEdit, me: User = Depends(admin),
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    h = _holiday_or_404(db, holiday_id)
    audit.record_changes(db, me, h, {"name": body.name.strip(), "half_day": body.half_day}, "holiday", h.id)
    db.commit()
    return svc.holiday_out(h)


@router.delete("/holidays/{holiday_id}")
def delete_holiday(holiday_id: int, me: User = Depends(admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    h = _holiday_or_404(db, holiday_id)
    audit.record(db, me, "holiday", h.id, "day", h.day.isoformat(), None, action="delete")
    db.delete(h)
    db.commit()
    return {"ok": True}
