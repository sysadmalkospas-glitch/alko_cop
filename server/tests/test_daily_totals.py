from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.jobs import daily_totals
from app.jobs.daily_totals import enqueue_daily_totals, process_daily_totals
from app.models import DailyTotal, DailyTotalsPending, as_utc

from .conftest import ENROLL_KEY
from .test_day_chronology import span, upload
from .test_directories import API, cabinet, create  # noqa: F401 (reuse cabinet fixture)
from .test_work_schedules import assign

MONDAY = date(2026, 11, 23)
TUESDAY = date(2026, 11, 24)


def totals(employee, day):
    with Session(get_engine()) as db:
        return db.get(DailyTotal, (employee["id"], day))


def run(at=datetime(2026, 11, 26, 10, tzinfo=UTC)):
    process_daily_totals(get_engine(), at)


def work_schedule(cabinet, employee, shift):
    office = create(cabinet, "offices", name="Тестовый офис", timezone="Europe/Moscow")
    group = create(cabinet, "groups", name="Тестовая смена", office_id=office["id"])
    assert cabinet.patch(f"{API}/employees/{employee['id']}", json={"group_id": group["id"]}).status_code == 200
    schedule = create(cabinet, "work-schedules", name="Тестовый график", late_tolerance_minutes=5, pattern={
        "type": "weekly", "days": [shift] + [None] * 6,
    })
    assign(cabinet, "groups", group, schedule)


def test_daily_totals_count_multi_computer_activity_once_and_distinguish_gaps(cabinet, agent):
    employee = create(cabinet, "employees", full_name="Тестовый сотрудник")
    create(cabinet, f"employees/{employee['id']}/logins", login=r"clinic\Straße")
    work_schedule(cabinet, employee, {
        "start": "09:00", "end": "18:00", "break_start": "12:00", "break_end": "13:00",
    })
    second = cabinet.post("/api/agent/v1/enroll", json={
        "enroll_key": ENROLL_KEY, "machine_id": "machine-0002", "hostname": "PC-2",
    })
    assert second.status_code == 200
    second_agent = {"Authorization": f"Bearer {second.json()['token']}"}
    staff = r"CLINIC\STRASSE"
    batch = [
        span("first", "2026-11-23T06:07:00Z", "2026-11-23T09:00:00Z", login=staff),
        span("lunch", "2026-11-23T09:00:00Z", "2026-11-23T10:00:00Z", login=staff, is_idle=True),
        span("last", "2026-11-23T10:15:00Z", "2026-11-23T14:30:00Z", login=staff),
        span("wrong-user", "2026-11-23T15:05:00Z", "2026-11-23T15:25:00Z"),
    ]
    upload(cabinet, agent, batch)
    upload(cabinet, second_agent, [
        span("overlap", "2026-11-23T06:10:00Z", "2026-11-23T07:11:00Z", login=staff),
        span("partial-idle", "2026-11-23T06:20:00Z", "2026-11-23T06:21:00Z", login=staff, is_idle=True),
    ])
    assert cabinet.post("/api/agent/v1/activity", headers=agent, json={"spans": batch}).json()["accepted_spans"] == 0
    run()
    result = totals(employee, MONDAY)
    assert result is not None
    assert as_utc(result.first_activity_at).isoformat() == "2026-11-23T06:07:00+00:00"
    assert as_utc(result.last_activity_at).isoformat() == "2026-11-23T14:30:00+00:00"
    assert (result.total_seconds, result.active_seconds, result.idle_seconds) == (29280, 25680, 3600)
    assert (result.late_seconds, result.early_departure_seconds, result.overtime_seconds) == (420, 1800, 0)
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(DailyTotalsPending)) == 0


def test_previous_night_stays_planned_and_late_data_recalculates_both_days(cabinet, agent):
    employee = create(cabinet, "employees", full_name="Тестовая ночная смена")
    create(cabinet, f"employees/{employee['id']}/logins", login=r"clinic\staff")
    work_schedule(cabinet, employee, {
        "start": "20:00", "end": "08:00", "break_start": "00:30", "break_end": "01:00",
    })
    upload(cabinet, agent, [
        span("before-lunch", "2026-11-23T17:08:00Z", "2026-11-23T21:30:00Z"),
        span("lunch", "2026-11-23T21:30:00Z", "2026-11-23T22:00:00Z", is_idle=True),
        span("after-lunch", "2026-11-23T22:00:00Z", "2026-11-24T04:45:00Z"),
    ])
    run(datetime(2026, 11, 24, 4, 50, tzinfo=UTC))
    assert totals(employee, MONDAY).early_departure_seconds == 0
    run(datetime(2026, 11, 24, 6, tzinfo=UTC))
    first = totals(employee, MONDAY)
    second = totals(employee, TUESDAY)
    assert (first.active_seconds, first.late_seconds, first.early_departure_seconds) == (13920, 480, 900)
    assert (second.active_seconds, second.idle_seconds, second.overtime_seconds) == (26100, 1800, 0)
    assert as_utc(first.last_activity_at) == as_utc(second.first_activity_at)

    upload(cabinet, agent, [span("late", "2026-11-24T04:45:00Z", "2026-11-24T05:10:00Z")])
    run()
    assert totals(employee, MONDAY).early_departure_seconds == 0
    assert totals(employee, TUESDAY).active_seconds == 27600
    assert totals(employee, TUESDAY).overtime_seconds == 600


def test_binding_and_unbinding_a_historical_login_rebuilds_totals(cabinet, agent):
    old_owner = create(cabinet, "employees", full_name="Первый сотрудник")
    new_owner = create(cabinet, "employees", full_name="Второй сотрудник")
    upload(cabinet, agent, [span("single", "2026-11-23T16:00:00Z", "2026-11-23T16:01:00Z")])
    run()
    assert totals(old_owner, MONDAY) is None

    link = create(cabinet, f"employees/{old_owner['id']}/logins", login=r"clinic\staff")
    run()
    assert totals(old_owner, MONDAY).active_seconds == 60
    assert cabinet.delete(f"{API}/employees/{old_owner['id']}/logins/{link['id']}").status_code == 204
    create(cabinet, f"employees/{new_owner['id']}/logins", login=r"clinic\staff")
    run()
    assert totals(old_owner, MONDAY).active_seconds == 0
    assert totals(old_owner, MONDAY).first_activity_at is None
    assert totals(new_owner, MONDAY).active_seconds == 60


def test_day_uses_office_timezone_and_handles_a_25_hour_day(cabinet, agent):
    office = create(cabinet, "offices", name="Berlin", timezone="Europe/Berlin")
    group = create(cabinet, "groups", name="Team", office_id=office["id"])
    employee = create(cabinet, "employees", full_name="Staff", group_id=group["id"])
    create(cabinet, f"employees/{employee['id']}/logins", login=r"clinic\staff")
    upload(cabinet, agent, [
        span("dst", "2026-10-24T23:50:00+02:00", "2026-10-26T00:10:00+01:00"),
    ])
    run()
    assert totals(employee, date(2026, 10, 24)).active_seconds == 600
    assert totals(employee, date(2026, 10, 25)).active_seconds == 25 * 3600
    assert totals(employee, date(2026, 10, 26)).active_seconds == 600


def test_very_long_ingest_remains_a_compact_durable_range(client, agent):
    upload(client, agent, [span("long", "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z")])
    with Session(get_engine()) as db:
        queued = db.scalars(select(DailyTotalsPending)).one()
        assert (queued.next_day, queued.last_day) == (date(2026, 1, 1), date(2026, 12, 30))
    run()
    with Session(get_engine()) as db:
        queued = db.scalars(select(DailyTotalsPending)).one()
        assert queued.next_day == date(2026, 1, 9)


def test_failed_worker_transaction_leaves_the_dirty_date_queued(client, monkeypatch):
    with Session(get_engine()) as db, db.begin():
        enqueue_daily_totals(db, [(datetime(2026, 11, 23, 1, tzinfo=UTC), datetime(2026, 11, 23, 2, tzinfo=UTC))])
    with monkeypatch.context() as patch:
        def fail(_):
            raise RuntimeError("Unable to read staff")

        patch.setattr(daily_totals, "_employee_contexts", fail)
        with pytest.raises(RuntimeError, match="Unable to read staff"):
            run()
    with Session(get_engine()) as db:
        assert db.scalars(select(DailyTotalsPending)).one().next_day == MONDAY
    run()
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(DailyTotalsPending)) == 0
