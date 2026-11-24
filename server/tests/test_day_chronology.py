from datetime import datetime, timedelta, timezone
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from sqlalchemy import insert, update
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import ActivitySpan, Office

from .test_directories import cabinet, create

API = "/api/v1/reports/day-chronology"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def bind(cabinet, employee, login):
    create(cabinet, f"employees/{employee['id']}/logins", login=login)


def span(client_id, started_at, ended_at, **fields):
    return {
        "id": client_id, "started_at": started_at, "ended_at": ended_at,
        "login": r"CLINIC\Staff", **fields,
    }


def upload(cabinet, agent, spans):
    response = cabinet.post("/api/agent/v1/activity", headers=agent, json={"spans": spans})
    assert response.status_code == 200, response.text
    assert response.json()["accepted_spans"] == len(spans)


@pytest.mark.parametrize("endpoint", ["query", "export"])
def test_chronology_requires_cabinet_session(client, agent, endpoint):
    for headers in ({}, agent):
        response = client.post(f"{API}/{endpoint}", json={"employee_id": 1, "day": "2026-03-29"}, headers=headers)
        assert response.status_code == 401


def test_chronology_local_day_paging_and_filters(cabinet, agent):
    office = create(cabinet, "offices", name="Office", timezone="Europe/Berlin")
    group = create(cabinet, "groups", name="Team", office_id=office["id"])
    employee = create(cabinet, "employees", full_name="Test Employee", group_id=group["id"])
    bind(cabinet, employee, r"clinic\straße")
    bind(cabinet, employee, r"clinic\second")
    upload(cabinet, agent, [
        span("before", "2026-03-28T22:55:00Z", "2026-03-28T23:00:00Z", login=r"CLINIC\Straße"),
        span("straddle", "2026-03-28T22:59:30Z", "2026-03-28T23:00:15Z", login=r"clinic\STRASSE",
             process_name="editor.exe", window_title="ОТЧЁТ А_50%", url="https://report.invalid"),
        span("next", "2026-03-29T21:59:30Z", "2026-03-29T22:00:20Z", login=r"CLINIC\Second",
             process_name="reader.exe", window_title="Отчёт АX50Y", is_idle=True),
        span("wrong employee", "2026-03-29T10:00:00Z", "2026-03-29T10:01:00Z",
             process_name="other.exe"),
        span("after", "2026-03-29T22:00:00Z", "2026-03-29T22:01:00Z", login=r"CLINIC\Straße"),
    ])
    filters = {"employee_id": employee["id"], "day": "2026-03-29"}
    response = cabinet.post(f"{API}/query", json={**filters, "limit": 1})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    page = response.json()
    assert (page["timezone"], page["total"], page["limit"], page["offset"]) == ("Europe/Berlin", 2, 1, 0)
    assert page["programs"] == ["editor.exe", "reader.exe"]
    assert page["items"] == [{
        "id": page["items"][0]["id"],
        "started_at": "2026-03-28T23:00:00Z",
        "ended_at": "2026-03-28T23:00:15Z",
        "duration_seconds": 15,
        "process_name": "editor.exe",
        "window_title": "ОТЧЁТ А_50%",
        "url": "https://report.invalid",
        "is_idle": False,
    }]

    page2 = cabinet.post(f"{API}/query", json={**filters, "limit": 1, "offset": 1}).json()
    assert page2["items"][0]["ended_at"] == "2026-03-29T22:00:00Z"
    assert page2["items"][0]["duration_seconds"] == 30 and page2["items"][0]["is_idle"] is True
    assert cabinet.post(f"{API}/query", json={**filters, "title": "а_50%"}).json()["total"] == 1
    assert cabinet.post(f"{API}/query", json={**filters, "title": "а_50%", "program": "reader.exe"}).json()["total"] == 0
    assert cabinet.post(f"{API}/query", json={**filters, "program": "reader.exe"}).json()["items"] == page2["items"]


def test_chronology_timezone_fallback_and_validation(cabinet):
    office = create(cabinet, "offices", name="Office")
    with Session(get_engine()) as db:
        db.execute(update(Office).where(Office.id == office["id"]).values(timezone="Not/An_Office"))
        db.commit()
    group = create(cabinet, "groups", name="Team", office_id=office["id"])
    for group_id in (None, group["id"]):
        employee = create(cabinet, "employees", full_name="Test Employee", group_id=group_id)
        filters = {"employee_id": employee["id"], "day": "2026-03-29"}
        assert cabinet.post(f"{API}/query", json=filters).json() == {
            "items": [], "total": 0, "limit": 50, "offset": 0, "programs": [], "timezone": "Europe/Moscow",
        }
        for invalid in ({"day": "9999-12-31"}, {"day": "0001-01-01"}, {"limit": 201}, {"offset": -1}, {"title": "\0"}):
            assert cabinet.post(f"{API}/query", json={**filters, **invalid}).status_code == 422
    assert cabinet.post(f"{API}/query", json={**filters, "employee_id": 9999}).status_code == 404


def test_chronology_keeps_long_and_zero_length_spans(cabinet, agent):
    employee = create(cabinet, "employees", full_name="Test Employee")
    bind(cabinet, employee, r"clinic\staff")
    upload(cabinet, agent, [
        span("long", "2026-11-01T00:00:00Z", "2026-11-24T06:00:00Z", process_name="long.exe"),
        span("point", "2026-11-23T21:00:00Z", "2026-11-23T21:00:00Z", process_name="point.exe"),
        span("ends-at-start", "2026-11-23T20:59:00Z", "2026-11-23T21:00:00Z", process_name="before.exe"),
        span("point-at-end", "2026-11-24T21:00:00Z", "2026-11-24T21:00:00Z", process_name="after.exe"),
    ])
    response = cabinet.post(f"{API}/query", json={"employee_id": employee["id"], "day": "2026-11-24"})
    assert response.status_code == 200, response.text
    assert [(item["process_name"], item["duration_seconds"]) for item in response.json()["items"]] == [
        ("long.exe", 9 * 60 * 60), ("point.exe", 0),
    ]


def test_chronology_xlsx_exports_filtered_rows_as_literals(cabinet, agent):
    employee = create(cabinet, "employees", full_name="Test Employee")
    bind(cabinet, employee, r"clinic\staff")
    upload(cabinet, agent, [
        span("kept", "2026-11-24T12:00:00Z", "2026-11-24T12:00:15Z",
             process_name="editor.exe", window_title="{=1+1}", url="https://report.invalid"),
        span("removed", "2026-11-24T12:01:00Z", "2026-11-24T12:01:30Z",
             process_name="reader.exe", window_title="not exported"),
    ])

    response = cabinet.post(f"{API}/export", json={
        "employee_id": employee["id"], "day": "2026-11-24", "program": "editor.exe",
    })
    assert response.status_code == 200, response.text if response.status_code != 200 else ""
    assert response.headers["content-type"] == XLSX
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == 'attachment; filename="day-chronology-2026-11-24.xlsx"'
    with ZipFile(BytesIO(response.content)) as xlsx:
        assert xlsx.testzip() is None
        assert "xl/worksheets/_rels/sheet1.xml.rels" not in xlsx.namelist()
        sheet = ElementTree.fromstring(xlsx.read("xl/worksheets/sheet1.xml"))
        assert len(sheet.findall(".//{*}row")) == 2
        assert sheet.find(".//{*}f") is None
        assert sheet.find(".//{*}c[@r='C2']/{*}v").text == "15"
        shared = xlsx.read("xl/sharedStrings.xml").decode()
        assert "{=1+1}" in shared and "https://report.invalid" in shared
        assert "not exported" not in shared


def test_chronology_paginates_and_exports_ten_thousand_spans(cabinet, agent):
    employee = create(cabinet, "employees", full_name="Test Employee")
    bind(cabinet, employee, r"clinic\staff")
    computer = cabinet.get("/api/v1/computers").json()["items"][0]
    base = datetime(2026, 11, 24, 10, tzinfo=timezone.utc)
    with Session(get_engine()) as db:
        db.execute(insert(ActivitySpan), [
            {
                "computer_id": computer["id"], "client_id": str(index), "login": r"CLINIC\STAFF",
                "started_at": base + timedelta(seconds=index),
                "ended_at": base + timedelta(seconds=index + 1),
                "process_name": "editor.exe", "window_title": f"Синтетический документ {index}",
            }
            for index in range(10_000)
        ])
        db.commit()
    filters = {"employee_id": employee["id"], "day": "2026-11-24"}
    page = cabinet.post(f"{API}/query", json={**filters, "limit": 50}).json()
    final_page = cabinet.post(f"{API}/query", json={**filters, "limit": 50, "offset": 9_950}).json()
    assert len(page["items"]) == len(final_page["items"]) == 50
    assert page["total"] == final_page["total"] == 10_000
    assert final_page["items"][-1]["window_title"] == "Синтетический документ 9999"

    response = cabinet.post(f"{API}/export", json=filters)
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as xlsx:
        sheet = ElementTree.fromstring(xlsx.read("xl/worksheets/sheet1.xml"))
        assert len(sheet.findall(".//{*}row")) == 10_001
        assert sheet.find("{*}autoFilter").get("ref") == "A1:G10001"
