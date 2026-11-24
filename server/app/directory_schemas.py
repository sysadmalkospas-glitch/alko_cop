from datetime import datetime, timezone
from typing import Annotated, Generic, TypeVar, TypedDict

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, with_config

from .models import as_utc

MAX_DIRECTORY_ID = 2_147_483_647
DirectoryId = Annotated[int, Field(gt=0, le=MAX_DIRECTORY_ID)]
DirectoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
ComputerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
TimezoneName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class DirectoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectoryRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int


class OfficeCreate(DirectoryInput):
    name: DirectoryName
    timezone: TimezoneName = "Europe/Moscow"


@with_config(ConfigDict(extra="forbid"))
class OfficeUpdate(TypedDict, total=False):
    name: DirectoryName
    timezone: TimezoneName


class OfficeOut(DirectoryRecord):
    name: str
    timezone: str


class MonitoringProfileOptionOut(DirectoryRecord):
    name: str
    is_default: bool


class GroupCreate(DirectoryInput):
    name: DirectoryName
    office_id: DirectoryId | None = None
    profile_id: DirectoryId | None = None


@with_config(ConfigDict(extra="forbid"))
class GroupUpdate(TypedDict, total=False):
    name: DirectoryName
    office_id: DirectoryId | None
    profile_id: DirectoryId | None


class GroupOut(DirectoryRecord):
    name: str
    office_id: int | None
    profile_id: int | None


class PositionCreate(DirectoryInput):
    name: DirectoryName


@with_config(ConfigDict(extra="forbid"))
class PositionUpdate(TypedDict, total=False):
    name: DirectoryName


class PositionOut(DirectoryRecord):
    name: str


class EmployeeCreate(DirectoryInput):
    full_name: FullName
    group_id: DirectoryId | None = None
    position_id: DirectoryId | None = None
    is_dismissed: bool = False


@with_config(ConfigDict(extra="forbid"))
class EmployeeUpdate(TypedDict, total=False):
    full_name: FullName
    group_id: DirectoryId | None
    position_id: DirectoryId | None
    is_dismissed: bool


class EmployeeOut(DirectoryRecord):
    full_name: str
    group_id: int | None
    position_id: int | None
    is_dismissed: bool


class EmployeeLoginCreate(DirectoryInput):
    login: Annotated[str, StringConstraints(min_length=1, max_length=300)]

    @field_validator("login")
    @classmethod
    def nonblank_login(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Login must not be blank")
        return value


class EmployeeLoginOut(DirectoryRecord):
    employee_id: int
    login: str


class UnknownLoginOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    login: str
    first_seen_at: datetime
    last_seen_at: datetime
    last_computer_id: int | None

    @field_validator("first_seen_at", "last_seen_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return as_utc(value)


@with_config(ConfigDict(extra="forbid"))
class ComputerUpdate(TypedDict, total=False):
    name: ComputerName | None
    office_id: DirectoryId | None
    profile_id: DirectoryId | None


class ComputerOut(DirectoryRecord):
    name: str
    hostname: str
    os_version: str | None
    office_id: int | None
    profile_id: int | None
    agent_version: str | None
    last_seen_at: datetime | None

    @field_validator("last_seen_at")
    @classmethod
    def restore_sqlite_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
