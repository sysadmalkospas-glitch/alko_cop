from collections.abc import Iterable
from datetime import datetime
from typing import TypedDict

from sqlalchemy import case, or_
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import ObservedLogin, as_utc


class Observation(TypedDict):
    login_key: str
    login: str
    first_seen_at: datetime
    last_seen_at: datetime
    last_computer_id: int


def record_observed_logins(
    db: Session,
    computer_id: int,
    sightings: Iterable[tuple[str | None, datetime, datetime]],
) -> None:
    observations: dict[str, Observation] = {}
    for login, first_seen, last_seen in sightings:
        if login is None or not login.strip():
            continue
        key = login.casefold()
        first_seen, last_seen = as_utc(first_seen), as_utc(last_seen)
        if key in observations:
            row = observations[key]
            row["first_seen_at"] = min(row["first_seen_at"], first_seen)
            row["last_seen_at"] = max(row["last_seen_at"], last_seen)
        else:
            observations[key] = Observation(
                login_key=key,
                login=login,
                first_seen_at=first_seen,
                last_seen_at=last_seen,
                last_computer_id=computer_id,
            )
    if not observations:
        return

    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert
    table = ObservedLogin.__table__
    statement = insert(table)
    current, incoming = table.c, statement.excluded
    earlier = incoming.first_seen_at < current.first_seen_at
    latest = or_(
        incoming.last_seen_at > current.last_seen_at,
        (incoming.last_seen_at == current.last_seen_at) & or_(
            current.last_computer_id.is_(None), incoming.last_computer_id > current.last_computer_id,
        ),
    )
    statement = statement.on_conflict_do_update(
        index_elements=[current.login_key],
        set_={
            "first_seen_at": case((earlier, incoming.first_seen_at), else_=current.first_seen_at),
            "last_seen_at": case((latest, incoming.last_seen_at), else_=current.last_seen_at),
            "last_computer_id": case((latest, incoming.last_computer_id), else_=current.last_computer_id),
        },
        where=or_(earlier, latest),
    )
    # Concurrent batches acquire observation locks in the same order.
    db.execute(statement, [observations[key] for key in sorted(observations)])
