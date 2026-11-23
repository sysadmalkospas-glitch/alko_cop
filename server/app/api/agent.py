"""API для агентов на компьютерах сотрудников (версия 1)."""

import re
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_session
from ..models import ActivitySpan, Computer, MonitoringProfile, Screenshot, SystemEvent, utcnow
from ..observed_logins import record_observed_logins
from ..schemas import (
    ActivityBatch,
    AgentConfig,
    BatchResult,
    EnrollRequest,
    EnrollResponse,
)
from ..security import hash_token, new_token, token_matches

router = APIRouter(prefix="/api/agent/v1", tags=["agent"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_IMAGE_TYPES = {"image/webp": "webp", "image/avif": "avif", "image/jpeg": "jpg"}


def current_computer(
    db: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Computer:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing agent token")
    token = authorization.removeprefix("Bearer ").strip()
    computer = db.scalar(select(Computer).where(Computer.token_hash == hash_token(token)))
    if computer is None or not token_matches(token, computer.token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown agent token")
    computer.last_seen_at = utcnow()
    return computer


ComputerDep = Annotated[Computer, Depends(current_computer)]


@router.post("/enroll", response_model=EnrollResponse)
def enroll(req: EnrollRequest, db: SessionDep, settings: SettingsDep) -> EnrollResponse:
    """Регистрация агента. Повторная регистрация той же машины выдаёт новый токен."""
    if not token_matches(req.enroll_key, hash_token(settings.enroll_key)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid enroll key")

    token = new_token()
    computer = db.scalar(select(Computer).where(Computer.machine_id == req.machine_id))
    if computer is None:
        computer = Computer(machine_id=req.machine_id, hostname=req.hostname, token_hash="")
        db.add(computer)
    computer.hostname = req.hostname
    computer.os_version = req.os_version
    computer.agent_version = req.agent_version
    computer.token_hash = hash_token(token)
    computer.last_seen_at = utcnow()
    db.commit()
    return EnrollResponse(computer_id=computer.id, token=token)


@router.get("/config", response_model=AgentConfig)
def get_config(computer: ComputerDep, db: SessionDep) -> AgentConfig:
    profile = None
    if computer.profile_id is not None:
        profile = db.get(MonitoringProfile, computer.profile_id)
    if profile is None:
        profile = db.scalar(select(MonitoringProfile).where(MonitoringProfile.is_default.is_(True)))
    db.commit()
    if profile is None:
        profile = MonitoringProfile(
            idle_threshold_sec=300,
            screenshots_enabled=True,
            screenshot_interval_sec=5,
            screenshot_quality=75,
            screenshot_format="webp",
            screenshot_max_width=0,
            screenshot_skip_unchanged=True,
        )
    return AgentConfig(
        idle_threshold_sec=profile.idle_threshold_sec,
        screenshots_enabled=profile.screenshots_enabled,
        screenshot_interval_sec=profile.screenshot_interval_sec,
        screenshot_quality=profile.screenshot_quality,
        screenshot_format=profile.screenshot_format,
        screenshot_max_width=profile.screenshot_max_width,
        screenshot_skip_unchanged=profile.screenshot_skip_unchanged,
    )


def _existing_ids(db: Session, model, computer_id: int, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    rows = db.scalars(
        select(model.client_id).where(model.computer_id == computer_id, model.client_id.in_(ids))
    )
    return set(rows)


@router.post("/activity", response_model=BatchResult)
def upload_activity(batch: ActivityBatch, computer: ComputerDep, db: SessionDep) -> BatchResult:
    """Приём пачки отрезков активности и системных событий.

    Отправка идемпотентна: записи с уже известным id пропускаются, поэтому агент
    может безопасно повторить отправку после обрыва связи.
    """
    span_ids = list(dict.fromkeys(s.id for s in batch.spans))
    event_ids = list(dict.fromkeys(e.id for e in batch.events))
    known_spans = _existing_ids(db, ActivitySpan, computer.id, span_ids)
    known_events = _existing_ids(db, SystemEvent, computer.id, event_ids)

    new_spans = {}
    for s in batch.spans:
        if s.id in known_spans or s.id in new_spans:
            continue
        new_spans[s.id] = ActivitySpan(
            computer_id=computer.id,
            client_id=s.id,
            login=s.login,
            session_id=s.session_id,
            started_at=s.started_at,
            ended_at=s.ended_at,
            is_idle=s.is_idle,
            process_name=s.process_name,
            window_title=s.window_title,
            url=s.url,
        )
    new_events = {}
    for e in batch.events:
        if e.id in known_events or e.id in new_events:
            continue
        new_events[e.id] = SystemEvent(
            computer_id=computer.id,
            client_id=e.id,
            login=e.login,
            occurred_at=e.occurred_at,
            kind=e.kind,
        )

    db.add_all(new_spans.values())
    db.add_all(new_events.values())
    try:
        db.flush()
        record_observed_logins(db, computer.id, chain(
            ((span.login, span.started_at, span.ended_at) for span in new_spans.values()),
            ((event.login, event.occurred_at, event.occurred_at) for event in new_events.values()),
        ))
        db.commit()
    except IntegrityError:
        # Параллельная отправка той же пачки: агент повторит, дубли отсеются.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Concurrent upload, retry")
    return BatchResult(accepted_spans=len(new_spans), accepted_events=len(new_events))


@router.post("/screenshots", status_code=status.HTTP_201_CREATED)
def upload_screenshot(
    computer: ComputerDep,
    db: SessionDep,
    settings: SettingsDep,
    id: Annotated[str, Form()],
    login: Annotated[str, Form(max_length=300)],
    taken_at: Annotated[datetime, Form()],
    file: Annotated[UploadFile, File()],
    monitor: Annotated[int, Form(ge=0, le=16)] = 0,
) -> dict:
    if not _SAFE_ID.match(id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid screenshot id")
    ext = _IMAGE_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported image type")

    existing = db.scalar(
        select(Screenshot).where(Screenshot.computer_id == computer.id, Screenshot.client_id == id)
    )
    if existing is not None:
        db.commit()
        return {"id": existing.id, "duplicate": True}

    data = file.file.read(settings.max_screenshot_bytes + 1)
    if len(data) > settings.max_screenshot_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Screenshot is too large")

    if taken_at.tzinfo is None:
        taken_at = taken_at.replace(tzinfo=timezone.utc)
    rel = Path(str(computer.id)) / taken_at.astimezone(timezone.utc).strftime("%Y-%m-%d") / f"{id}.{ext}"
    target = settings.screenshot_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)

    shot = Screenshot(
        computer_id=computer.id,
        client_id=id,
        login=login,
        taken_at=taken_at,
        monitor=monitor,
        file_path=rel.as_posix(),
        content_type=file.content_type,
        size_bytes=len(data),
    )
    db.add(shot)
    try:
        db.flush()
        record_observed_logins(db, computer.id, [(shot.login, shot.taken_at, shot.taken_at)])
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"duplicate": True}
    return {"id": shot.id, "duplicate": False}
