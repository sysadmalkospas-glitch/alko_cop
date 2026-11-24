"""Day chronology for the authenticated cabinet."""

from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import and_, false, func, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import TSTZRANGE, Range
from xlsxwriter import Workbook

from ..auth import SessionDep, current_user
from ..directory_schemas import MAX_DIRECTORY_ID, DirectoryId, Page
from ..models import ActivitySpan, Employee, EmployeeLogin, Group, Office, as_utc, postgres_activity_span_range
from ..office_timezones import office_timezone

router = APIRouter(
    prefix="/api/v1/reports/day-chronology", tags=["reports"], dependencies=[Depends(current_user)],
)
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ChronologyFilters(BaseModel):
    employee_id: DirectoryId
    day: date
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    program: Annotated[str, StringConstraints(max_length=260)] = ""

    @field_validator("title", "program")
    @classmethod
    def reject_null_character(cls, value: str) -> str:
        if "\0" in value:
            raise ValueError("Invalid text filter")
        return value


class ChronologyQuery(ChronologyFilters):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=MAX_DIRECTORY_ID)


class ChronologyRow(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    process_name: str | None
    window_title: str | None
    url: str | None
    is_idle: bool


class ChronologyPage(Page[ChronologyRow]):
    timezone: str
    programs: list[str]


def _employee_timezone(db: SessionDep, employee_id: int) -> ZoneInfo:
    employee = db.execute(
        select(Employee.id, Office.timezone)
        .outerjoin(Group, Employee.group_id == Group.id)
        .outerjoin(Office, Group.office_id == Office.id)
        .where(Employee.id == employee_id)
    ).one_or_none()
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    return office_timezone(employee.timezone)


def _day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    try:
        start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
        end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    except OverflowError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Day is out of range") from None
    return start, end


def _employee_spans(db: SessionDep, employee_id: int, start: datetime, end: datetime):
    login_keys = set(db.scalars(select(EmployeeLogin.login_key).where(EmployeeLogin.employee_id == employee_id)))
    if not login_keys or start >= end:
        return false()

    # Spans retain the original login. Match every spelling with the same Python casefold
    # as directory bindings, including rows created before the login was linked.
    overlap = [
        ActivitySpan.started_at < end,
        or_(ActivitySpan.ended_at > start, ActivitySpan.started_at == start),
    ]
    if db.get_bind().dialect.name == "postgresql":
        # GiST bounds both ends of the scan without assuming a maximum span length.
        report_day = Range(start, end, bounds="[)")
        overlap.append(type_coerce(postgres_activity_span_range(), TSTZRANGE).overlaps(report_day))
    spellings = db.scalars(select(ActivitySpan.login).where(*overlap).distinct())
    logins = [login for login in spellings if login.casefold() in login_keys]
    return and_(ActivitySpan.login.in_(logins), *overlap)


def _filtered_spans(scope, filters: ChronologyFilters):
    if filters.title:
        scope &= ActivitySpan.window_title.icontains(filters.title, autoescape=True)
    if filters.program:
        scope &= ActivitySpan.process_name == filters.program
    return scope


def _row(span: ActivitySpan, start: datetime, end: datetime) -> ChronologyRow:
    # Clip intervals that straddle midnight to the requested local day.
    started_at = max(as_utc(span.started_at), start)
    ended_at = min(as_utc(span.ended_at), end)
    return ChronologyRow(
        id=span.id,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=(ended_at - started_at).total_seconds(),
        process_name=span.process_name,
        window_title=span.window_title,
        url=span.url,
        is_idle=span.is_idle,
    )


@router.post("/query", response_model=ChronologyPage)
def query_day_chronology(filters: ChronologyQuery, db: SessionDep) -> ChronologyPage:
    # Put title search terms in a request body so they stay out of HTTP access logs.
    zone = _employee_timezone(db, filters.employee_id)
    start, end = _day_bounds(filters.day, zone)
    employee_spans = _employee_spans(db, filters.employee_id, start, end)
    programs = db.scalars(
        select(ActivitySpan.process_name)
        .where(employee_spans, ActivitySpan.process_name.is_not(None), ActivitySpan.process_name != "")
        .distinct()
        .order_by(ActivitySpan.process_name)
    ).all()
    scope = _filtered_spans(employee_spans, filters)
    total = db.scalar(select(func.count()).select_from(ActivitySpan).where(scope))
    spans = db.scalars(
        select(ActivitySpan).where(scope)
        .order_by(ActivitySpan.started_at, ActivitySpan.id)
        .offset(filters.offset).limit(filters.limit)
    )
    return ChronologyPage(
        items=[_row(span, start, end) for span in spans],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
        timezone=zone.key,
        programs=programs,
    )


@router.post("/export", response_class=Response, responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}})
def export_day_chronology(filters: ChronologyFilters, db: SessionDep) -> Response:
    zone = _employee_timezone(db, filters.employee_id)
    start, end = _day_bounds(filters.day, zone)
    scope = _filtered_spans(_employee_spans(db, filters.employee_id, start, end), filters)
    spans = db.scalars(
        select(ActivitySpan).where(scope).order_by(ActivitySpan.started_at, ActivitySpan.id)
        .execution_options(yield_per=500),
    )
    output = BytesIO()
    with Workbook(output, {
        "in_memory": True,
        "strings_to_formulas": False,
        "strings_to_urls": False,
        "default_date_format": "yyyy-mm-dd hh:mm:ss",
    }) as workbook:
        sheet = workbook.add_worksheet("Хронометраж дня")
        headings = (
            f"Начало ({zone.key})", f"Конец ({zone.key})", "Длительность, с",
            "Программа", "Заголовок окна", "Адрес сайта", "Простой",
        )
        heading_format = workbook.add_format({"bold": True, "bg_color": "#E4F1EC"})
        sheet.write_row(0, 0, headings, heading_format)
        sheet.set_column(0, 1, 32)
        sheet.set_column(2, 3, 20)
        sheet.set_column(4, 5, 48)
        sheet.set_column(6, 6, 12)
        sheet.freeze_panes(1, 0)

        row_number = 0
        for row_number, span in enumerate(spans, start=1):
            row = _row(span, start, end)
            if sheet.write_row(row_number, 0, (
                row.started_at.astimezone(zone).replace(tzinfo=None),
                row.ended_at.astimezone(zone).replace(tzinfo=None),
                row.duration_seconds,
            )) == -1:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Too many rows for an Excel sheet")
            # Explicit string cells cover formula-like content, including array formulas and URLs.
            for column, value in enumerate((row.process_name, row.window_title, row.url), start=3):
                if value is not None:
                    sheet.write_string(row_number, column, value)
            sheet.write_string(row_number, 6, "Да" if row.is_idle else "Нет")
        sheet.autofilter(0, 0, row_number, len(headings) - 1)

    return Response(
        output.getvalue(),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="day-chronology-{filters.day.isoformat()}.xlsx"',
        },
    )
