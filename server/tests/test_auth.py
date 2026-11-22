from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME
from app.cli import create_first_admin
from app.db import get_engine
from app.models import CabinetSession, CabinetUser, LoginThrottle, utcnow
from app.security import hash_token

PASSWORD = "test-password-only"
LOGIN = "admin"
AUTH = "/api/v1/auth"


@pytest.fixture
def admin(client, settings):
    assert create_first_admin("Admin", PASSWORD, settings)
    return client


def login(client, name=LOGIN, password=PASSWORD, **kwargs):
    return client.post(f"{AUTH}/login", json={"login": name, "password": password}, **kwargs)


def test_login_me_logout_and_revocation(admin):
    response = login(admin, name=" ADMIN ")
    assert response.status_code == 200
    assert response.json() == {"id": 1, "login": LOGIN, "role": "admin"}
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "path=/api/v1" in cookie
    token = admin.cookies.get(COOKIE_NAME)
    with Session(get_engine()) as db:
        user = db.scalar(select(CabinetUser))
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        assert db.get(CabinetSession, hash_token(token)) is not None
        assert db.get(CabinetSession, token) is None
        assert db.get(LoginThrottle, f"login:{hash_token(LOGIN)}") is None

    response = admin.get(f"{AUTH}/me")
    assert response.status_code == 200
    assert response.json()["login"] == LOGIN
    assert response.headers["cache-control"] == "no-store"
    response = admin.post(f"{AUTH}/logout")
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert admin.get(f"{AUTH}/me").status_code == 401
    assert admin.get(f"{AUTH}/me", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code == 401
    with Session(get_engine()) as db:
        assert db.get(CabinetSession, hash_token(token)) is None


def test_invalid_password_and_unknown_login_same_response(admin):
    wrong = login(admin, password="wrong")
    unknown = login(admin, name="unknown")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid login or password"}
    assert COOKIE_NAME not in wrong.cookies and COOKIE_NAME not in unknown.cookies
    assert admin.get(f"{AUTH}/me").status_code == 401


def test_account_throttling_and_recovery(admin, settings):
    for _ in range(settings.auth_login_attempt_limit):
        assert login(admin, name="ADMIN", password="wrong").status_code == 401
    limited = login(admin)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    with Session(get_engine()) as db:
        db.execute(update(LoginThrottle).values(window_ends_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert login(admin).status_code == 200


def test_ip_throttling_across_accounts(client, settings):
    settings.auth_ip_attempt_limit = 3
    for i in range(3):
        assert login(client, name=f"unknown-{i}").status_code == 401
    assert login(client, name="unknown-4").status_code == 429


def test_session_rotation_and_expiry(admin):
    assert login(admin).status_code == 200
    first = admin.cookies.get(COOKIE_NAME)
    assert login(admin).status_code == 200
    second = admin.cookies.get(COOKIE_NAME)
    assert first != second
    with Session(get_engine()) as db:
        assert db.get(CabinetSession, hash_token(first)) is None
        db.execute(update(CabinetSession).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert admin.get(f"{AUTH}/me").status_code == 401


def test_disabled_user_cannot_sign_in_or_use_existing_session(admin):
    assert login(admin).status_code == 200
    with Session(get_engine()) as db:
        db.execute(update(CabinetUser).values(is_active=False))
        db.commit()
    assert admin.get(f"{AUTH}/me").status_code == 401
    assert login(admin).status_code == 401


def test_unauthenticated_and_agent_token_rejected(client, agent):
    assert client.get(f"{AUTH}/me").status_code == 401
    assert client.post(f"{AUTH}/logout").status_code == 401
    assert client.get(f"{AUTH}/me", headers=agent).status_code == 401


def test_cabinet_session_does_not_grant_agent_access(admin):
    assert login(admin).status_code == 200
    assert admin.get("/api/agent/v1/config").status_code == 401


def test_browser_cross_origin_requests_rejected(admin):
    assert login(admin, headers={"Origin": "https://other.example"}).status_code == 403
    assert login(admin, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert login(admin, headers={"Origin": "https://testserver"}).status_code == 200
    assert admin.post(f"{AUTH}/logout", headers={"Origin": "https://other.example"}).status_code == 403
    assert admin.get(f"{AUTH}/me").status_code == 200


def test_https_required_by_default(admin):
    response = admin.post(
        "http://testserver/api/v1/auth/login", json={"login": LOGIN, "password": PASSWORD},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "HTTPS required"


def test_validation_does_not_echo_password(client):
    response = client.post(f"{AUTH}/login", json={"password": PASSWORD})
    assert response.status_code == 422
    assert PASSWORD not in response.text


def test_create_admin_command(client, settings, monkeypatch):
    import app.cli as cli

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["app.cli", "create-admin", "--login", "First"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: PASSWORD)
    assert cli.main() == 0
    assert cli.main() == 1
    assert login(client, name="first").status_code == 200
    assert not create_first_admin("other", PASSWORD, settings)


def test_admin_requires_strong_enough_password(client, settings):
    with pytest.raises(ValueError):
        create_first_admin("admin", "short", settings)


def test_auth_migration_preserves_existing_data(settings):
    from sqlalchemy import create_engine, inspect, text

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    engine = create_engine(settings.database_url)
    try:
        command.upgrade(config, "0001")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO offices (name, timezone) VALUES ('Old', 'Europe/Moscow')"))
        command.upgrade(config, "head")
        assert "cabinet_users" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT name FROM offices")).scalar_one() == "Old"
        command.check(config)
        command.downgrade(config, "0001")
        assert "cabinet_users" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT name FROM offices")).scalar_one() == "Old"
    finally:
        engine.dispose()
