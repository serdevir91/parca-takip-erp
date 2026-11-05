"""Shift arithmetic with no database: worked hours, breaks and weekly overtime."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from . import numbers as num

MAX_SHIFT_HOURS = 16     # an open shift older than this is a forgotten clock-out, not someone still at work
BREAK_AFTER_HOURS = 4    # shorter shifts get no default break
PAID_LEAVE = ("annual", "sick", "excuse")   # these cover the hours of the day; unpaid leave does not


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def working_days(first: date, last: date, off: dict[date, float] | None = None) -> float:
    """Monday to Friday days from `first` to `last`, both included, less the part of each day in `off` (public
    holidays). No loop: a mistyped year must stay cheap."""
    if last < first:
        return 0
    weeks, rest = divmod((last - first).days + 1, 7)
    days = weeks * 5 + sum((first.weekday() + i) % 7 < 5 for i in range(rest))
    return days - sum(part for d, part in (off or {}).items() if first <= d <= last and d.weekday() < 5)


def default_break(clock_in: datetime, clock_out: datetime, minutes: int) -> int:
    return minutes if clock_out - clock_in > timedelta(hours=BREAK_AFTER_HOURS) else 0


def worked_hours(clock_in: datetime, clock_out: datetime | None, break_minutes: int) -> float:
    if clock_out is None:
        return 0.0
    return num.hours(max((clock_out - clock_in).total_seconds() / 60 - break_minutes, 0) / 60)


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
        out[sid] = num.hours(max(before + hours - max(before, week_hours), 0))
    return out


def day_balance(first: date, last: date, today: date, work_hours: float, worked: dict[date, float],
                leaves: dict[date, str], start_date: date | None = None, active: bool = True,
                holidays: dict[date, float] | None = None) -> dict[str, Any]:
    """What one employee owed in a period against what they did. A Monday to Friday day is expected once it has
    passed, from the hire date on. Today counts only with hours or leave on it, as the day is not over. Inactive
    cards have no leaving date, so only their recorded days count. Paid leave covers what the shifts of that day
    left open. Unpaid leave is no missing day, but its hours stay uncovered and show up in `short`. A public holiday
    (`holidays`: the part of the day that is off) lowers what the day owes; hours worked on it still count."""
    off = holidays or {}
    owed = lambda d: work_hours * (1 - off.get(d, 0.0))  # noqa: E731
    begin = max(first, start_date) if start_date else first
    elapsed = min(last, today - timedelta(days=1))
    base = working_days(begin, elapsed) if active else 0
    free = sum(1 for d, part in off.items() if part >= 1 and begin <= d <= elapsed and d.weekday() < 5) if active else 0
    half = sum(part for d, part in off.items() if part < 1 and begin <= d <= elapsed and d.weekday() < 5) if active else 0
    marked = {d for d in {*worked, *leaves} if begin <= d <= min(last, today) and d.weekday() < 5
              and (d < today or worked.get(d) or d in leaves)}
    extra = {d for d in marked if not active or d > elapsed}
    covered = sum(max(owed(d) - worked.get(d, 0.0), 0.0) for d in marked
                  if leaves.get(d) in PAID_LEAVE)
    expected = (base - free - half) * work_hours + sum(owed(d) for d in extra)
    hours = sum(h for d, h in worked.items() if first <= d <= last)
    kinds: dict[str, int] = {}
    for d, kind in leaves.items():
        if first <= d <= last:
            kinds[kind] = kinds.get(kind, 0) + 1
    return {"expected": num.hours(expected), "covered": num.hours(covered), "missing_days": base - free - len({d for d in marked - extra if off.get(d, 0.0) < 1}),
            "short": num.hours(max(expected - hours - covered, 0.0)), "leave": kinds}
