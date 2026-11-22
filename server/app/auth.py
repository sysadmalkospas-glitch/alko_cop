"""Authentication and session management for the web cabinet."""

import unicodedata
from datetime import datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import case, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_session
from .models import CabinetSession, CabinetUser, LoginThrottle, utcnow
from .security import hash_token, new_token

COOKIE_NAME = "alkocop_session"
COOKIE_PATH = "/api/v1"
MAX_PASSWORD_LENGTH = 1024

_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
# An unknown or inactive account still incurs the password verification cost.
_DUMMY_HASH = _PASSWORD_HASHER.hash(new_token())

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def normalize_login(value: str) -> str:
    login = unicodedata.normalize("NFKC", value).strip().casefold()
    if not 1 <= len(login) <= 128 or not all(
        char.isalnum() or char in "._-@" for char in login
    ):
        raise ValueError("Invalid login")
    return login


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError("Password must contain 12–1024 characters")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not 1 <= len(password) <= MAX_PASSWORD_LENGTH:
        return False
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, UnicodeError):
        return False


class LoginRequest(BaseModel):
    login: str = Field(max_length=128)
    password: SecretStr

    @field_validator("login")
    @classmethod
    def canonical_login(cls, value: str) -> str:
        return normalize_login(value)


class UserInfo(BaseModel):
    id: int
    login: str
    role: str

    @classmethod
    def from_user(cls, user: CabinetUser) -> "UserInfo":
        return cls(id=user.id, login=user.login, role=user.role)


class AuthRoute(APIRoute):
    """Do not include submitted passwords in FastAPI validation error bodies."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid login data",
                    headers={"Cache-Control": "no-store"},
                ) from None

        return safe_handler


router = APIRouter(prefix="/api/v1/auth", tags=["auth"], route_class=AuthRoute)


def require_same_origin(request: Request) -> None:
    """Reject browser cross-origin mutations; non-browser clients omit Origin."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-origin request denied")
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-origin request denied")


def require_secure_transport(request: Request, settings: Settings) -> None:
    if settings.auth_cookie_secure and request.url.scheme != "https":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "HTTPS required")


def _throttle_key(kind: str, value: str) -> str:
    return f"{kind}:{hash_token(value)}"


def _reserve_attempt(
    db: Session, key: str, limit: int, now: datetime, window_seconds: int,
) -> bool:
    # The conditional upsert reserves a slot atomically even across workers.
    dialect = db.get_bind().dialect.name
    insert = sqlite_insert if dialect == "sqlite" else postgres_insert
    end = now + timedelta(seconds=window_seconds)
    expired = LoginThrottle.window_ends_at <= now
    stmt = insert(LoginThrottle).values(key=key, attempts=1, window_ends_at=end)
    stmt = stmt.on_conflict_do_update(
        index_elements=[LoginThrottle.key],
        set_={
            "attempts": case((expired, 1), else_=LoginThrottle.attempts + 1),
            "window_ends_at": case((expired, end), else_=LoginThrottle.window_ends_at),
        },
        where=or_(expired, LoginThrottle.attempts < limit),
    ).returning(LoginThrottle.key)
    return db.execute(stmt).scalar_one_or_none() is not None


def _reserve_login(db: Session, login: str, host: str, settings: Settings) -> str:
    now = utcnow()
    account_key = _throttle_key("login", login)
    ip_key = _throttle_key("ip", host)
    db.execute(delete(LoginThrottle).where(LoginThrottle.window_ends_at <= now))
    allowed = _reserve_attempt(
        db, ip_key, settings.auth_ip_attempt_limit, now, settings.auth_login_window_seconds,
    ) and _reserve_attempt(
        db, account_key, settings.auth_login_attempt_limit, now, settings.auth_login_window_seconds,
    )
    db.commit()
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts",
            headers={"Retry-After": str(settings.auth_login_window_seconds), "Cache-Control": "no-store"},
        )
    return account_key


def current_user(
    request: Request, response: Response, db: SessionDep, settings: SettingsDep,
) -> CabinetUser:
    """Reusable dependency for future cabinet APIs; never accepts agent tokens."""
    require_same_origin(request)
    response.headers["Cache-Control"] = "no-store"
    token = request.cookies.get(COOKIE_NAME)
    user = None
    if token and len(token) == 43:
        require_secure_transport(request, settings)
        user = db.scalar(
            select(CabinetUser)
            .join(CabinetSession, CabinetSession.user_id == CabinetUser.id)
            .where(
                CabinetSession.token_hash == hash_token(token),
                CabinetSession.expires_at > utcnow(),
                CabinetUser.is_active.is_(True),
            )
        )
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Authentication required",
            headers={"Cache-Control": "no-store"},
        )
    return user


CurrentUser = Annotated[CabinetUser, Depends(current_user)]


@router.post("/login", response_model=UserInfo)
def login(
    payload: LoginRequest, request: Request, response: Response, db: SessionDep,
    settings: SettingsDep,
) -> UserInfo:
    require_same_origin(request)
    require_secure_transport(request, settings)
    account_key = _reserve_login(
        db, payload.login, request.client.host if request.client else "unknown", settings,
    )
    user = db.scalar(select(CabinetUser).where(CabinetUser.login == payload.login))
    password = payload.password.get_secret_value()
    valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not valid or user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid login or password",
            headers={"Cache-Control": "no-store"},
        )

    now = utcnow()
    db.execute(delete(LoginThrottle).where(LoginThrottle.key == account_key))
    db.execute(delete(CabinetSession).where(CabinetSession.expires_at <= now))
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token and len(old_token) == 43:
        db.execute(delete(CabinetSession).where(CabinetSession.token_hash == hash_token(old_token)))
    if _PASSWORD_HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = _PASSWORD_HASHER.hash(password)
    token = new_token()
    db.add(CabinetSession(
        token_hash=hash_token(token),
        user_id=user.id,
        expires_at=now + timedelta(seconds=settings.auth_session_ttl_seconds),
    ))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.auth_session_ttl_seconds,
        path=COOKIE_PATH, secure=settings.auth_cookie_secure, httponly=True, samesite="strict",
    )
    return UserInfo.from_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(request: Request, db: SessionDep, settings: SettingsDep, user: CurrentUser) -> Response:
    token = request.cookies[COOKIE_NAME]
    db.execute(delete(CabinetSession).where(
        CabinetSession.token_hash == hash_token(token), CabinetSession.user_id == user.id,
    ))
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        COOKIE_NAME, path=COOKIE_PATH, secure=settings.auth_cookie_secure,
        httponly=True, samesite="strict",
    )
    return response


@router.get("/me", response_model=UserInfo)
def me(user: CurrentUser) -> UserInfo:
    return UserInfo.from_user(user)
