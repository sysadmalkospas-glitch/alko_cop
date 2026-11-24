from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal, TypedDict

from pydantic import ConfigDict, Field, field_validator, model_validator, with_config

from .directory_schemas import DirectoryId, DirectoryInput, DirectoryName, DirectoryRecord

DAY = timedelta(days=1)
LateTolerance = Annotated[int, Field(ge=0, le=1440)]


def _from_midnight(value: time) -> timedelta:
    return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second, microseconds=value.microsecond)


class Shift(DirectoryInput):
    start: time
    end: time = Field(description="Время окончания. Если оно совпадает с началом, смена длится сутки.")
    break_start: time | None = None
    break_end: time | None = None

    @field_validator("start", "end", "break_start", "break_end")
    @classmethod
    def local_time(cls, value: time | None) -> time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("Shift times must not carry a timezone")
        return value

    def shift_offsets(self) -> tuple[timedelta, timedelta]:
        start, end = _from_midnight(self.start), _from_midnight(self.end)
        return start, end + DAY if end <= start else end

    def break_offsets(self) -> tuple[timedelta, timedelta] | None:
        if self.break_start is None or self.break_end is None:
            return None
        start, end = _from_midnight(self.break_start), _from_midnight(self.break_end)
        if start < _from_midnight(self.start):
            start += DAY
            end += DAY
        return start, end + DAY if end < start else end

    @model_validator(mode="after")
    def valid_break(self) -> "Shift":
        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("Both break times are required")
        if pause := self.break_offsets():
            start, end = self.shift_offsets()
            if not start <= pause[0] < pause[1] <= end or pause == (start, end):
                raise ValueError("Break must be within the shift and shorter than it")
        return self


class WeeklyPattern(DirectoryInput):
    type: Literal["weekly"]
    days: list[Shift | None] = Field(
        min_length=7, max_length=7,
        description="Семь дней с понедельника по воскресенье. null — выходной.",
    )

    def shift_for(self, day: date) -> Shift | None:
        return self.days[day.weekday()]


class RotatingPattern(DirectoryInput):
    type: Literal["rotation"]
    anchor_date: date = Field(description="Дата первого дня цикла в часовом поясе офиса.")
    days: list[Shift | None] = Field(
        min_length=1,
        description="Дни повторяющегося цикла. null — выходной. Цикл действует и до даты отсчёта.",
    )

    def shift_for(self, day: date) -> Shift | None:
        return self.days[(day - self.anchor_date).days % len(self.days)]


WorkPattern = Annotated[WeeklyPattern | RotatingPattern, Field(discriminator="type")]


class WorkScheduleCreate(DirectoryInput):
    name: DirectoryName
    pattern: WorkPattern
    late_tolerance_minutes: LateTolerance = 0


@with_config(ConfigDict(extra="forbid"))
class WorkScheduleUpdate(TypedDict, total=False):
    name: DirectoryName
    pattern: WorkPattern
    late_tolerance_minutes: LateTolerance


class WorkScheduleOut(DirectoryRecord):
    name: str
    pattern: WorkPattern
    late_tolerance_minutes: int


class ScheduleAssignment(DirectoryInput):
    schedule_id: DirectoryId | None


class PlannedShift(DirectoryInput):
    starts_at: datetime
    ends_at: datetime
    break_starts_at: datetime | None = None
    break_ends_at: datetime | None = None


class EmployeeWorkPlan(DirectoryInput):
    date: date
    timezone: str
    schedule_id: int | None = None
    source: Literal["employee", "group"] | None = None
    late_tolerance_minutes: int | None = None
    shift: PlannedShift | None = None
