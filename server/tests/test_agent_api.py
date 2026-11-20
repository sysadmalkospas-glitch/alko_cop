from tests.conftest import ENROLL_KEY

SPAN = {
    "id": "span-1",
    "login": "CLINIC\\ivanova",
    "session_id": 2,
    "started_at": "2026-11-20T07:00:00Z",
    "ended_at": "2026-11-20T07:05:00Z",
    "process_name": "chrome.exe",
    "window_title": "Яндекс",
}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_enroll_rejects_wrong_key(client):
    resp = client.post(
        "/api/agent/v1/enroll",
        json={"enroll_key": "wrong", "machine_id": "machine-0001", "hostname": "PC-1"},
    )
    assert resp.status_code == 403


def test_reenroll_keeps_computer_and_rotates_token(client, agent):
    resp = client.post(
        "/api/agent/v1/enroll",
        json={"enroll_key": ENROLL_KEY, "machine_id": "machine-0001", "hostname": "PC-1-renamed"},
    )
    assert resp.json()["computer_id"] == 1
    # Старый токен больше не действует.
    assert client.get("/api/agent/v1/config", headers=agent).status_code == 401


def test_requires_token(client):
    assert client.get("/api/agent/v1/config").status_code == 401
    assert client.get("/api/agent/v1/config", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_default_config(client, agent):
    cfg = client.get("/api/agent/v1/config", headers=agent).json()
    assert cfg["screenshot_interval_sec"] == 5
    assert cfg["screenshot_format"] == "webp"


def test_activity_upload_is_idempotent(client, agent):
    batch = {
        "spans": [SPAN, {**SPAN, "id": "span-2", "is_idle": True}],
        "events": [{"id": "ev-1", "occurred_at": "2026-11-20T07:00:00Z", "kind": "logon"}],
    }
    first = client.post("/api/agent/v1/activity", json=batch, headers=agent)
    assert first.json() == {"accepted_spans": 2, "accepted_events": 1}
    again = client.post("/api/agent/v1/activity", json=batch, headers=agent)
    assert again.json() == {"accepted_spans": 0, "accepted_events": 0}


def test_activity_rejects_inverted_span(client, agent):
    bad = {**SPAN, "ended_at": "2026-11-20T06:00:00Z"}
    resp = client.post("/api/agent/v1/activity", json={"spans": [bad]}, headers=agent)
    assert resp.status_code == 422


def _shot(client, headers, shot_id="shot-1", content=b"RIFF....WEBP", ctype="image/webp"):
    return client.post(
        "/api/agent/v1/screenshots",
        headers=headers,
        data={"id": shot_id, "login": "CLINIC\\ivanova", "taken_at": "2026-11-20T07:00:05Z"},
        files={"file": ("s.webp", content, ctype)},
    )


def test_screenshot_upload_and_duplicate(client, agent, settings):
    resp = _shot(client, agent)
    assert resp.status_code == 201
    assert resp.json()["duplicate"] is False
    assert (settings.screenshot_dir / "1" / "2026-11-20" / "shot-1.webp").read_bytes() == b"RIFF....WEBP"
    assert _shot(client, agent).json()["duplicate"] is True


def test_screenshot_validation(client, agent):
    assert _shot(client, agent, shot_id="../evil").status_code == 422
    assert _shot(client, agent, ctype="image/png").status_code == 415
    assert _shot(client, agent, content=b"x" * 2048).status_code == 413
