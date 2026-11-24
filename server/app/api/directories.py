"""Authenticated office, staff and computer directories for the cabinet."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import SessionDep, current_user
from ..db import Base
from ..directory_schemas import (
    MAX_DIRECTORY_ID,
    ComputerOut,
    ComputerUpdate,
    EmployeeCreate,
    EmployeeLoginCreate,
    EmployeeLoginOut,
    EmployeeOut,
    EmployeeUpdate,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    MonitoringProfileOptionOut,
    OfficeCreate,
    OfficeOut,
    OfficeUpdate,
    Page,
    PositionCreate,
    PositionOut,
    PositionUpdate,
    UnknownLoginOut,
)
from ..jobs.daily_totals import enqueue_login_history
from ..models import Computer, Employee, EmployeeLogin, Group, MonitoringProfile, ObservedLogin, Office, Position

router = APIRouter(prefix="/api/v1", tags=["directories"], dependencies=[Depends(current_user)])
RecordId = Annotated[int, Path(gt=0, le=MAX_DIRECTORY_ID)]


class ListParams(BaseModel):
    limit: Annotated[int, Query(ge=1, le=200)] = 50
    offset: Annotated[int, Query(ge=0, le=MAX_DIRECTORY_ID)] = 0
    q: Annotated[str | None, Query(max_length=300)] = None


class EmployeeListParams(ListParams):
    is_dismissed: bool | None = None


ListQuery = Annotated[ListParams, Query()]


def _page(db: Session, statement: Select, params: ListParams, name, tie_breaker) -> dict:
    if params.q:
        statement = statement.where(name.icontains(params.q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    page = statement.order_by(func.lower(name), tie_breaker).limit(params.limit).offset(params.offset)
    items = db.scalars(page).all()
    return {"items": items, "total": total, "limit": params.limit, "offset": params.offset}


def _get[T: Base](db: Session, model: type[T], record_id: int) -> T:
    record = db.get(model, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Directory record not found")
    return record


def _commit(db: Session, *, deleting: bool = False) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        sqlstate = getattr(exc.orig, "sqlstate", None)
        sqlite_error = getattr(exc.orig, "sqlite_errorname", None)
        if sqlstate == "23505" or sqlite_error == "SQLITE_CONSTRAINT_UNIQUE":
            detail = "Duplicate directory value"
        elif sqlstate == "23503" or sqlite_error == "SQLITE_CONSTRAINT_FOREIGNKEY":
            detail = "Directory record is in use" if deleting else "Referenced directory record does not exist"
        else:
            detail = "Directory constraint conflict"
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc


def _create[T: Base](db: Session, record: T) -> T:
    db.add(record)
    _commit(db)
    return record


def _update[T: Base](db: Session, record: T, changes: dict) -> T:
    for field, value in changes.items():
        setattr(record, field, value)
    _commit(db)
    return record


def _delete(db: Session, record: Base) -> None:
    db.delete(record)
    _commit(db, deleting=True)


@router.get("/offices", response_model=Page[OfficeOut])
def list_offices(db: SessionDep, params: ListQuery):
    return _page(db, select(Office), params, Office.name, Office.id)


@router.post("/offices", response_model=OfficeOut, status_code=status.HTTP_201_CREATED)
def create_office(payload: OfficeCreate, db: SessionDep) -> Office:
    return _create(db, Office(**payload.model_dump()))


@router.get("/offices/{office_id}", response_model=OfficeOut)
def get_office(office_id: RecordId, db: SessionDep) -> Office:
    return _get(db, Office, office_id)


@router.patch("/offices/{office_id}", response_model=OfficeOut)
def update_office(office_id: RecordId, payload: OfficeUpdate, db: SessionDep) -> Office:
    return _update(db, _get(db, Office, office_id), payload)


@router.delete("/offices/{office_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_office(office_id: RecordId, db: SessionDep) -> None:
    _delete(db, _get(db, Office, office_id))


@router.get("/monitoring-profiles", response_model=Page[MonitoringProfileOptionOut])
def list_monitoring_profiles(db: SessionDep, params: ListQuery):
    return _page(db, select(MonitoringProfile), params, MonitoringProfile.name, MonitoringProfile.id)


@router.get("/groups", response_model=Page[GroupOut])
def list_groups(db: SessionDep, params: ListQuery):
    return _page(db, select(Group), params, Group.name, Group.id)


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, db: SessionDep) -> Group:
    return _create(db, Group(**payload.model_dump()))


@router.get("/groups/{group_id}", response_model=GroupOut)
def get_group(group_id: RecordId, db: SessionDep) -> Group:
    return _get(db, Group, group_id)


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(group_id: RecordId, payload: GroupUpdate, db: SessionDep) -> Group:
    return _update(db, _get(db, Group, group_id), payload)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: RecordId, db: SessionDep) -> None:
    _delete(db, _get(db, Group, group_id))


@router.get("/positions", response_model=Page[PositionOut])
def list_positions(db: SessionDep, params: ListQuery):
    return _page(db, select(Position), params, Position.name, Position.id)


@router.post("/positions", response_model=PositionOut, status_code=status.HTTP_201_CREATED)
def create_position(payload: PositionCreate, db: SessionDep) -> Position:
    return _create(db, Position(**payload.model_dump()))


@router.get("/positions/{position_id}", response_model=PositionOut)
def get_position(position_id: RecordId, db: SessionDep) -> Position:
    return _get(db, Position, position_id)


@router.patch("/positions/{position_id}", response_model=PositionOut)
def update_position(position_id: RecordId, payload: PositionUpdate, db: SessionDep) -> Position:
    return _update(db, _get(db, Position, position_id), payload)


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position(position_id: RecordId, db: SessionDep) -> None:
    _delete(db, _get(db, Position, position_id))


@router.get("/employees", response_model=Page[EmployeeOut])
def list_employees(db: SessionDep, params: Annotated[EmployeeListParams, Query()]):
    statement = select(Employee)
    if params.is_dismissed is not None:
        statement = statement.where(Employee.is_dismissed.is_(params.is_dismissed))
    return _page(db, statement, params, Employee.full_name, Employee.id)


@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeCreate, db: SessionDep) -> Employee:
    return _create(db, Employee(**payload.model_dump()))


@router.get("/employees/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: RecordId, db: SessionDep) -> Employee:
    return _get(db, Employee, employee_id)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: RecordId, payload: EmployeeUpdate, db: SessionDep) -> Employee:
    return _update(db, _get(db, Employee, employee_id), payload)


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_employee(employee_id: RecordId, db: SessionDep) -> None:
    _update(db, _get(db, Employee, employee_id), {"is_dismissed": True})


@router.get("/employees/{employee_id}/logins", response_model=Page[EmployeeLoginOut])
def list_employee_logins(employee_id: RecordId, db: SessionDep, params: ListQuery):
    _get(db, Employee, employee_id)
    statement = select(EmployeeLogin).where(EmployeeLogin.employee_id == employee_id)
    return _page(db, statement, params, EmployeeLogin.login, EmployeeLogin.id)


@router.post("/employees/{employee_id}/logins", response_model=EmployeeLoginOut, status_code=status.HTTP_201_CREATED)
def bind_employee_login(employee_id: RecordId, payload: EmployeeLoginCreate, db: SessionDep) -> EmployeeLogin:
    _get(db, Employee, employee_id)
    login_key = payload.login.casefold()
    enqueue_login_history(db, login_key)
    return _create(db, EmployeeLogin(employee_id=employee_id, login=payload.login, login_key=login_key))


@router.delete("/employees/{employee_id}/logins/{login_id}", status_code=status.HTTP_204_NO_CONTENT)
def unbind_employee_login(employee_id: RecordId, login_id: RecordId, db: SessionDep) -> None:
    binding = db.scalar(select(EmployeeLogin).where(
        EmployeeLogin.id == login_id, EmployeeLogin.employee_id == employee_id,
    ))
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee login not found")
    enqueue_login_history(db, binding.login_key)
    _delete(db, binding)


@router.get("/logins/unknown", response_model=Page[UnknownLoginOut])
def list_unknown_logins(db: SessionDep, params: ListQuery):
    binding_exists = select(EmployeeLogin.id).where(EmployeeLogin.login_key == ObservedLogin.login_key).exists()
    statement = select(ObservedLogin).where(~binding_exists)
    return _page(db, statement, params, ObservedLogin.login, ObservedLogin.login_key)


@router.get("/computers", response_model=Page[ComputerOut])
def list_computers(db: SessionDep, params: ListQuery):
    name = func.coalesce(Computer.display_name, Computer.hostname)
    return _page(db, select(Computer), params, name, Computer.id)


@router.get("/computers/{computer_id}", response_model=ComputerOut)
def get_computer(computer_id: RecordId, db: SessionDep) -> Computer:
    return _get(db, Computer, computer_id)


@router.patch("/computers/{computer_id}", response_model=ComputerOut)
def update_computer(computer_id: RecordId, payload: ComputerUpdate, db: SessionDep) -> Computer:
    changes = {"display_name" if field == "name" else field: value for field, value in payload.items()}
    return _update(db, _get(db, Computer, computer_id), changes)
