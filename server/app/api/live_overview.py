"""Current computer status for the authenticated cabinet."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select

from ..auth import SessionDep, current_user
from ..directory_schemas import MAX_DIRECTORY_ID, DirectoryId, Page
from ..models import Computer, ComputerHeartbeat, Employee, EmployeeLogin, Group, Office, as_utc, utcnow

router = APIRouter(
    prefix="/api/v1/reports/live-overview", tags=["reports"], dependencies=[Depends(current_user)],
)
LIVE_WINDOW = timedelta(minutes=1)


class LiveOverviewQuery(BaseModel):
    office_id: DirectoryId | None = None
    group_id: DirectoryId | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=MAX_DIRECTORY_ID)


class DirectoryLabel(BaseModel):
    id: int
    name: str


class LiveSessionOut(BaseModel):
    login: str
    employee: DirectoryLabel | None
    group: DirectoryLabel | None
    process_name: str | None
    window_title: str | None
    last_input_at: datetime
    sampled_at: datetime
    is_idle: bool


class LiveComputer(BaseModel):
    id: int
    name: str
    office: DirectoryLabel | None
    last_seen_at: datetime | None
    online: bool
    session: LiveSessionOut | None


class LiveOverviewPage(Page[LiveComputer]):
    as_of: datetime


@router.get("", response_model=LiveOverviewPage)
def live_overview(params: Annotated[LiveOverviewQuery, Query()], db: SessionDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    as_of = utcnow()
    cutoff = as_of - LIVE_WINDOW
    office_id = func.coalesce(Computer.office_id, Group.office_id)
    query = (
        select(Computer, ComputerHeartbeat, Employee, Group, Office)
        .select_from(Computer)
        .outerjoin(ComputerHeartbeat, ComputerHeartbeat.computer_id == Computer.id)
        .outerjoin(EmployeeLogin, and_(
            ComputerHeartbeat.login_key == EmployeeLogin.login_key,
            ComputerHeartbeat.sampled_at > cutoff,
        ))
        .outerjoin(Employee, Employee.id == EmployeeLogin.employee_id)
        .outerjoin(Group, Group.id == Employee.group_id)
        .outerjoin(Office, Office.id == office_id)
    )
    if params.office_id is not None:
        query = query.where(office_id == params.office_id)
    if params.group_id is not None:
        query = query.where(Group.id == params.group_id)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(func.coalesce(Computer.display_name, Computer.hostname), Computer.id)
        .limit(params.limit).offset(params.offset)
    )
    items = []
    for computer, heartbeat, employee, group, office in rows:
        seen = [as_utc(value) for value in (
            computer.last_seen_at, heartbeat.received_at if heartbeat else None,
        ) if value is not None]
        last_seen_at = max(seen, default=None)
        session = None
        if heartbeat and heartbeat.sampled_at and as_utc(heartbeat.sampled_at) > cutoff:
            session = LiveSessionOut(
                login=heartbeat.login,
                employee=DirectoryLabel(id=employee.id, name=employee.full_name) if employee else None,
                group=DirectoryLabel(id=group.id, name=group.name) if group else None,
                process_name=heartbeat.process_name,
                window_title=heartbeat.window_title,
                last_input_at=as_utc(heartbeat.last_input_at),
                sampled_at=as_utc(heartbeat.sampled_at),
                is_idle=heartbeat.is_idle,
            )
        items.append(LiveComputer(
            id=computer.id,
            name=computer.name,
            office=DirectoryLabel(id=office.id, name=office.name) if office else None,
            last_seen_at=last_seen_at,
            online=last_seen_at is not None and last_seen_at > cutoff,
            session=session,
        ))
    return LiveOverviewPage(items=items, total=total, limit=params.limit, offset=params.offset, as_of=as_of)
