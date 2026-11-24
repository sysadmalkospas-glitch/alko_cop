"""Authenticated, nonhistorical live observations from managed computers."""

from datetime import timedelta

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..models import ComputerHeartbeat, utcnow
from .agent import ComputerDep, SessionDep

router = APIRouter(prefix="/api/agent/v1", tags=["agent"])


class LiveSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1, max_length=300)
    process_name: str | None = Field(default=None, max_length=260)
    window_title: str | None = Field(default=None, max_length=1024)
    idle_for_seconds: int = Field(ge=0, le=4_300_000)
    sample_age_seconds: int = Field(ge=0, lt=8)
    is_idle: bool

    @field_validator("login", "process_name", "window_title")
    @classmethod
    def reject_null_character(cls, value: str | None) -> str | None:
        if value is not None and "\0" in value:
            raise ValueError("Invalid text")
        return value

    @model_validator(mode="after")
    def validate_live_sample(self):
        if not self.login.strip() or self.idle_for_seconds < self.sample_age_seconds:
            raise ValueError("Invalid login or sample age")
        return self


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: LiveSessionIn | None = None


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def heartbeat(payload: HeartbeatIn, computer: ComputerDep, db: SessionDep) -> None:
    received_at = utcnow()
    session = payload.session
    values = {
        "received_at": received_at,
        "sampled_at": received_at - timedelta(seconds=session.sample_age_seconds) if session else None,
        "login": session.login if session else None,
        "login_key": session.login.casefold() if session else None,
        "process_name": session.process_name if session else None,
        "window_title": session.window_title if session else None,
        "last_input_at": received_at - timedelta(seconds=session.idle_for_seconds) if session else None,
        "is_idle": session.is_idle if session else None,
    }
    table = ComputerHeartbeat.__table__
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert
    statement = insert(table).values(computer_id=computer.id, **values)
    db.execute(statement.on_conflict_do_update(
        index_elements=[table.c.computer_id],
        set_=values,
        where=statement.excluded.received_at >= table.c.received_at,
    ))
    db.commit()
