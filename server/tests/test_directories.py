from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.cli import create_first_admin
from app.db import get_engine
from app.models import MonitoringProfile

from .conftest import ENROLL_KEY

API = "/api/v1"


@pytest.fixture
def cabinet(client, settings):
    password = "test-password-only"
    assert create_first_admin("admin", password, settings)
    response = client.post(f"{API}/auth/login", json={"login": "admin", "password": password})
    assert response.status_code == 200
    return client


def create(cabinet, path, **payload):
    response = cabinet.post(f"{API}/{path}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "offices"), ("GET", "offices/1"), ("PATCH", "offices/1"), ("DELETE", "offices/1"),
    ("GET", "groups"), ("GET", "positions"), ("GET", "employees"),
    ("GET", "employees/1/logins"), ("POST", "employees/1/logins"),
    ("DELETE", "employees/1/logins/1"), ("GET", "logins/unknown"),
    ("GET", "computers"), ("PATCH", "computers/1"),
])
def test_directories_require_cabinet_session(client, agent, method, path):
    for headers in ({}, agent):
        response = client.request(method, f"{API}/{path}", json={}, headers=headers)
        assert response.status_code == 401


def test_directory_rejects_cross_origin_mutation(cabinet):
    response = cabinet.post(
        f"{API}/offices", json={"name": "Тест"}, headers={"Origin": "https://other.example"},
    )
    assert response.status_code == 403
    assert cabinet.get(f"{API}/offices").json()["total"] == 0


@pytest.mark.parametrize("resource", ["offices", "groups", "positions"])
def test_named_directory_crud_and_pagination(cabinet, resource):
    first = create(cabinet, resource, name="Север 01")
    second = create(cabinet, resource, name="Север 02")
    create(cabinet, resource, name="Юг")
    path = f"{API}/{resource}/{first['id']}"
    assert cabinet.get(path).json() == first

    page = cabinet.get(f"{API}/{resource}", params={"q": "СЕВЕР", "limit": 1, "offset": 1})
    assert page.json() == {"items": [second], "total": 2, "limit": 1, "offset": 1}
    assert cabinet.get(f"{API}/{resource}", params={"q": "%"}).json()["total"] == 0
    assert cabinet.get(f"{API}/{resource}", params={"limit": 201}).status_code == 422
    assert cabinet.patch(path, json={"name": None}).status_code == 422
    assert cabinet.patch(path, json={"name": "  Север 03 "}).json()["name"] == "Север 03"
    assert cabinet.delete(path).status_code == 204
    assert cabinet.get(path).status_code == 404


def test_employee_assignments_and_dismissal(cabinet):
    with Session(get_engine()) as db:
        profile = MonitoringProfile(name="Пилот")
        db.add(profile)
        db.commit()
        profile_id = profile.id

    office = create(cabinet, "offices", name="Север")
    group = create(cabinet, "groups", name="Приём", office_id=office["id"], profile_id=profile_id)
    assert (group["office_id"], group["profile_id"]) == (office["id"], profile_id)
    position = create(cabinet, "positions", name="Терапевт")
    employee = create(cabinet, "employees", full_name="Иван Тестов", group_id=group["id"], position_id=position["id"])
    path = f"{API}/employees/{employee['id']}"
    assert cabinet.get(path).json() == employee
    assert cabinet.get(f"{API}/employees/9223372036854775808").status_code == 422
    assert cabinet.patch(path, json={"group_id": 9223372036854775808}).status_code == 422
    assert cabinet.post(f"{API}/offices", json={"name": office["name"]}).status_code == 409
    assert cabinet.patch(path, json={"group_id": 999}).status_code == 409
    for resource, record in [("offices", office), ("groups", group), ("positions", position)]:
        assert cabinet.delete(f"{API}/{resource}/{record['id']}").status_code == 409

    assert cabinet.delete(path).status_code == 204
    assert cabinet.delete(path).status_code == 204
    assert cabinet.get(path).json()["is_dismissed"] is True
    assert cabinet.get(f"{API}/employees", params={"is_dismissed": False}).json()["total"] == 0
    dismissed = cabinet.get(f"{API}/employees", params={"is_dismissed": True, "q": "ТЕСТОВ"}).json()
    assert [item["id"] for item in dismissed["items"]] == [employee["id"]]

    updated = cabinet.patch(path, json={"is_dismissed": False, "position_id": None}).json()
    assert updated["is_dismissed"] is False
    assert updated["position_id"] is None
    assert updated["group_id"] == group["id"]
    assert cabinet.delete(f"{API}/positions/{position['id']}").status_code == 204


def test_unknown_logins_and_employee_binding(cabinet, agent):
    span_login = r"CLINIC\User_01"
    event_login = r"CLINIC\User_02"
    screenshot_login = r"PC-1\Local"
    now = datetime.now(timezone.utc).isoformat()
    response = cabinet.post("/api/agent/v1/activity", headers=agent, json={
        "spans": [{"id": "a", "login": span_login, "started_at": now, "ended_at": now}],
        "events": [
            {"id": "b", "login": span_login, "occurred_at": now, "kind": "logon"},
            {"id": "c", "login": event_login, "occurred_at": now, "kind": "logon"},
            {"id": "d", "occurred_at": now, "kind": "agent_start"},
        ],
    })
    assert response.status_code == 200, response.text
    response = cabinet.post(
        "/api/agent/v1/screenshots", headers=agent,
        data={"id": "shot-1", "login": screenshot_login, "taken_at": now},
        files={"file": ("shot.jpg", b"image-bytes", "image/jpeg")},
    )
    assert response.status_code == 201, response.text

    unknown = f"{API}/logins/unknown"
    assert cabinet.get(unknown).json()["items"] == [
        {"login": span_login}, {"login": event_login}, {"login": screenshot_login},
    ]
    assert cabinet.get(unknown, params={"q": "USER_", "limit": 1, "offset": 1}).json() == {
        "items": [{"login": event_login}], "total": 2, "limit": 1, "offset": 1,
    }
    first = create(cabinet, "employees", full_name="Первый")
    second = create(cabinet, "employees", full_name="Второй")
    first_logins = f"employees/{first['id']}/logins"
    second_logins = f"{API}/employees/{second['id']}/logins"
    binding = create(cabinet, first_logins, login=span_login)
    assert cabinet.get(f"{API}/{first_logins}").json()["items"] == [binding]
    assert cabinet.post(second_logins, json={"login": span_login}).status_code == 409
    assert cabinet.delete(f"{second_logins}/{binding['id']}").status_code == 404
    assert cabinet.get(unknown).json()["items"] == [{"login": event_login}, {"login": screenshot_login}]
    assert cabinet.delete(f"{API}/employees/{first['id']}").status_code == 204
    assert cabinet.get(f"{API}/{first_logins}").json()["items"] == [binding]
    assert cabinet.delete(f"{API}/{first_logins}/{binding['id']}").status_code == 204
    assert cabinet.get(unknown).json()["items"][0] == {"login": span_login}


def test_computer_name_and_assignments_survive_agent_enrollment(cabinet):
    with Session(get_engine()) as db:
        profile = MonitoringProfile(name="Кабинет", idle_threshold_sec=123)
        db.add(profile)
        db.commit()
        profile_id = profile.id

    def enroll(hostname, version):
        response = cabinet.post("/api/agent/v1/enroll", json={
            "enroll_key": ENROLL_KEY, "machine_id": "machine-0001",
            "hostname": hostname, "agent_version": version,
        })
        assert response.status_code == 200, response.text
        return response.json()

    office = create(cabinet, "offices", name="Север")
    computer_id = enroll("PC-1", "1.0")["computer_id"]
    path = f"{API}/computers/{computer_id}"
    assert cabinet.get(path).json()["name"] == "PC-1"
    response = cabinet.patch(path, json={"name": "Кабинет 4", "office_id": office["id"], "profile_id": profile_id})
    assert response.status_code == 200, response.text
    enrollment = enroll("PC-2", "1.1")
    assert enrollment["computer_id"] == computer_id
    assert cabinet.get("/api/agent/v1/config", headers={
        "Authorization": f"Bearer {enrollment['token']}",
    }).json()["idle_threshold_sec"] == 123

    computer = cabinet.get(path).json()
    assert computer == {
        "id": computer_id, "hostname": "PC-2", "name": "Кабинет 4", "os_version": None,
        "office_id": office["id"], "profile_id": profile_id, "agent_version": "1.1",
        "last_seen_at": computer["last_seen_at"],
    }
    assert cabinet.get(f"{API}/computers", params={"q": "КАБИНЕТ"}).json()["items"] == [computer]
    assert datetime.fromisoformat(computer["last_seen_at"]).utcoffset() is not None
    updated = cabinet.patch(path, json={"name": None, "office_id": None, "profile_id": None}).json()
    assert updated["name"] == "PC-2"
    assert updated["office_id"] is None and updated["profile_id"] is None
