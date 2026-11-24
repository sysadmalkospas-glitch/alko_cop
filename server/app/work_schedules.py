"""Resolve the shift that starts on an employee's local work date."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Employee, Group, Office, WorkSchedule
from .office_timezones import local_instant, office_timezone
from .work_schedule_schemas import EmployeeWorkPlan, PlannedShift, WorkPattern

_pattern = TypeAdapter(WorkPattern)


def get_employee_work_plan(db: Session, employee_id: int, day: date) -> EmployeeWorkPlan | None:
    """Get the shift that starts on this local date.

    When calculating daily totals, also check the previous date for a shift
    that started before midnight and continues into this date.
    """
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
    schedule, timezone_name, employee_schedule_id = result
    return resolve_work_plan(schedule, office_timezone(timezone_name), employee_schedule_id, day)


def resolve_work_plan(
    schedule: WorkSchedule | None, zone: ZoneInfo, employee_schedule_id: int | None, day: date,
) -> EmployeeWorkPlan:
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
    starts_at, ends_at = local_instant(midnight + start, zone), local_instant(midnight + end, zone)
    if starts_at == ends_at:
        return work_plan

    pause = shift.break_offsets()
    break_starts_at = break_ends_at = None
    if pause is not None:
        break_starts_at, break_ends_at = (local_instant(midnight + offset, zone) for offset in pause)
        if break_starts_at == break_ends_at:
            break_starts_at = break_ends_at = None

    work_plan.shift = PlannedShift(
        starts_at=starts_at,
        ends_at=ends_at,
        break_starts_at=break_starts_at,
        break_ends_at=break_ends_at,
    )
    return work_plan
