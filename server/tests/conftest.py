from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

ENROLL_KEY = "test-enroll-key"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        screenshot_dir=tmp_path / "shots",
        enroll_key=ENROLL_KEY,
        max_screenshot_bytes=1024,
    )


@pytest.fixture
def client(settings):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, "head")
    get_settings.cache_clear()
    app.dependency_overrides[get_settings] = lambda: settings
    # lifespan читает get_settings() напрямую, поэтому подменяем и кеш.
    import app.main as main_module

    original = main_module.get_settings
    main_module.get_settings = lambda: settings
    try:
        with TestClient(app, base_url="https://testserver") as c:
            yield c
    finally:
        main_module.get_settings = original
        app.dependency_overrides.clear()


@pytest.fixture
def agent(client):
    resp = client.post(
        "/api/agent/v1/enroll",
        json={"enroll_key": ENROLL_KEY, "machine_id": "machine-0001", "hostname": "PC-1"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
