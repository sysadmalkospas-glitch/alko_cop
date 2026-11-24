"""Resolve the shift that starts on an employee's local work date."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Employee, Group, Office, WorkSchedule
from .work_schedule_schemas import EmployeeWorkPlan, PlannedShift, WorkPattern

DEFAULT_OFFICE_TIMEZONE = "Europe/Moscow"
_pattern = TypeAdapter(WorkPattern)


def _office_timezone(name: str | None) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            # Older offices could store strings that do not name an IANA timezone.
            pass
    return ZoneInfo(DEFAULT_OFFICE_TIMEZONE)


def _instant(local: datetime, zone: ZoneInfo) -> datetime:
    first = local.replace(tzinfo=zone, fold=0).astimezone(UTC)
    if first.astimezone(zone).replace(tzinfo=None) == local:
        return first

    # During a forward clock change, clamp nonexistent wall times to the first
    # valid instant. Both endpoints in the gap then produce no phantom work.
    lower = local.replace(tzinfo=zone, fold=1).astimezone(UTC)
    upper = first
    while upper - lower > timedelta(microseconds=1):
        midpoint = lower + (upper - lower) // 2
        if midpoint.astimezone(zone).replace(tzinfo=None) < local:
            lower = midpoint
        else:
            upper = midpoint
    return upper


def get_employee_work_plan(db: Session, employee_id: int, day: date) -> EmployeeWorkPlan | None:
    result = db.execute(
        select(WorkSchedule, Office.timezone, Employee.schedule_id)
        .select_from(Employee)
        .outerjoin(Group, Group.id == Employee.group_id)
        .outerjoin(Office, Office.id == Group.office_id)
        .outerjoin(WorkSchedule, WorkSchedule.id == func.coalesce(Employee.schedule_id, Group.schedule_id))
        .where(Employee.id == employee_id)
    ).one_or_none()
    if result is None:
        return None
    schedule, office_timezone, employee_schedule_id = result
    zone = _office_timezone(office_timezone)
    if schedule is None:
        return EmployeeWorkPlan(date=day, timezone=zone.key)

    work_plan = EmployeeWorkPlan(
        date=day,
        timezone=zone.key,
        schedule_id=schedule.id,
        source="employee" if employee_schedule_id is not None else "group",
        late_tolerance_minutes=schedule.late_tolerance_minutes,
    )
    shift = _pattern.validate_python(schedule.pattern).shift_for(day)
    if shift is None:
        return work_plan

    midnight = datetime.combine(day, time.min)
    start, end = shift.shift_offsets()
    starts_at, ends_at = _instant(midnight + start, zone), _instant(midnight + end, zone)
    if starts_at == ends_at:
        return work_plan

    pause = shift.break_offsets()
    break_starts_at = break_ends_at = None
    if pause is not None:
        break_starts_at, break_ends_at = (_instant(midnight + offset, zone) for offset in pause)
        if break_starts_at == break_ends_at:
            break_starts_at = break_ends_at = None

    work_plan.shift = PlannedShift(
        starts_at=starts_at,
        ends_at=ends_at,
        break_starts_at=break_starts_at,
        break_ends_at=break_ends_at,
    )
    return work_plan
