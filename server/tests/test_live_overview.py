from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import agent as agent_api, agent_heartbeat, live_overview
from app.db import get_engine
from app.models import ComputerHeartbeat

from .conftest import ENROLL_KEY
from .test_directories import cabinet, create  # noqa: F401 - reuse cabinet fixture

HEARTBEAT = "/api/agent/v1/heartbeat"
OVERVIEW = "/api/v1/reports/live-overview"
START = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
SAMPLE = {
    "login": "OFFICE\\ИВАНОВ",
    "process_name": "editor.exe",
    "window_title": "Тестовый документ",
    "idle_for_seconds": 25,
    "sample_age_seconds": 2,
    "is_idle": True,
}


@pytest.fixture
def clock(monkeypatch):
    current = [START]
    for module in (agent_api, agent_heartbeat, live_overview):
        monkeypatch.setattr(module, "utcnow", lambda: current[0])
    return current


def enroll(client, name="Test Workstation", machine_id="test-machine-01"):
    response = client.post("/api/agent/v1/enroll", json={
        "enroll_key": ENROLL_KEY,
        "machine_id": machine_id,
        "hostname": name,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    return result["computer_id"], {"Authorization": "Bearer " + result["token"]}


def send_heartbeat(client, headers, session):
    response = client.post(HEARTBEAT, json={"session": session}, headers=headers)
    assert response.status_code == 204, response.text


def test_heartbeat_and_live_report_require_distinct_auth(client, cabinet):
    client.cookies.clear()
    _, agent = enroll(client)
    assert client.post(HEARTBEAT, json={}).status_code == 401
    assert client.post(HEARTBEAT, json={}, headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.get(OVERVIEW).status_code == 401
    assert client.get(OVERVIEW, headers=agent).status_code == 401

    assert cabinet.post("/api/v1/auth/login", json={"login": "admin", "password": "test-password-only"}).status_code == 200
    assert cabinet.post(HEARTBEAT, json={"session": SAMPLE}).status_code == 401
    assert client.post(HEARTBEAT, json={"session": SAMPLE, "computer_id": 99}, headers=agent).status_code == 422


def test_live_heartbeat_replaces_snapshot_and_filters(cabinet, clock):
    north = create(cabinet, "offices", name="Север")
    south = create(cabinet, "offices", name="Юг")
    group = create(cabinet, "groups", name="Регистратура", office_id=north["id"])
    employee = create(cabinet, "employees", full_name="Тестовый сотрудник", group_id=group["id"])
    create(cabinet, f"employees/{employee['id']}/logins", login="office\\иванов")
    computer_id, agent = enroll(cabinet)
    other_id, other_agent = enroll(cabinet, "Second Workstation", "test-machine-02")
    assert cabinet.patch(f"/api/v1/computers/{computer_id}", json={"office_id": south["id"], "name": "Первый ПК"}).status_code == 200

    send_heartbeat(cabinet, agent, SAMPLE)
    send_heartbeat(cabinet, other_agent, {**SAMPLE, "login": "OFFICE\\other"})
    response = cabinet.get(OVERVIEW, params={"office_id": south["id"], "group_id": group["id"]})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["items"] == [{
        "id": computer_id,
        "name": "Первый ПК",
        "office": {"id": south["id"], "name": "Юг"},
        "online": True,
        "last_seen_at": "2026-11-24T12:00:00Z",
        "session": {
            "login": SAMPLE["login"],
            "employee": {"id": employee["id"], "name": "Тестовый сотрудник"},
            "group": {"id": group["id"], "name": "Регистратура"},
            "process_name": "editor.exe",
            "window_title": "Тестовый документ",
            "sampled_at": "2026-11-24T11:59:58Z",
            "last_input_at": "2026-11-24T11:59:35Z",
            "is_idle": True,
        },
    }]
    assert cabinet.get(OVERVIEW, params={"office_id": north["id"]}).json()["total"] == 0
    assert cabinet.get(OVERVIEW, params={"limit": 1, "offset": 1}).json()["items"][0]["id"] == computer_id
    assert cabinet.get(OVERVIEW).json()["items"][0]["id"] == other_id

    clock[0] += timedelta(seconds=20)
    send_heartbeat(cabinet, agent, {**SAMPLE, "window_title": "Новый тестовый документ", "is_idle": False})
    row = cabinet.get(OVERVIEW, params={"group_id": group["id"]}).json()["items"][0]
    assert row["session"]["window_title"] == "Новый тестовый документ"
    assert row["session"]["is_idle"] is False
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(ComputerHeartbeat)) == 2

    send_heartbeat(cabinet, agent, None)
    row = cabinet.get(OVERVIEW, params={"office_id": south["id"]}).json()["items"][0]
    assert row["session"] is None and row["online"]
    assert cabinet.get(OVERVIEW, params={"group_id": group["id"]}).json()["total"] == 0


def test_stale_heartbeat_hides_title_and_group_without_hiding_computer(cabinet, clock):
    office = create(cabinet, "offices", name="Север")
    group = create(cabinet, "groups", name="Регистратура", office_id=office["id"])
    employee = create(cabinet, "employees", full_name="Тестовый сотрудник", group_id=group["id"])
    create(cabinet, f"employees/{employee['id']}/logins", login=SAMPLE["login"])
    computer, agent = enroll(cabinet)
    send_heartbeat(cabinet, agent, SAMPLE)
    assert cabinet.get(OVERVIEW, params={"office_id": office["id"]}).json()["total"] == 1
    clock[0] += timedelta(seconds=58)
    row = cabinet.get(OVERVIEW).json()["items"][0]
    assert row["id"] == computer
    assert row["online"] and row["session"] is None and row["office"] is None
    assert cabinet.get(OVERVIEW, params={"group_id": group["id"]}).json()["total"] == 0
    clock[0] += timedelta(seconds=2)
    row = cabinet.get(OVERVIEW).json()["items"][0]
    assert not row["online"] and row["session"] is None


@pytest.mark.parametrize("changes", [
    {"window_title": "x" * 1025},
    {"process_name": "x\0x"},
    {"login": " "},
    {"sample_age_seconds": 8},
    {"idle_for_seconds": 1},
])
def test_heartbeat_rejects_invalid_sample(client, changes):
    _, agent = enroll(client)
    assert client.post(HEARTBEAT, json={"session": {**SAMPLE, **changes}}, headers=agent).status_code == 422
