from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3

from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from pydantic import BaseModel, Field

from . import scrim_db


router = APIRouter(prefix="/api/scrim", tags=["scrim-management"])
SCRIM_AUTH_COOKIE = "scrim_auth"


class UserCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    riot_id: str = Field(min_length=3, max_length=80)
    secondary_riot_id: str | None = Field(default=None, max_length=80)
    password: str = Field(default="1234", min_length=4, max_length=128)
    nickname: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)


class LoginInput(BaseModel):
    riot_id: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=4, max_length=128)


class TeamCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    top_rank: str | None = Field(default=None, max_length=50)
    game_count: int = Field(default=0, ge=0)


class TeamJoinInput(BaseModel):
    invite_code: str = Field(min_length=1)


class ScrimScheduleInput(BaseModel):
    team_id: int
    scheduled_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    opponent_team_name: str | None = Field(default=None, max_length=100)
    memo: str | None = None


class PasswordResetInput(BaseModel):
    new_password: str = Field(min_length=4, max_length=128)


class UserApprovalInput(BaseModel):
    approved: bool


class MyProfileInput(BaseModel):
    riot_id: str = Field(min_length=3, max_length=80)
    secondary_riot_id: str | None = Field(default=None, max_length=80)
    nickname: str | None = Field(default=None, max_length=50)
    password: str | None = Field(default=None, min_length=4, max_length=128)


def _sign(payload: str) -> str:
    secret = os.getenv("SCRIM_SESSION_SECRET") or os.getenv(
        "SESSION_SECRET", "local-development-secret"
    )
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(user: dict) -> str:
    raw = json.dumps(
        {
            "user_id": user["id"],
            "role": user["role"],
            "nonce": secrets.token_hex(4),
        },
        separators=(",", ":"),
    )
    payload = base64.urlsafe_b64encode(raw.encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_session(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data.get("user_id"), int):
        return None
    return data


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "riot_id": user["riot_id"],
        "secondary_riot_id": user.get("secondary_riot_id"),
        "nickname": user.get("nickname"),
        "role": user["role"],
        "approved": bool(user.get("approved", False)),
        "is_active": bool(user["is_active"]),
        "last_login_at": user["last_login_at"],
        "created_at": user["created_at"],
    }


def set_session_cookie(response: Response, user: dict) -> None:
    response.set_cookie(
        SCRIM_AUTH_COOKIE,
        make_session(user),
        httponly=True,
        samesite="lax",
        secure=bool(os.getenv("VERCEL")),
    )


def current_user_or_none(scrim_auth: str | None) -> dict | None:
    session = read_session(scrim_auth)
    if session is None:
        return None
    try:
        with scrim_db.connect() as connection:
            return scrim_db.get_user(connection, session["user_id"])
    except ValueError:
        return None


def current_user_from_cookie(scrim_auth: str | None) -> dict:
    user = current_user_or_none(scrim_auth)
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


def require_admin(scrim_auth: str | None) -> dict:
    current_user = current_user_from_cookie(scrim_auth)
    if current_user["role"] != "ADMIN":
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return current_user


@router.get("/health")
async def health():
    scrim_db.init_db()
    return {
        "ok": True,
        "backend": scrim_db.configured_backend(),
        "database": scrim_db.configured_database_label(),
    }


@router.post("/users")
async def create_user(data: UserCreateInput, response: Response):
    if os.getenv("SCRIM_ALLOW_PUBLIC_SIGNUP", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(403, "회원가입은 강사님이 회원 관리에서 생성합니다.")
    try:
        with scrim_db.connect() as connection:
            user = scrim_db.create_user(connection, **data.model_dump())
            set_session_cookie(response, user)
            return public_user(user)
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/auth/login")
async def login(data: LoginInput, response: Response):
    with scrim_db.connect() as connection:
        user = scrim_db.get_user_by_riot_id(connection, data.riot_id)
        if user is None or not scrim_db.verify_password(
            data.password, user["password_hash"]
        ):
            raise HTTPException(401, "롤 아이디 또는 비밀번호가 올바르지 않습니다.")
        scrim_db.touch_last_login(connection, user["id"])
        user = scrim_db.get_user(connection, user["id"])
        set_session_cookie(response, user)
        return public_user(user)


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(SCRIM_AUTH_COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(scrim_auth: str | None = Cookie(default=None)):
    return public_user(current_user_from_cookie(scrim_auth))


@router.patch("/me")
async def update_me(
    data: MyProfileInput,
    scrim_auth: str | None = Cookie(default=None),
):
    current_user = current_user_from_cookie(scrim_auth)
    try:
        with scrim_db.connect() as connection:
            user = scrim_db.update_user_profile(
                connection,
                user_id=current_user["id"],
                **data.model_dump(),
            )
            return public_user(user)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(400, "이미 사용 중인 본 아이디입니다.") from exc


@router.get("/admin/users")
async def admin_search_users(
    query: str = Query(default="", max_length=80),
    scrim_auth: str | None = Cookie(default=None),
):
    require_admin(scrim_auth)
    with scrim_db.connect() as connection:
        users = scrim_db.search_users(connection, query)
        return {"users": [public_user(user) for user in users]}


@router.post("/admin/users")
async def admin_create_user(
    data: UserCreateInput,
    scrim_auth: str | None = Cookie(default=None),
):
    require_admin(scrim_auth)
    try:
        with scrim_db.connect() as connection:
            user = scrim_db.create_user(
                connection,
                **data.model_dump(),
                approved=True,
            )
            return public_user(user)
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/admin/users/{user_id}/password")
async def admin_reset_user_password(
    user_id: int,
    data: PasswordResetInput,
    scrim_auth: str | None = Cookie(default=None),
):
    require_admin(scrim_auth)
    with scrim_db.connect() as connection:
        user = scrim_db.reset_user_password(
            connection,
            user_id=user_id,
            new_password=data.new_password,
        )
        return public_user(user)


@router.patch("/admin/users/{user_id}/approval")
async def admin_set_user_approval(
    user_id: int,
    data: UserApprovalInput,
    scrim_auth: str | None = Cookie(default=None),
):
    require_admin(scrim_auth)
    with scrim_db.connect() as connection:
        user = scrim_db.set_user_approval(
            connection,
            user_id=user_id,
            approved=data.approved,
        )
        return public_user(user)


@router.get("/teams")
async def list_teams():
    with scrim_db.connect() as connection:
        return {"teams": scrim_db.list_teams(connection)}


@router.post("/teams")
async def create_team(
    data: TeamCreateInput,
    scrim_auth: str | None = Cookie(default=None),
):
    current_user = current_user_from_cookie(scrim_auth)
    try:
        with scrim_db.connect() as connection:
            return scrim_db.create_team(
                connection,
                **data.model_dump(),
                created_by=current_user["id"],
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/teams/join")
async def join_team(
    data: TeamJoinInput,
    scrim_auth: str | None = Cookie(default=None),
):
    current_user = current_user_from_cookie(scrim_auth)
    try:
        with scrim_db.connect() as connection:
            return scrim_db.join_team_by_code(
                connection,
                invite_code=data.invite_code,
                user_id=current_user["id"],
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/schedules")
async def create_schedule(
    data: ScrimScheduleInput,
    scrim_auth: str | None = Cookie(default=None),
):
    if data.start_time >= data.end_time:
        raise HTTPException(400, "종료 시간은 시작 시간보다 늦어야 합니다.")
    current_user = current_user_from_cookie(scrim_auth)
    try:
        with scrim_db.connect() as connection:
            if not scrim_db.user_can_schedule(
                connection,
                user_id=current_user["id"],
                team_id=data.team_id,
            ):
                raise HTTPException(403, "팀장 또는 관리자만 예약할 수 있습니다.")
            return scrim_db.create_scrim_schedule(
                connection,
                **data.model_dump(),
                created_by=current_user["id"],
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
