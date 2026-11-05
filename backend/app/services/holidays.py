"""Resmi tatiller. Expected hours and leave days skip them; a half day counts for half.

The dates of the religious holidays move every year and depend on an official announcement, so only the fixed days
come ready to add. An admin enters the bayram days as a range. Like `erp`, these functions do not commit.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Holiday, User
from . import audit
from app.core.i18n import tx

FIXED = [(1, 1, "Yılbaşı", False), (4, 23, "Ulusal Egemenlik ve Çocuk Bayramı", False),
         (5, 1, "Emek ve Dayanışma Günü", False), (5, 19, "Atatürk'ü Anma, Gençlik ve Spor Bayramı", False),
         (7, 15, "Demokrasi ve Millî Birlik Günü", False), (8, 30, "Zafer Bayramı", False),
         (10, 28, "Cumhuriyet Bayramı arifesi", True), (10, 29, "Cumhuriyet Bayramı", False)]
MAX_RANGE_DAYS = 31


def off_days(db: Session, first: date, last: date) -> dict[date, float]:
    """Holidays in the period, as the part of the day that is off."""
    q = select(Holiday.day, Holiday.half_day).where(Holiday.day >= first, Holiday.day <= last)
    return {d: 0.5 if half else 1.0 for d, half in db.execute(q)}


def holiday_out(h: Holiday) -> dict[str, Any]:
    return {"id": h.id, "day": h.day.isoformat(), "name": h.name, "half_day": h.half_day}


def add_range(db: Session, user: User, first: date, last: date | None, name: str, half_day: bool) -> list[Holiday]:
    """One row per day. Days that already exist are left as they are."""
    last = last or first
    if last < first:
        raise HTTPException(400, tx("Bitiş tarihi başlangıçtan önce olamaz"))
    if (last - first).days >= MAX_RANGE_DAYS:
        raise HTTPException(400, tx("Bir kerede en fazla {0} gün eklenir", MAX_RANGE_DAYS))
    have = set(off_days(db, first, last))
    made = []
    for i in range((last - first).days + 1):
        d = first + timedelta(days=i)
        if d not in have:
            h = Holiday(day=d, name=name, half_day=half_day)
            db.add(h)
            made.append(h)
    db.flush()
    for h in made:
        audit.record(db, user, "holiday", h.id, "day", None, h.day.isoformat(), action="create")
    return made


def add_fixed(db: Session, user: User, year: int) -> list[Holiday]:
    made: list[Holiday] = []
    for month, day, name, half in FIXED:
        d = date(year, month, day)
        made += add_range(db, user, d, d, name, half)
    return made
