"""Модели базы данных.

Пользователь Windows (логин) хранится в каждой записи как есть: сопоставление
логина с сотрудником делается через регистронезависимый ключ в employee_logins,
чтобы один сотрудник мог работать на разных компьютерах и под разными логинами.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class Office(Base):
    __tablename__ = "offices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")


class MonitoringProfile(Base):
    """Профиль мониторинга: что и как часто собирает агент."""

    __tablename__ = "monitoring_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Через сколько секунд без клавиатуры и мыши время считается простоем.
    idle_threshold_sec: Mapped[int] = mapped_column(Integer, default=300)
    screenshots_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    screenshot_interval_sec: Mapped[int] = mapped_column(Integer, default=5)
    # Качество сжатия 1–100.
    screenshot_quality: Mapped[int] = mapped_column(Integer, default=75)
    # webp | avif | jpeg
    screenshot_format: Mapped[str] = mapped_column(String(16), default="webp")
    # Максимальная ширина кадра в пикселях; 0 — без уменьшения.
    screenshot_max_width: Mapped[int] = mapped_column(Integer, default=0)
    # Не отправлять кадр, если экран не изменился с прошлого снимка.
    screenshot_skip_unchanged: Mapped[bool] = mapped_column(Boolean, default=True)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_profiles.id"))


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(300))
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", name="fk_employees_position_id"), index=True,
    )
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"))
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    logins: Mapped[list["EmployeeLogin"]] = relationship(back_populates="employee")


class EmployeeLogin(Base):
    """Логин Windows (DOMAIN\\user или COMPUTER\\user), закреплённый за сотрудником."""

    __tablename__ = "employee_logins"
    __table_args__ = (UniqueConstraint("login_key", name="uq_employee_logins_login_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    login: Mapped[str] = mapped_column(String(300), unique=True)
    login_key: Mapped[str] = mapped_column(Text)

    employee: Mapped[Employee] = relationship(back_populates="logins")


class Computer(Base):
    __tablename__ = "computers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Постоянный идентификатор машины, который генерирует агент.
    machine_id: Mapped[str] = mapped_column(String(64), unique=True)
    hostname: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    os_version: Mapped[str | None] = mapped_column(String(255))
    agent_version: Mapped[str | None] = mapped_column(String(64))
    office_id: Mapped[int | None] = mapped_column(ForeignKey("offices.id"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_profiles.id"))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def name(self) -> str:
        return self.display_name if self.display_name is not None else self.hostname


class ObservedLogin(Base):
    __tablename__ = "observed_logins"

    login_key: Mapped[str] = mapped_column(Text, primary_key=True)
    login: Mapped[str] = mapped_column(String(300))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_computer_id: Mapped[int | None] = mapped_column(ForeignKey("computers.id", ondelete="SET NULL"))


class ActivitySpan(Base):
    """Непрерывный отрезок работы в одном окне (или простоя)."""

    __tablename__ = "activity_spans"
    __table_args__ = (UniqueConstraint("computer_id", "client_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    # Идентификатор записи на стороне агента: повторная отправка не создаёт дубль.
    client_id: Mapped[str] = mapped_column(String(64))
    login: Mapped[str] = mapped_column(String(300), index=True)
    session_id: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_idle: Mapped[bool] = mapped_column(Boolean, default=False)
    process_name: Mapped[str | None] = mapped_column(String(260))
    window_title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)


class SystemEvent(Base):
    """Включение, выключение, вход, выход, блокировка компьютера и т.п."""

    __tablename__ = "system_events"
    __table_args__ = (UniqueConstraint("computer_id", "client_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    login: Mapped[str | None] = mapped_column(String(300))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(32))


class Screenshot(Base):
    __tablename__ = "screenshots"
    __table_args__ = (UniqueConstraint("computer_id", "client_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    login: Mapped[str] = mapped_column(String(300))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    monitor: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer)


class CabinetUser(Base):
    """A manager with access to the web cabinet, separate from agent identities."""

    __tablename__ = "cabinet_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(32), default="admin")


class CabinetSession(Base):
    __tablename__ = "cabinet_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("cabinet_users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginThrottle(Base):
    """Persistent fixed-window login attempt counter, keyed by account or IP hash."""

    __tablename__ = "login_throttles"

    key: Mapped[str] = mapped_column(String(70), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    window_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
