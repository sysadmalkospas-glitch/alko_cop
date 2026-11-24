"""Shared calendar and interval filters for activity reports."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, type_coerce
from sqlalchemy.dialects.postgresql import TSTZRANGE, Range
from sqlalchemy.orm import Session

from .models import ActivitySpan, postgres_activity_span_range


def local_day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    return start, end


def overlapping_activity(db: Session, start: datetime, end: datetime):
    overlap = [
        ActivitySpan.started_at < end,
        or_(ActivitySpan.ended_at > start, ActivitySpan.started_at == start),
    ]
    if db.get_bind().dialect.name == "postgresql":
        # Use GiST for both bounds while retaining spans of any length.
        day = Range(start, end, bounds="[)")
        overlap.append(type_coerce(postgres_activity_span_range(), TSTZRANGE).overlaps(day))
    return overlap
