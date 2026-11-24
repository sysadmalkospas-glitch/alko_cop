import pytest
from sqlalchemy import create_engine, text

from .test_directories import API, cabinet, create  # noqa: F401 (reuse cabinet fixture)

SCHEDULES = f"{API}/work-schedules"
MONDAY = "2026-11-23"
DAY_SHIFT = {"start": "09:00", "end": "18:00", "break_start": "12:00", "break_end": "13:00"}


def weekly(shift=DAY_SHIFT):
    return {"type": "weekly", "days": [shift] * 5 + [None, None]}


def read_plan(cabinet, employee, day=MONDAY):
    response = cabinet.get(f"{API}/employees/{employee['id']}/work-plan", params={"day": day})
    assert response.status_code == 200, response.text
    return response.json()


def assign(cabinet, resource, record, schedule):
    path = f"{API}/{resource}/{record['id']}/work-schedule"
    payload = {"schedule_id": schedule["id"] if schedule else None}
    assert cabinet.put(path, json=payload).json() == payload
    assert cabinet.get(path).json() == payload


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/work-schedules"),
    ("POST", "/work-schedules"),
    ("PUT", "/groups/1/work-schedule"),
    ("GET", f"/employees/1/work-plan?day={MONDAY}"),
])
def test_work_schedules_require_cabinet_session(client, agent, method, path):
    for headers in ({}, agent):
        response = client.request(method, f"{API}{path}", json={}, headers=headers)
        assert response.status_code == 401


def test_schedule_crud_and_validation(cabinet):
    schedule = create(cabinet, "work-schedules", name="Рабочая неделя", pattern=weekly(), late_tolerance_minutes=5)
    path = f"{SCHEDULES}/{schedule['id']}"
    assert cabinet.get(path).json() == schedule
    assert cabinet.get(SCHEDULES, params={"q": "РАБОЧАЯ"}).json()["items"] == [schedule]
    assert cabinet.post(SCHEDULES, json={"name": schedule["name"], "pattern": weekly()}).status_code == 409
    for invalid in (
        {"pattern": {"type": "weekly", "days": [DAY_SHIFT]}},
        {"pattern": {"type": "rotation", "anchor_date": MONDAY, "days": []}},
        {"pattern": {"type": "rotation", "anchor_date": MONDAY, "days": [None] * 367}},
        {"pattern": weekly({"start": "09:00Z", "end": "18:00"})},
        {"pattern": weekly({"start": "09:00", "end": "18:00", "break_start": "12:00"})},
        {"pattern": weekly({"start": "09:00", "end": "18:00", "break_start": "17:00", "break_end": "19:00"})},
        {"name": None},
        {"late_tolerance_minutes": -1},
    ):
        assert cabinet.patch(path, json=invalid).status_code == 422, invalid

    changed = cabinet.patch(path, json={"name": " Сменный ", "late_tolerance_minutes": 10, "pattern": weekly({
        "start": "08:00", "end": "17:00",
    })})
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Сменный"
    assert changed.json()["late_tolerance_minutes"] == 10
    assert changed.json()["pattern"]["days"][0]["start"] == "08:00:00"
    assert cabinet.delete(path).status_code == 204
    assert cabinet.get(path).status_code == 404


def test_weekly_plan_inherits_group_and_employee_override_restores_group(cabinet):
    office = create(cabinet, "offices", name="Север", timezone="Asia/Yekaterinburg")
    group = create(cabinet, "groups", name="Регистратура", office_id=office["id"])
    employee = create(cabinet, "employees", full_name="Иван Тестов", group_id=group["id"])
    assert read_plan(cabinet, employee) == {
        "date": MONDAY,
        "timezone": "Asia/Yekaterinburg",
        "schedule_id": None,
        "source": None,
        "late_tolerance_minutes": None,
        "shift": None,
    }
    regular = create(cabinet, "work-schedules", name="Основной", pattern=weekly(), late_tolerance_minutes=15)
    employee_path = f"{API}/employees/{employee['id']}/work-schedule"
    assert cabinet.put(employee_path, json={"schedule_id": 999}).status_code == 404
    assign(cabinet, "groups", group, regular)
    assert read_plan(cabinet, employee) == {
        "date": MONDAY,
        "timezone": "Asia/Yekaterinburg",
        "schedule_id": regular["id"],
        "source": "group",
        "late_tolerance_minutes": 15,
        "shift": {
            "starts_at": "2026-11-23T04:00:00Z",
            "ends_at": "2026-11-23T13:00:00Z",
            "break_starts_at": "2026-11-23T07:00:00Z",
            "break_ends_at": "2026-11-23T08:00:00Z",
        },
    }
    assert read_plan(cabinet, employee, "2026-11-28")["shift"] is None

    override = create(cabinet, "work-schedules", name="Исключение", pattern={
        "type": "rotation", "anchor_date": MONDAY, "days": [None, DAY_SHIFT, DAY_SHIFT, None],
    })
    assign(cabinet, "employees", employee, override)
    plan = read_plan(cabinet, employee)
    assert (plan["schedule_id"], plan["source"], plan["shift"]) == (override["id"], "employee", None)
    assert cabinet.delete(f"{SCHEDULES}/{override['id']}").status_code == 409
    assign(cabinet, "employees", employee, None)
    assert read_plan(cabinet, employee)["source"] == "group"
    assert cabinet.delete(f"{SCHEDULES}/{override['id']}").status_code == 204
    assert cabinet.delete(f"{SCHEDULES}/{regular['id']}").status_code == 409


def test_rotating_overnight_and_24h_shifts(cabinet):
    employee = create(cabinet, "employees", full_name="Валентина Тестова")
    rotation = create(cabinet, "work-schedules", name="Сутки через трое", pattern={
        "type": "rotation",
        "anchor_date": MONDAY,
        "days": [{"start": "08:00", "end": "08:00", "break_start": "23:50", "break_end": "00:10"}, None, None, None],
    })
    assign(cabinet, "employees", employee, rotation)
    plan = read_plan(cabinet, employee)
    assert plan["timezone"] == "Europe/Moscow"
    assert plan["shift"] == {
        "starts_at": "2026-11-23T05:00:00Z",
        "ends_at": "2026-11-24T05:00:00Z",
        "break_starts_at": "2026-11-23T20:50:00Z",
        "break_ends_at": "2026-11-23T21:10:00Z",
    }
    assert read_plan(cabinet, employee, "2026-11-24")["shift"] is None
    assert read_plan(cabinet, employee, "2026-11-27")["shift"]["starts_at"] == "2026-11-27T05:00:00Z"
    assert read_plan(cabinet, employee, "2026-11-19")["shift"]["starts_at"] == "2026-11-19T05:00:00Z"

    assert cabinet.patch(f"{SCHEDULES}/{rotation['id']}", json={
        "pattern": {"type": "rotation", "anchor_date": MONDAY, "days": [{
            "start": "22:00", "end": "06:00", "break_start": "02:00", "break_end": "02:30",
        }]},
    }).status_code == 200
    assert read_plan(cabinet, employee)["shift"] == {
        "starts_at": "2026-11-23T19:00:00Z",
        "ends_at": "2026-11-24T03:00:00Z",
        "break_starts_at": "2026-11-23T23:00:00Z",
        "break_ends_at": "2026-11-23T23:30:00Z",
    }
    assert cabinet.get(
        f"{API}/employees/{employee['id']}/work-plan", params={"day": "9999-12-31"},
    ).status_code == 422


def test_dst_and_fallback_for_legacy_office_timezone(cabinet, settings):
    office = create(cabinet, "offices", name="Тест", timezone="America/New_York")
    group = create(cabinet, "groups", name="Тест", office_id=office["id"])
    employee = create(cabinet, "employees", full_name="Иван Тестов", group_id=group["id"])
    schedule = create(cabinet, "work-schedules", name="Смена", pattern={
        "type": "weekly", "days": [None] * 6 + [{"start": "02:20", "end": "03:30"}],
    })
    assign(cabinet, "employees", employee, schedule)
    spring = read_plan(cabinet, employee, "2026-03-08")
    assert spring["shift"]["starts_at"] == "2026-03-08T07:00:00Z"
    assert spring["shift"]["ends_at"] == "2026-03-08T07:30:00Z"

    assert cabinet.post(f"{API}/offices", json={
        "name": "Invalid office", "timezone": "Europe/Moskow",
    }).status_code == 422
    assert cabinet.patch(f"{API}/offices/{office['id']}", json={"timezone": "Legacy"}).status_code == 422
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as db:
            db.execute(text("UPDATE offices SET timezone = 'Legacy' WHERE id = :id"), {"id": office["id"]})
    finally:
        engine.dispose()
    fallback = read_plan(cabinet, employee, "2026-03-08")
    assert fallback["timezone"] == "Europe/Moscow"
    assert fallback["shift"]["starts_at"] == "2026-03-07T23:20:00Z"
