from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SystemEventKind = Literal[
    "agent_start",
    "agent_stop",
    "logon",
    "logoff",
    "lock",
    "unlock",
    "shutdown",
    "resume",
    "suspend",
]


class EnrollRequest(BaseModel):
    enroll_key: str
    machine_id: str = Field(min_length=8, max_length=64)
    hostname: str = Field(max_length=255)
    os_version: str | None = Field(default=None, max_length=255)
    agent_version: str | None = Field(default=None, max_length=64)


class EnrollResponse(BaseModel):
    computer_id: int
    token: str


class AgentConfig(BaseModel):
    idle_threshold_sec: int
    screenshots_enabled: bool
    screenshot_interval_sec: int
    screenshot_quality: int
    screenshot_format: str
    screenshot_max_width: int
    screenshot_skip_unchanged: bool
    upload_interval_sec: int = 30


class ActivitySpanIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    login: str = Field(max_length=300)
    session_id: int = 0
    started_at: datetime
    ended_at: datetime
    is_idle: bool = False
    process_name: str | None = Field(default=None, max_length=260)
    window_title: str | None = None
    url: str | None = None

    @field_validator("ended_at")
    @classmethod
    def _not_before_start(cls, v: datetime, info):
        started = info.data.get("started_at")
        if started is not None and v < started:
            raise ValueError("ended_at is before started_at")
        return v


class SystemEventIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    login: str | None = Field(default=None, max_length=300)
    occurred_at: datetime
    kind: SystemEventKind


class ActivityBatch(BaseModel):
    spans: list[ActivitySpanIn] = Field(default_factory=list, max_length=5000)
    events: list[SystemEventIn] = Field(default_factory=list, max_length=5000)


class BatchResult(BaseModel):
    accepted_spans: int
    accepted_events: int
