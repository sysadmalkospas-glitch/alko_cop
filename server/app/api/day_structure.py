"""Daily activity timeline for an office's group."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from heapq import heappop, heappush
from itertools import pairwise
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select

from ..auth import SessionDep, current_user
from ..directory_schemas import MAX_DIRECTORY_ID, DirectoryId
from ..models import ActivitySpan, Employee, EmployeeLogin, Group, Office, as_utc
from ..office_timezones import office_timezone
from ..report_activity import local_day_bounds, overlapping_activity
from ..work_schedules import get_employee_work_plan

router = APIRouter(
    prefix="/api/v1/reports/day-structure", tags=["reports"], dependencies=[Depends(current_user)],
)

ActivityStatus = Literal["active", "idle", "no_data"]


class Interval(BaseModel):
    starts_at: datetime
    ends_at: datetime


class ActivityInterval(Interval):
    status: ActivityStatus
    process_name: str | None = None
    window_title: str | None = None


class ScheduleInterval(Interval):
    is_break: bool = False


class EmployeeTimeline(BaseModel):
    employee_id: int
    full_name: str
    activity: list[ActivityInterval]
    schedule: list[ScheduleInterval]


class DayStructure(Interval):
    day: date
    timezone: str
    total: int
    rows: list[EmployeeTimeline]


@dataclass(frozen=True, slots=True)
class RecordedSpan:
    start: datetime
    end: datetime
    idle: bool
    process_name: str | None
    window_title: str | None


def _activities(spans: list[RecordedSpan], start: datetime, end: datetime) -> list[ActivityInterval]:
    """Make nonoverlapping bands. Prefer work, then the most recent observation."""
    edges = sorted({start, end, *(point for span in spans for point in (span.start, span.end))})
    pending = iter(enumerate(spans))
    upcoming = next(pending, None)
    active: list[tuple[bool, int, RecordedSpan]] = []
    intervals: list[ActivityInterval] = []
    previous = None
    for left, right in pairwise(edges):
        while upcoming is not None and upcoming[1].start <= left:
            rank, span = upcoming
            heappush(active, (span.idle, -rank, span))
            upcoming = next(pending, None)
        while active and active[0][2].end <= left:
            heappop(active)
        if active:
            span = active[0][2]
            current = ("idle" if span.idle else "active", span.process_name, span.window_title)
        else:
            current = ("no_data", None, None)
        if current == previous:
            intervals[-1].ends_at = right
        else:
            state, process, title = current
            intervals.append(ActivityInterval(
                starts_at=left, ends_at=right, status=state, process_name=process, window_title=title,
            ))
            previous = current
    return intervals


def _recorded_spans(
    db: SessionDep, employee_ids: list[int], start: datetime, end: datetime,
) -> dict[int, list[RecordedSpan]]:
    if not employee_ids:
        return {}
    employees_by_login = {
        login_key: employee_id
        for login_key, employee_id in db.execute(
            select(EmployeeLogin.login_key, EmployeeLogin.employee_id)
            .where(EmployeeLogin.employee_id.in_(employee_ids)),
        )
    }
    if not employees_by_login:
        return {}

    # Use the same Unicode casefold as login bindings while keeping the stored raw logins.
    overlap = overlapping_activity(db, start, end)
    spellings = {
        raw: employees_by_login[raw.casefold()]
        for raw in db.scalars(select(ActivitySpan.login).where(*overlap).distinct())
        if raw.casefold() in employees_by_login
    }
    if not spellings:
        return {}
    spans = db.execute(
        select(ActivitySpan.login, ActivitySpan.started_at, ActivitySpan.ended_at, ActivitySpan.is_idle,
               ActivitySpan.process_name, ActivitySpan.window_title)
        .where(ActivitySpan.login.in_(spellings), *overlap)
        .order_by(ActivitySpan.started_at, ActivitySpan.id)
        .execution_options(yield_per=1000),
    )
    by_employee: dict[int, list[RecordedSpan]] = defaultdict(list)
    for login, started, ended, idle, process, title in spans:
        left, right = max(start, as_utc(started)), min(end, as_utc(ended))
        if left < right:
            by_employee[spellings[login]].append(RecordedSpan(left, right, idle, process, title))
    return by_employee


def _schedule(
    db: SessionDep, employee_id: int, previous_day: date, day: date, start: datetime, end: datetime,
) -> list[ScheduleInterval]:
    intervals = []
    for shift_day in (previous_day, day):
        plan = get_employee_work_plan(db, employee_id, shift_day)
        if plan is None or plan.shift is None:
            continue
        shift = plan.shift
        parts = [(shift.starts_at, shift.ends_at, False)]
        if shift.break_starts_at is not None and shift.break_ends_at is not None:
            parts = [
                (shift.starts_at, shift.break_starts_at, False),
                (shift.break_starts_at, shift.break_ends_at, True),
                (shift.break_ends_at, shift.ends_at, False),
            ]
        for left, right, is_break in parts:
            left, right = max(start, left), min(end, right)
            if left < right:
                intervals.append(ScheduleInterval(starts_at=left, ends_at=right, is_break=is_break))
    return intervals


@router.get("", response_model=DayStructure)
def day_structure(
    db: SessionDep, response: Response, group_id: DirectoryId, day: date,
    limit: Annotated[int, Query(ge=1, le=30)] = 30,
    offset: Annotated[int, Query(ge=0, le=MAX_DIRECTORY_ID)] = 0,
) -> DayStructure:
    group = db.execute(
        select(Group.schedule_id, Office.timezone).outerjoin(Office, Office.id == Group.office_id)
        .where(Group.id == group_id),
    ).one_or_none()
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    zone = office_timezone(group.timezone)
    try:
        previous_day = day - timedelta(days=1)
        start, end = local_day_bounds(day, zone)
    except OverflowError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Day is out of range") from None
    if start >= end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Day does not exist in the office timezone")

    group_employees = Employee.group_id == group_id
    total = db.scalar(select(func.count()).select_from(Employee).where(group_employees))
    employees = db.execute(
        select(Employee.id, Employee.full_name, Employee.schedule_id).where(group_employees)
        .order_by(func.lower(Employee.full_name), Employee.id).offset(offset).limit(limit),
    ).all()
    spans = _recorded_spans(db, [employee.id for employee in employees], start, end)
    rows = []
    try:
        for employee in employees:
            schedule = (
                _schedule(db, employee.id, previous_day, day, start, end)
                if employee.schedule_id is not None or group.schedule_id is not None else []
            )
            rows.append(EmployeeTimeline(
                employee_id=employee.id, full_name=employee.full_name, schedule=schedule,
                activity=_activities(spans.get(employee.id, []), start, end),
            ))
    except OverflowError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Day is out of range") from None
    response.headers["Cache-Control"] = "no-store"
    return DayStructure(day=day, timezone=zone.key, starts_at=start, ends_at=end, total=total, rows=rows)
