from pathlib import Path

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
