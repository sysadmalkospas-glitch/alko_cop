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
