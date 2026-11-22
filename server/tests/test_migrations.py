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
