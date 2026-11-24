"""Cabinet API for work schedules and staff assignments."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from ..auth import SessionDep, current_user
from ..directory_schemas import Page
from ..models import Employee, Group, WorkSchedule
from ..work_schedule_schemas import (
    EmployeeWorkPlan,
    ScheduleAssignment,
    WorkScheduleCreate,
    WorkScheduleOut,
    WorkScheduleUpdate,
)
from ..work_schedules import get_employee_work_plan
from .directories import ListQuery, RecordId, _create, _delete, _get, _page, _update

router = APIRouter(prefix="/api/v1", tags=["work schedules"], dependencies=[Depends(current_user)])


@router.get("/work-schedules", response_model=Page[WorkScheduleOut])
def list_work_schedules(db: SessionDep, params: ListQuery):
    return _page(db, select(WorkSchedule), params, WorkSchedule.name, WorkSchedule.id)


@router.post("/work-schedules", response_model=WorkScheduleOut, status_code=status.HTTP_201_CREATED)
def create_work_schedule(payload: WorkScheduleCreate, db: SessionDep) -> WorkSchedule:
    return _create(db, WorkSchedule(**payload.model_dump(mode="json")))


@router.get("/work-schedules/{schedule_id}", response_model=WorkScheduleOut)
def read_work_schedule(schedule_id: RecordId, db: SessionDep) -> WorkSchedule:
    return _get(db, WorkSchedule, schedule_id)


@router.patch("/work-schedules/{schedule_id}", response_model=WorkScheduleOut)
def update_work_schedule(schedule_id: RecordId, payload: WorkScheduleUpdate, db: SessionDep) -> WorkSchedule:
    changes = dict(payload)
    if "pattern" in payload:
        changes["pattern"] = payload["pattern"].model_dump(mode="json")
    return _update(db, _get(db, WorkSchedule, schedule_id), changes)


@router.delete("/work-schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_work_schedule(schedule_id: RecordId, db: SessionDep) -> None:
    _delete(db, _get(db, WorkSchedule, schedule_id))


@router.get("/groups/{group_id}/work-schedule", response_model=ScheduleAssignment)
def read_group_schedule(group_id: RecordId, db: SessionDep) -> ScheduleAssignment:
    return ScheduleAssignment(schedule_id=_get(db, Group, group_id).schedule_id)


@router.put("/groups/{group_id}/work-schedule", response_model=ScheduleAssignment)
def assign_group_schedule(group_id: RecordId, payload: ScheduleAssignment, db: SessionDep) -> ScheduleAssignment:
    group = _get(db, Group, group_id)
    if payload.schedule_id is not None:
        _get(db, WorkSchedule, payload.schedule_id)
    _update(db, group, payload.model_dump())
    return payload


@router.get("/employees/{employee_id}/work-schedule", response_model=ScheduleAssignment)
def read_employee_schedule(employee_id: RecordId, db: SessionDep) -> ScheduleAssignment:
    return ScheduleAssignment(schedule_id=_get(db, Employee, employee_id).schedule_id)


@router.put("/employees/{employee_id}/work-schedule", response_model=ScheduleAssignment)
def assign_employee_schedule(
    employee_id: RecordId, payload: ScheduleAssignment, db: SessionDep,
) -> ScheduleAssignment:
    employee = _get(db, Employee, employee_id)
    if payload.schedule_id is not None:
        _get(db, WorkSchedule, payload.schedule_id)
    _update(db, employee, payload.model_dump())
    return payload


@router.get("/employees/{employee_id}/work-plan", response_model=EmployeeWorkPlan)
def read_employee_work_plan(employee_id: RecordId, day: date, db: SessionDep) -> EmployeeWorkPlan:
    """Возвращает смену, которая начинается в указанную дату по времени офиса. Время смены — UTC."""
    try:
        plan = get_employee_work_plan(db, employee_id, day)
    except OverflowError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Shift is outside the supported date range") from exc
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return plan
