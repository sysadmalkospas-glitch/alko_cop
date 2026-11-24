from datetime import datetime

import pytest

from .test_day_chronology import bind, span, upload
from .test_directories import cabinet, create  # noqa: F401

REPORT = "/api/v1/reports/day-structure"
DAY = "2026-11-24"
UTC_START = "2026-11-23T21:00:00Z"
UTC_END = "2026-11-24T21:00:00Z"


def test_day_structure_requires_cabinet_session(client, agent):
    for headers in ({}, agent):
        response = client.get(REPORT, headers=headers, params={"group_id": 1, "day": DAY})
        assert response.status_code == 401


def test_day_structure_clips_merges_and_keeps_gaps_and_night_schedule(cabinet, agent):
    office = create(cabinet, "offices", name="Clinic", timezone="Europe/Moscow")
    group = create(cabinet, "groups", name="Day team", office_id=office["id"])
    other = create(cabinet, "groups", name="Other team", office_id=office["id"])
    employee = create(cabinet, "employees", full_name="A employee", group_id=group["id"])
    empty = create(cabinet, "employees", full_name="B employee", group_id=group["id"])
    external = create(cabinet, "employees", full_name="Not in group", group_id=other["id"])
    bind(cabinet, employee, r"clinic\straße")
    bind(cabinet, employee, r"clinic\second")
    bind(cabinet, external, r"clinic\other")

    night = {"start": "22:00", "end": "06:00", "break_start": "02:00", "break_end": "02:30"}
    schedule = create(cabinet, "work-schedules", name="Night schedule", pattern={
        "type": "weekly", "days": [night, None, None, None, None, None, None],
    })
    assert cabinet.put(f"/api/v1/groups/{group['id']}/work-schedule", json={
        "schedule_id": schedule["id"],
    }).status_code == 200
    day_off = create(cabinet, "work-schedules", name="Personal days off", pattern={
        "type": "weekly", "days": [None] * 7,
    })
    assert cabinet.put(f"/api/v1/employees/{empty['id']}/work-schedule", json={
        "schedule_id": day_off["id"],
    }).status_code == 200

    work = {"login": r"CLINIC\STRASSE", "process_name": "demo.exe", "window_title": "Тестовое окно"}
    upload(cabinet, agent, [
        span("cross", "2026-11-23T20:59:30Z", "2026-11-23T21:00:30Z", **work),
        span("touch", "2026-11-23T21:00:30Z", "2026-11-23T21:01:00Z", **work),
        span("idle", "2026-11-23T21:00:45Z", "2026-11-23T21:02:00Z", login=r"CLINIC\Second", is_idle=True),
        span("external", "2026-11-23T21:00:00Z", "2026-11-23T21:03:00Z", login=r"CLINIC\Other"),
        span("later", "2026-11-23T21:02:01Z", "2026-11-23T21:03:00Z", **work),
        span("next day", UTC_END, "2026-11-24T21:01:00Z", **work),
    ])
    filters = {"group_id": group["id"], "day": DAY}
    response = cabinet.get(REPORT, params=filters)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert (result["starts_at"], result["ends_at"], result["timezone"], result["total"]) == (
        UTC_START, UTC_END, "Europe/Moscow", 2,
    )
    first, second = result["rows"]
    assert first["employee_id"] == employee["id"] and second["employee_id"] == empty["id"]
    assert first["schedule"] == [
        {"starts_at": UTC_START, "ends_at": "2026-11-23T23:00:00Z", "is_break": False},
        {"starts_at": "2026-11-23T23:00:00Z", "ends_at": "2026-11-23T23:30:00Z", "is_break": True},
        {"starts_at": "2026-11-23T23:30:00Z", "ends_at": "2026-11-24T03:00:00Z", "is_break": False},
    ]
    assert [(item["starts_at"], item["ends_at"], item["status"]) for item in first["activity"]] == [
        (UTC_START, "2026-11-23T21:01:00Z", "active"),
        ("2026-11-23T21:01:00Z", "2026-11-23T21:02:00Z", "idle"),
        ("2026-11-23T21:02:00Z", "2026-11-23T21:02:01Z", "no_data"),
        ("2026-11-23T21:02:01Z", "2026-11-23T21:03:00Z", "active"),
        ("2026-11-23T21:03:00Z", UTC_END, "no_data"),
    ]
    assert first["activity"][0]["process_name"] == "demo.exe"
    assert first["activity"][0]["window_title"] == "Тестовое окно"
    assert second["schedule"] == []
    assert second["activity"] == [{
        "starts_at": UTC_START, "ends_at": UTC_END, "status": "no_data",
        "process_name": None, "window_title": None,
    }]

    page = cabinet.get(REPORT, params={**filters, "limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and page["rows"] == [second]


@pytest.mark.parametrize(("day", "duration"), [("2026-03-29", 23), ("2026-10-25", 25)])
def test_day_structure_has_exact_local_day_bounds_at_clock_changes(cabinet, day, duration):
    office = create(cabinet, "offices", name="Office", timezone="Europe/Berlin")
    group = create(cabinet, "groups", name="Team", office_id=office["id"])
    response = cabinet.get(REPORT, params={"group_id": group["id"], "day": day})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (datetime.fromisoformat(result["ends_at"]) - datetime.fromisoformat(result["starts_at"])).total_seconds() == 3600 * duration
    assert result["total"] == 0 and result["rows"] == []


def test_day_structure_validates_group_date_and_page(cabinet):
    assert cabinet.get(REPORT, params={"group_id": 999, "day": DAY}).status_code == 404
    group = create(cabinet, "groups", name="Clinic")
    filters = {"group_id": group["id"], "day": DAY}
    for invalid in ({"day": "9999-12-31"}, {"day": "0001-01-01"}, {"limit": 31}, {"offset": -1}):
        assert cabinet.get(REPORT, params={**filters, **invalid}).status_code == 422
