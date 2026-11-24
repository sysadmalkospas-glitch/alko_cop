from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    global _engine, _session_factory
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    if _engine.dialect.name == "sqlite":
        event.listen(_engine, "connect", _configure_sqlite)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _configure_sqlite(connection, _connection_record) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    # SQLite's built-in lower() only handles ASCII, including in name searches.
    connection.create_function("lower", 1, _unicode_lower, deterministic=True)


def _unicode_lower(value: str | None) -> str | None:
    return value.lower() if value is not None else None


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database engine is not initialised")
    return _engine


def get_session() -> Iterator[Session]:
    if _session_factory is None:
        raise RuntimeError("Database engine is not initialised")
    with _session_factory() as session:
        yield session
