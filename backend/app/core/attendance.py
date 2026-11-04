"""Shift arithmetic with no database: worked hours, breaks and weekly overtime."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

MAX_SHIFT_HOURS = 16     # an open shift older than this is a forgotten clock-out, not someone still at work
BREAK_AFTER_HOURS = 4    # shorter shifts get no default break
PAID_LEAVE = ("annual", "sick", "excuse")   # these cover the hours of the day; unpaid leave does not


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def working_days(first: date, last: date) -> int:
    """Monday to Friday days from `first` to `last`, both included. No loop: a mistyped year must stay cheap."""
    if last < first:
        return 0
    weeks, rest = divmod((last - first).days + 1, 7)
    return weeks * 5 + sum((first.weekday() + i) % 7 < 5 for i in range(rest))


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


def day_balance(first: date, last: date, today: date, work_hours: float, worked: dict[date, float],
                leaves: dict[date, str], start_date: date | None = None, active: bool = True) -> dict[str, Any]:
    """What one employee owed in a period against what they did. A Monday to Friday day is expected once it has
    passed, from the hire date on. Today counts only with hours or leave on it, as the day is not over. Inactive
    cards have no leaving date, so only their recorded days count. Paid leave covers what the shifts of that day
    left open. Unpaid leave is no missing day, but its hours stay uncovered and show up in `short`."""
    begin = max(first, start_date) if start_date else first
    elapsed = min(last, today - timedelta(days=1))
    base = working_days(begin, elapsed) if active else 0
    marked = {d for d in {*worked, *leaves} if begin <= d <= min(last, today) and d.weekday() < 5
              and (d < today or worked.get(d) or d in leaves)}
    extra = {d for d in marked if not active or d > elapsed}
    covered = sum(max(work_hours - worked.get(d, 0.0), 0.0) for d in marked
                  if leaves.get(d) in PAID_LEAVE)
    expected = (base + len(extra)) * work_hours
    hours = sum(h for d, h in worked.items() if first <= d <= last)
    kinds: dict[str, int] = {}
    for d, kind in leaves.items():
        if first <= d <= last:
            kinds[kind] = kinds.get(kind, 0) + 1
    return {"expected": round(expected, 2), "covered": round(covered, 2), "missing_days": base - len(marked - extra),
            "short": round(max(expected - hours - covered, 0.0), 2), "leave": kinds}
