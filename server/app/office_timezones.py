from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_OFFICE_TIMEZONE = "Europe/Moscow"


def validate_office_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Unknown IANA time zone") from None
    return name


def office_timezone(name: str | None) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except (ValueError, ZoneInfoNotFoundError):
            # Legacy offices could store invalid values before write validation.
            pass
    return ZoneInfo(DEFAULT_OFFICE_TIMEZONE)


def local_instant(local: datetime, zone: ZoneInfo) -> datetime:
    """Convert a wall time to UTC, clamping a nonexistent time to the first valid instant."""
    first = local.replace(tzinfo=zone, fold=0).astimezone(UTC)
    if first.astimezone(zone).replace(tzinfo=None) == local:
        return first

    lower = local.replace(tzinfo=zone, fold=1).astimezone(UTC)
    upper = first
    while upper - lower > timedelta(microseconds=1):
        midpoint = lower + (upper - lower) // 2
        if midpoint.astimezone(zone).replace(tzinfo=None) < local:
            lower = midpoint
        else:
            upper = midpoint
    return upper
