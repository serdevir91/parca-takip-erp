"""Shift arithmetic with no database: worked hours, breaks and weekly overtime."""
from __future__ import annotations

from datetime import date, datetime, timedelta

MAX_SHIFT_HOURS = 16     # an open shift older than this is a forgotten clock-out, not someone still at work
BREAK_AFTER_HOURS = 4    # shorter shifts get no default break


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def default_break(clock_in: datetime, clock_out: datetime, minutes: int) -> int:
    return minutes if clock_out - clock_in > timedelta(hours=BREAK_AFTER_HOURS) else 0


def worked_hours(clock_in: datetime, clock_out: datetime | None, break_minutes: int) -> float:
    if clock_out is None:
        return 0.0
    return round(max((clock_out - clock_in).total_seconds() / 60 - break_minutes, 0) / 60, 2)


def is_forgotten(clock_in: datetime, clock_out: datetime | None, now: datetime) -> bool:
    return clock_out is None and now - clock_in > timedelta(hours=MAX_SHIFT_HOURS)


def weekly_overtime(shifts: list[tuple[int, date, float]], week_hours: float) -> dict[int, float]:
    """Overtime per shift for one employee: what goes past the weekly limit, counted in time order, so it lands
    on the shifts that crossed the limit. `shifts` = (id, work_date, hours), sorted by time."""
    out: dict[int, float] = {}
    total: dict[date, float] = {}
    for sid, day, hours in shifts:
        week = week_start(day)
        before = total.get(week, 0.0)
        total[week] = before + hours
        out[sid] = round(max(before + hours - max(before, week_hours), 0), 2)
    return out
