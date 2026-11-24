from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app import models  # noqa: F401
from app.db import Base


def test_initial_migration_matches_models(settings):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    engine = create_engine(settings.database_url)
    try:
        assert inspect(engine).get_table_names() == []
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) == {
            *Base.metadata.tables, "alembic_version"
        }
        # Uses the same autogeneration comparison as 'alembic check'.
        command.check(config)

        # Repeated startup must not recreate tables or lose data.
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO offices (name, timezone) VALUES ('Test', 'Europe/Moscow')"
            ))
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT name FROM offices")).scalar_one() == "Test"

        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        command.check(config)
    finally:
        engine.dispose()


def test_directory_migration_preserves_positions_and_login_links(settings):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    engine = create_engine(settings.database_url)
    try:
        command.upgrade(config, "0002")
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO employees (id, full_name, position, is_dismissed) VALUES "
                "(1, 'One', 'Терапевт', false), (2, 'Two', 'Терапевт', true), "
                "(3, 'Three', NULL, false), (4, 'Four', 'Медсестра', false)"
            ))
            connection.execute(text("INSERT INTO employee_logins (employee_id, login) VALUES (2, 'test-login')"))
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM positions")).scalar_one() == 2
            assert connection.execute(text(
                "SELECT employees.id, positions.name, employees.is_dismissed FROM employees "
                "LEFT JOIN positions ON positions.id = employees.position_id ORDER BY employees.id"
            )).all() == [(1, "Терапевт", False), (2, "Терапевт", True), (3, None, False), (4, "Медсестра", False)]
            assert connection.execute(text("SELECT employee_id, login FROM employee_logins")).one() == (2, "test-login")

        command.downgrade(config, "0002")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT position FROM employees ORDER BY id")).scalars().all() == [
                "Терапевт", "Терапевт", None, "Медсестра",
            ]
            assert connection.execute(text("SELECT employee_id, login FROM employee_logins")).one() == (2, "test-login")
    finally:
        engine.dispose()


def test_observed_login_migration_backfills_history_and_normalizes_bindings(settings):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    engine = create_engine(settings.database_url)
    try:
        command.upgrade(config, "0003")
        with engine.begin() as db:
            db.execute(text("INSERT INTO employees (id, full_name, is_dismissed) VALUES (1, 'One', false)"))
            db.execute(text(
                "INSERT INTO employee_logins (id, employee_id, login) VALUES (1, 1, :original), (2, 1, :lower)"
            ), {"original": r"CLINIC\Иванов", "lower": r"clinic\иванов"})
            db.execute(text(
                "INSERT INTO computers (id, machine_id, hostname, token_hash, created_at) VALUES "
                "(1, 'machine-a', 'PC-A', 'one', '2026-11-20 08:00:00'), "
                "(2, 'machine-b', 'PC-B', 'two', '2026-11-20 08:00:00')"
            ))
            db.execute(text(
                "INSERT INTO activity_spans (computer_id, client_id, login, session_id, started_at, ended_at, is_idle) "
                "VALUES (1, 'span', :login, 0, '2026-11-20 09:00:00', '2026-11-20 10:00:00', false)"
            ), {"login": r"CLINIC\Иванов"})
            db.execute(text(
                "INSERT INTO system_events (computer_id, client_id, login, occurred_at, kind) "
                "VALUES (1, 'event', :login, '2026-11-20 08:00:00', 'logon'), "
                "(2, 'blank', NULL, '2026-11-20 07:00:00', 'agent_start')"
            ), {"login": r"clinic\иванов"})
            db.execute(text(
                "INSERT INTO screenshots (computer_id, client_id, login, taken_at, monitor, file_path, content_type, size_bytes) "
                "VALUES (2, 'shot', :login, '2026-11-20 11:00:00', 0, 'shot.jpg', 'image/jpeg', 1)"
            ), {"login": r"CLINIC\ИВАНОВ"})

        command.upgrade(config, "head")
        with engine.connect() as db:
            assert db.execute(text("SELECT id, login, login_key FROM employee_logins")).one() == (
                1, r"CLINIC\Иванов", r"clinic\иванов",
            )
            login, first, last, computer_id = db.execute(text(
                "SELECT login_key, first_seen_at, last_seen_at, last_computer_id FROM observed_logins"
            )).one()
            assert (login, computer_id) == (r"clinic\иванов", 2)
            assert first.startswith("2026-11-20 08:00:00")
            assert last.startswith("2026-11-20 11:00:00")
            assert db.execute(text("SELECT login FROM activity_spans")).scalar_one() == r"CLINIC\Иванов"

        command.downgrade(config, "0003")
        with engine.connect() as db:
            assert db.execute(text("SELECT id, login FROM employee_logins")).one() == (1, r"CLINIC\Иванов")
            assert "observed_logins" not in inspect(db).get_table_names()
        command.upgrade(config, "head")
        command.check(config)
    finally:
        engine.dispose()


def test_observed_login_migration_refuses_ambiguous_bindings(settings):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    engine = create_engine(settings.database_url)
    try:
        command.upgrade(config, "0003")
        with engine.begin() as db:
            db.execute(text("INSERT INTO employees (id, full_name, is_dismissed) VALUES (1, 'One', false), (2, 'Two', false)"))
            db.execute(text("INSERT INTO employee_logins (id, employee_id, login) VALUES (1, 1, 'ABC'), (2, 2, 'abc')"))
        with pytest.raises(RuntimeError, match="bindings 1 and 2 match ignoring case"):
            command.upgrade(config, "head")
        with engine.connect() as db:
            assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0003"
            assert db.execute(text("SELECT employee_id FROM employee_logins ORDER BY id")).scalars().all() == [1, 2]
            assert "observed_logins" not in inspect(db).get_table_names()
    finally:
        engine.dispose()
