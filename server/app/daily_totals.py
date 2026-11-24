"""Calendar-day activity and attendance arithmetic for employee work totals."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .work_schedule_schemas import EmployeeWorkPlan, PlannedShift

Interval = tuple[datetime, datetime]
Activity = tuple[datetime, datetime, bool]


@dataclass(frozen=True)
class DailyMetrics:
    first_activity_at: datetime | None
    last_activity_at: datetime | None
    total_seconds: int
    active_seconds: int
    idle_seconds: int
    late_seconds: int
    early_departure_seconds: int
    overtime_seconds: int


def _union(intervals: Iterable[Interval]) -> list[Interval]:
    combined: list[Interval] = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if combined and start <= combined[-1][1]:
            previous_start, previous_end = combined[-1]
            combined[-1] = previous_start, max(previous_end, end)
        else:
            combined.append((start, end))
    return combined


def _intersect(intervals: list[Interval], window: Interval) -> list[Interval]:
    lower, upper = window
    return [
        (max(start, lower), min(end, upper))
        for start, end in intervals
        if start < upper and end > lower
    ] if lower < upper else []


def _seconds(intervals: Iterable[Interval]) -> float:
    return sum((end - start).total_seconds() for start, end in intervals)


def _working_windows(shift: PlannedShift) -> list[Interval]:
    if shift.break_starts_at is None or shift.break_ends_at is None:
        return [(shift.starts_at, shift.ends_at)]
    return [(shift.starts_at, shift.break_starts_at), (shift.break_ends_at, shift.ends_at)]


def _attendance(active: list[Interval], plan: EmployeeWorkPlan, now: datetime) -> tuple[int, int]:
    if plan.shift is None:
        return 0, 0
    windows = _working_windows(plan.shift)
    observed = [portion for window in windows for portion in _intersect(active, window)]
    if not observed:
        return 0, 0

    first, last = observed[0][0], observed[-1][1]
    missed_at_start = _seconds(_intersect(windows, (plan.shift.starts_at, first)))
    tolerance = (plan.late_tolerance_minutes or 0) * 60
    late = int(missed_at_start) if missed_at_start > tolerance else 0
    early = int(_seconds(_intersect(windows, (last, plan.shift.ends_at)))) if now >= plan.shift.ends_at else 0
    return late, early


def calculate_daily_totals(
    activity: Iterable[Activity],
    day_window: Interval,
    plan: EmployeeWorkPlan,
    previous_shift: PlannedShift | None,
    now: datetime,
) -> DailyMetrics:
    spans, active = [], []
    for start, end, idle in activity:
        if start >= end:
            continue
        spans.append((start, end))
        if not idle:
            active.append((start, end))
    all_active = _union(active)
    daily_active = _intersect(all_active, day_window)
    active_time = _seconds(daily_active)
    total_seconds = int(_seconds(_intersect(_union(spans), day_window)))
    active_seconds = int(active_time)
    late, early = _attendance(all_active, plan, now)

    shifts = _union((shift.starts_at, shift.ends_at) for shift in (previous_shift, plan.shift) if shift is not None)
    # Lunch is inside the scheduled shift for overtime purposes.
    scheduled_active = sum(_seconds(_intersect(daily_active, window)) for window in shifts)
    overtime = int(max(0, active_time - scheduled_active)) if plan.schedule_id is not None else 0
    return DailyMetrics(
        first_activity_at=daily_active[0][0] if daily_active else None,
        last_activity_at=daily_active[-1][1] if daily_active else None,
        total_seconds=total_seconds,
        active_seconds=active_seconds,
        idle_seconds=total_seconds - active_seconds,
        late_seconds=late,
        early_departure_seconds=early,
        overtime_seconds=overtime,
    )
