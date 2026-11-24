"""Durable daily totals queue and periodic aggregation."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text, type_coerce, update
from sqlalchemy.dialects.postgresql import TSTZRANGE, Range, insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..daily_totals import Activity, calculate_daily_totals
from ..models import (
    ActivitySpan, DailyTotal, DailyTotalsPending, Employee, EmployeeLogin, Group, ObservedLogin,
    Office, WorkSchedule, as_utc, postgres_activity_span_range, utcnow,
)
from ..office_timezones import local_instant, office_timezone
from ..work_schedules import resolve_work_plan

DAY = timedelta(days=1)
DIRTY_DAYS_PER_RUN = 8
# Stable transaction advisory lock for this job across API processes.
JOB_LOCK = 2_291_598_356
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmployeeContext:
    id: int
    schedule: WorkSchedule | None
    own_schedule_id: int | None
    dismissed: bool


def enqueue_daily_totals(db: Session, spans: Iterable[tuple[datetime, datetime]]) -> None:
    """Insert compact UTC date ranges in the source mutation's transaction."""
    ranges: list[tuple[date, date]] = []
    for start, end in spans:
        start, end = as_utc(start), as_utc(end)
        if start < end:
            ranges.append((start.date(), (end - timedelta(microseconds=1)).date()))
    merged: list[DailyTotalsPending] = []
    for first, last in sorted(ranges):
        if merged and first.toordinal() <= merged[-1].last_day.toordinal() + 1:
            merged[-1].last_day = max(merged[-1].last_day, last)
        else:
            merged.append(DailyTotalsPending(next_day=first, last_day=last))
    db.add_all(merged)


def enqueue_login_history(db: Session, login_key: str) -> None:
    sighting = db.get(ObservedLogin, login_key)
    if sighting is not None:
        enqueue_daily_totals(db, [(sighting.first_seen_at, sighting.last_seen_at)])


def _claim_dirty_dates(db: Session) -> set[date]:
    days: set[date] = set()
    for _ in range(DIRTY_DAYS_PER_RUN):
        available = select(func.max(DailyTotalsPending.next_day))
        if days:
            available = available.where(DailyTotalsPending.next_day.not_in(sorted(days)))
        day = db.scalar(available)
        if day is None:
            break
        days.add(day)
        # Consume before reading spans. Concurrent uploads insert new queue rows, so a
        # later commit either appears in this calculation or leaves a retry for next run.
        at_day = DailyTotalsPending.next_day == day
        db.execute(delete(DailyTotalsPending).where(at_day, DailyTotalsPending.last_day == day))
        if day < date.max:
            db.execute(update(DailyTotalsPending).where(at_day, DailyTotalsPending.last_day > day)
                       .values(next_day=day + DAY))
    return days


def _employee_contexts(db: Session) -> dict[ZoneInfo, list[EmployeeContext]]:
    rows = db.execute(
        select(Employee.id, Office.timezone, WorkSchedule, Employee.schedule_id, Employee.is_dismissed)
        .select_from(Employee)
        .outerjoin(Group, Group.id == Employee.group_id)
        .outerjoin(Office, Office.id == Group.office_id)
        .outerjoin(WorkSchedule, WorkSchedule.id == func.coalesce(Employee.schedule_id, Group.schedule_id))
    )
    by_zone: dict[ZoneInfo, list[EmployeeContext]] = defaultdict(list)
    for employee_id, timezone, schedule, own_schedule_id, dismissed in rows:
        zone = office_timezone(timezone)
        by_zone[zone].append(EmployeeContext(employee_id, schedule, own_schedule_id, dismissed))
    return by_zone


def _target_dates(zone: ZoneInfo, now: datetime, dirty: set[date]) -> list[date]:
    today = now.astimezone(zone).date()
    days = {today}
    for utc_day in dirty:
        first = datetime.combine(utc_day, time.min, UTC)
        last = datetime.combine(utc_day, time.max, UTC)
        try:
            local_first, local_last = first.astimezone(zone).date(), last.astimezone(zone).date()
        except OverflowError:
            continue
        days.update(date.fromordinal(ordinal) for ordinal in range(local_first.toordinal(), local_last.toordinal() + 1))
    # Post-midnight activity can also affect attendance on the date a shift began.
    days.update(day - DAY for day in tuple(days) if day > date.min)
    return sorted(days)


def _read_activity(
    db: Session, start: datetime, end: datetime, bindings: dict[str, int], employee_ids: set[int],
) -> dict[int, list[Activity]]:
    result: dict[int, list[Activity]] = defaultdict(list)
    selected = {login: employee_id for login, employee_id in bindings.items() if employee_id in employee_ids}
    if not selected:
        return result
    query = select(ActivitySpan.login, ActivitySpan.started_at, ActivitySpan.ended_at, ActivitySpan.is_idle).where(
        ActivitySpan.started_at < end, ActivitySpan.ended_at > start,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.where(type_coerce(postgres_activity_span_range(), TSTZRANGE).overlaps(Range(start, end)))
    for login, first, last, idle in db.execute(query):
        employee_id = selected.get(login.casefold())
        if employee_id is not None:
            result[employee_id].append((as_utc(first), as_utc(last), idle))
    return result


def _save_totals(db: Session, rows: list[dict]) -> None:
    if not rows:
        return
    table = DailyTotal.__table__
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(table)
    db.execute(statement.on_conflict_do_update(
        index_elements=[table.c.employee_id, table.c.day],
        set_={column.name: statement.excluded[column.name] for column in table.c if not column.primary_key},
    ), rows)


def _refresh_day(
    db: Session, zone: ZoneInfo, day: date, employees: list[EmployeeContext], bindings: dict[str, int], now: datetime,
) -> None:
    if day in (date.min, date.max):
        return
    start, end = (
        local_instant(datetime.combine(value, time.min), zone) for value in (day, day + DAY)
    )
    if start >= end:
        return
    plans = {
        employee.id: resolve_work_plan(employee.schedule, zone, employee.own_schedule_id, day)
        for employee in employees
    }
    until = max([end, *(plan.shift.ends_at for plan in plans.values() if plan.shift is not None)])
    employee_ids = set(plans)
    activity = _read_activity(db, start, until, bindings, employee_ids)
    existing = set(db.scalars(select(DailyTotal.employee_id).where(
        DailyTotal.day == day, DailyTotal.employee_id.in_(employee_ids),
    )))
    rows = []
    for employee in employees:
        previous = resolve_work_plan(employee.schedule, zone, employee.own_schedule_id, day - DAY)
        plan = plans[employee.id]
        metrics = calculate_daily_totals(activity[employee.id], (start, end), plan, previous.shift, now)
        scheduled = plan.shift is not None or (previous.shift is not None and previous.shift.ends_at > start)
        if metrics.total_seconds or metrics.first_activity_at or (scheduled and not employee.dismissed) or employee.id in existing:
            rows.append({"employee_id": employee.id, "day": day, "updated_at": now, **asdict(metrics)})
    _save_totals(db, rows)


def process_daily_totals(engine: Engine, now: datetime | None = None) -> None:
    now = as_utc(now) if now is not None else utcnow()
    with Session(engine) as db, db.begin():
        if engine.dialect.name == "postgresql" and not db.scalar(select(func.pg_try_advisory_xact_lock(JOB_LOCK))):
            return
        if engine.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        dirty = _claim_dirty_dates(db)
        bindings = {
            login: employee_id
            for login, employee_id in db.execute(select(EmployeeLogin.login_key, EmployeeLogin.employee_id))
        }
        for zone, employees in _employee_contexts(db).items():
            for day in _target_dates(zone, now, dirty):
                _refresh_day(db, zone, day, employees, bindings, now)


async def run_daily_totals(engine: Engine, stop: asyncio.Event, interval_seconds: int) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            try:
                await asyncio.to_thread(process_daily_totals, engine)
            except Exception:
                logger.exception("Daily totals recalculation failed; pending dates will be retried")
