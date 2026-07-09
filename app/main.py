from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import (
    Cookie,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine, scrim_db
from .riot import RiotApiError, lookup_kr_player
from .scrim_api import (
    SCRIM_AUTH_COOKIE,
    current_user_or_none,
    router as scrim_router,
)
from .scrim_db import init_db as init_scrim_db
from .store import JsonStore


ROOT = Path(__file__).parent
store = JsonStore()
state_lock = asyncio.Lock()
connections: set[WebSocket] = set()
connection_viewers: dict[WebSocket, dict] = {}

SCRIM_RESULT_IMAGE_MAX_BYTES = int(os.getenv("SCRIM_RESULT_IMAGE_MAX_BYTES", "1048576"))
SCRIM_RESULT_IMAGE_MAX_PER_TEAM = int(os.getenv("SCRIM_RESULT_IMAGE_MAX_PER_TEAM", "30"))
SCRIM_RESULT_IMAGE_RETENTION_DAYS = int(os.getenv("SCRIM_RESULT_IMAGE_RETENTION_DAYS", "10"))
BLOB_API_URL = os.getenv("VERCEL_BLOB_API_URL", "https://vercel.com/api/blob")


def captain_presence() -> dict:
    online_ids = {
        viewer["captain_id"]
        for viewer in connection_viewers.values()
        if viewer.get("role") == "captain" and viewer.get("captain_id")
    }
    captain_ids = {captain["id"] for captain in store.state["captains"]}
    connected_ids = sorted(online_ids & captain_ids)
    return {
        "online_captain_ids": connected_ids,
        "connected": len(connected_ids),
        "total": len(captain_ids),
        "all_connected": bool(captain_ids) and captain_ids <= online_ids,
    }


def compute_viewer(token: str | None) -> dict:
    user = current_user_or_none(token)
    if user is None:
        return {"role": "spectator", "captain_id": None, "authenticated": False}
    with scrim_db.connect() as connection:
        roster = scrim_db.get_roster_entry_by_user_id(connection, user["id"])
    score_fields = {
        "TOP": ("탑", "score_top"),
        "JUG": ("정글", "score_jungle"),
        "MID": ("미드", "score_mid"),
        "ADC": ("원딜", "score_adc"),
        "SUP": ("서폿", "score_support"),
    }
    score_lines = []
    if roster:
        for index, position in enumerate(
            scrim_db.roster_positions(roster.get("preferred_lines"))
        ):
            label, field = score_fields[position]
            score = roster.get(field)
            if score not in (None, ""):
                score_lines.append(
                    {
                        "position": position,
                        "label": label,
                        "role": "주 라인" if index == 0 else "부 라인" if index == 1 else "추가 라인",
                        "score": score,
                    }
                )
    base = {
        "captain_id": None,
        "authenticated": True,
        "approved": bool(user.get("approved")),
        "user_id": user["id"],
        "riot_id": user["riot_id"],
        "secondary_riot_id": user.get("secondary_riot_id"),
        "nickname": user.get("nickname"),
        "name": user["name"],
        "roster_tier": roster.get("tier") if roster else None,
        "score_lines": score_lines,
    }
    if user["role"] == "ADMIN":
        return {**base, "role": "host", "approved": True}
    captain = next(
        (
            c
            for c in store.state["captains"]
            if c.get("user_id") == user["id"]
        ),
        None,
    )
    if captain:
        return {**base, "role": "captain", "captain_id": captain["id"], "approved": True}
    if user.get("approved"):
        return {**base, "role": "participant", "approved": True}
    return {**base, "role": "spectator", "approved": False}


def require_host(request: Request) -> dict:
    viewer = compute_viewer(request.cookies.get(SCRIM_AUTH_COOKIE))
    if viewer["role"] != "host":
        raise HTTPException(403, "강사님만 사용할 수 있는 기능입니다.")
    return viewer


def require_captain(request: Request) -> dict:
    viewer = compute_viewer(request.cookies.get(SCRIM_AUTH_COOKIE))
    if viewer["role"] != "captain" or not viewer["captain_id"]:
        raise HTTPException(403, "팀장으로 입장해야 입찰할 수 있습니다.")
    return viewer


def require_authenticated(request: Request) -> dict:
    viewer = compute_viewer(request.cookies.get(SCRIM_AUTH_COOKIE))
    if not viewer["authenticated"]:
        raise HTTPException(401, "먼저 입장해 주세요.")
    return viewer


def require_participant(request: Request) -> dict:
    viewer = require_authenticated(request)
    if viewer["role"] not in ("host", "participant", "captain"):
        raise HTTPException(403, "강사님 승인 후 참가할 수 있습니다.")
    return viewer


async def broadcast() -> None:
    dead: list[WebSocket] = []
    for connection in list(connections):
        try:
            viewer = connection_viewers.get(connection)
            payload = {
                "type": "state",
                "data": engine.public_state(store.state, viewer),
            }
            payload["data"]["competition_registry"] = (
                store.competition_summary()
            )
            payload["data"]["captain_presence"] = captain_presence()
            await connection.send_json(payload)
        except Exception:
            dead.append(connection)
    for connection in dead:
        connections.discard(connection)
        connection_viewers.pop(connection, None)


async def timer_loop() -> None:
    while True:
        await asyncio.sleep(0.2)
        changed = False
        async with state_lock:
            changed = engine.finalize_if_due(store.state)
            if changed:
                store.save()
        if changed:
            await broadcast()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_scrim_db()
    task = None
    if not os.getenv("VERCEL"):
        task = asyncio.create_task(timer_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="LoL Auction", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(scrim_router)


@app.middleware("http")
async def serverless_state_sync(request: Request, call_next):
    if os.getenv("VERCEL") and request.url.path.startswith("/api/"):
        async with state_lock:
            store.refresh()
            if engine.finalize_if_due(store.state):
                store.save()
    return await call_next(request)


class SettingsInput(BaseModel):
    room_name: str = Field(min_length=1, max_length=50)
    countdown_seconds: int = Field(ge=5, le=300)
    minimum_bid: int = Field(ge=0, le=1_000_000)
    bid_increment: int = Field(ge=1, le=1_000_000)
    extension_trigger_seconds: int = Field(ge=0, le=60)
    extension_seconds: int = Field(ge=0, le=60)


class CaptainInput(BaseModel):
    player_id: str
    budget: int = Field(ge=0, le=10_000_000)
    riot_id: str = Field(min_length=3, max_length=80)


class PlayerInput(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    riot_id: str = Field(default="", max_length=80)
    tier: str = Field(default="UNRANKED", max_length=40)
    primary_position: Literal["TOP", "JUG", "MID", "ADC", "SUP"]
    secondary_position: Literal["TOP", "JUG", "MID", "ADC", "SUP"] | None = None
    extra_positions: list[Literal["TOP", "JUG", "MID", "ADC", "SUP"]] = Field(default_factory=list, max_length=2)
    profile_icon_url: str | None = None
    score: int = Field(default=0, ge=0, le=1000)
    secondary_score: int | None = Field(default=None, ge=0, le=1000)


class PlayerScoreInput(BaseModel):
    score: int = Field(ge=0, le=1000)
    secondary_score: int | None = Field(default=None, ge=0, le=1000)


class RiotPlayerInput(BaseModel):
    riot_id: str = Field(min_length=3, max_length=80)
    primary_position: Literal["TOP", "JUG", "MID", "ADC", "SUP"]
    secondary_position: Literal["TOP", "JUG", "MID", "ADC", "SUP"] | None = None
    extra_positions: list[Literal["TOP", "JUG", "MID", "ADC", "SUP"]] = Field(default_factory=list, max_length=2)
    score: int = Field(default=0, ge=0, le=1000)
    secondary_score: int | None = Field(default=None, ge=0, le=1000)


class RosterRiotLookupInput(BaseModel):
    riot_id: str = Field(min_length=3, max_length=100)
    preferred_lines: str | None = Field(default=None, max_length=120)
    top_adjustment: str | None = Field(default=None, max_length=80)
    game_count_adjustment: str | None = Field(default=None, max_length=80)


class BidInput(BaseModel):
    amount: int = Field(ge=0, le=10_000_000)


class TournamentSettingsInput(BaseModel):
    score_limit: int = Field(ge=0, le=5000)
    format: Literal["single_elimination", "group_then_knockout"] = "single_elimination"
    group_count: int = Field(default=2, ge=2, le=16)
    qualifiers_per_group: int = Field(default=2, ge=1, le=8)


class TournamentTeamInput(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    members: dict[
        Literal["TOP", "JUG", "MID", "ADC", "SUP"], str
    ]
    registration_pin: str = Field(
        min_length=4, max_length=12, pattern=r"^[0-9]+$"
    )


class TeamApprovalInput(BaseModel):
    approved: bool


class MatchWinnerInput(BaseModel):
    round_index: int = Field(ge=0)
    match_index: int = Field(ge=0)
    team_id: str


class GroupQualifiersInput(BaseModel):
    group_index: int = Field(ge=0)
    team_ids: list[str] = Field(max_length=8)


class BracketRouteInput(BaseModel):
    round_index: int = Field(ge=0)
    match_index: int = Field(ge=0)
    slot: Literal["team1_id", "team2_id"]


class CustomBracketMatchInput(BaseModel):
    team1_id: str | None = None
    team2_id: str | None = None
    winner_to: BracketRouteInput | None = None
    loser_to: BracketRouteInput | None = None


class CustomBracketRoundInput(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    matches: list[CustomBracketMatchInput] = Field(min_length=1, max_length=64)


class CustomBracketInput(BaseModel):
    rounds: list[CustomBracketRoundInput] = Field(min_length=1, max_length=32)


class ScrimResultInput(BaseModel):
    team_a_id: str
    team_b_id: str
    match_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    best_of: int = Field(default=3)
    team_a_score: int = Field(ge=0, le=3)
    team_b_score: int = Field(ge=0, le=3)
    memo: str | None = Field(default=None, max_length=500)


class ParticipationSettingsInput(BaseModel):
    enabled: bool
    terms: str = Field(min_length=1, max_length=2000)


class ParticipationApplyInput(BaseModel):
    terms_agreed: bool


class ParticipationStatusInput(BaseModel):
    status: Literal["APPLIED", "APPROVED", "CANCELLED"]


class RosterEntryInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    participation_status_text: str | None = Field(default=None, max_length=80)
    absence_reason: str | None = Field(default=None, max_length=200)
    payment_status: str | None = Field(default=None, max_length=80)
    riot_id: str | None = Field(default=None, max_length=100)
    secondary_riot_id: str | None = Field(default=None, max_length=100)
    tier: str | None = Field(default=None, max_length=80)
    top_adjustment: str | None = Field(default=None, max_length=80)
    game_count_adjustment: str | None = Field(default=None, max_length=80)
    preferred_lines: str | None = Field(default=None, max_length=120)
    score_top: str | None = Field(default=None, max_length=40)
    score_jungle: str | None = Field(default=None, max_length=40)
    score_mid: str | None = Field(default=None, max_length=40)
    score_adc: str | None = Field(default=None, max_length=40)
    score_support: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=300)


class RosterImportRow(RosterEntryInput):
    source_row: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)


class RosterImportInput(BaseModel):
    rows: list[RosterImportRow] = Field(min_length=1, max_length=1000)


class RosterBulkUpdateRow(RosterEntryInput):
    id: int = Field(ge=1)


class RosterBulkUpdateInput(BaseModel):
    rows: list[RosterBulkUpdateRow] = Field(min_length=1, max_length=1000)


TEST_COMPETITION_ID = "test-score-approved"
TEST2_COMPETITION_ID = "test2-score-open"


def score_competition_state(name: str, *, participation_enabled: bool, applications: list[dict]) -> dict:
    score_state = engine.new_state()
    score_state["settings"]["room_name"] = name
    score_state["players"] = []
    score_state["tournament"]["status"] = "registration"
    score_state["participation"]["enabled"] = participation_enabled
    score_state["participation"]["applications"] = applications
    return score_state


def member_participation_payload(user: dict, applications: dict[int, dict]) -> dict:
    payload = {
        "id": user["id"],
        "name": user["name"],
        "riot_id": user["riot_id"],
        "secondary_riot_id": user.get("secondary_riot_id"),
        "nickname": user.get("nickname"),
        "role": user["role"],
        "approved": bool(user.get("approved", False)),
        "created_at": user["created_at"],
    }
    counts_for_stats = user["role"] != "ADMIN" and bool(user.get("approved", False))
    if not counts_for_stats:
        payload["participation_status"] = "excluded"
        payload["participation_label"] = "통계 제외"
        payload["applied_at"] = None
        return payload
    application = applications.get(user["id"])
    payload["participation_status"] = "applied" if application else "not_applied"
    payload["participation_label"] = "대회 참가" if application else "대회 미참가"
    return payload


def roster_entry_is_applied(entry: dict) -> bool:
    status_text = (entry.get("participation_status_text") or "").strip()
    return (
        "\ucc38\uac00" in status_text
        and "\ubd88\ucc38" not in status_text
        and "\ubbf8\ucc38\uac00" not in status_text
    )


def roster_tier_from_riot_tier(tier: str | None) -> str | None:
    base = str(tier or "").split("\u00b7", 1)[0].strip()
    return scrim_db.normalize_roster_tier(base)


def roster_payload(
    entry: dict,
    applications: dict[int, dict],
    participation_history: dict[int, list[dict]] | None = None,
) -> dict:
    payload = dict(entry)
    roster_applied = roster_entry_is_applied(entry)
    user_id = entry.get("user_id")
    application = applications.get(user_id) if user_id else None
    is_approved = bool(application and application.get("status") == "APPROVED")
    is_applied = roster_applied or is_approved
    payload["tournament_status"] = "applied" if is_applied else "not_applied"
    payload["tournament_label"] = "\ub300\ud68c \ucc38\uac00" if is_applied else "\ub300\ud68c \ubbf8\ucc38\uac00"
    payload["applied_at"] = application.get("applied_at") if application else None
    events = (participation_history or {}).get(user_id, []) if user_id else []
    payload["participation_events"] = events
    payload["participation_count"] = sum(
        1 for event in events if event.get("status") == "APPROVED"
    )
    return payload


class TeamRecommendationInput(BaseModel):
    locked: dict[
        Literal["TOP", "JUG", "MID", "ADC", "SUP"], str | None
    ]
    limit: int = Field(default=12, ge=1, le=30)


class CompetitionInput(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    mode: Literal["auction", "tournament"]
    tournament_format: Literal[
        "single_elimination", "group_then_knockout"
    ] = "single_elimination"
    group_count: int = Field(default=2, ge=2, le=16)
    qualifiers_per_group: int = Field(default=2, ge=1, le=8)


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/riot.txt")
async def riot_verification():
    return FileResponse(ROOT / "static" / "riot.txt", media_type="text/plain")


@app.get("/team-simulator")
async def team_simulator_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/score-players")
async def score_players_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/team-register")
async def legacy_team_register_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/tournament")
async def tournament_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/participation")
async def participation_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/members")
async def members_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/mypage")
async def mypage():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/scrim")
async def scrim_management_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/competition-room")
async def competition_room_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/state")
async def get_state(scrim_auth: str | None = Cookie(default=None)):
    async with state_lock:
        apply_scrim_image_retention()
        store.save()
    result = engine.public_state(store.state, compute_viewer(scrim_auth))
    result["competition_registry"] = store.competition_summary()
    result["captain_presence"] = captain_presence()
    result["deployment"] = {
        "serverless": bool(os.getenv("VERCEL")),
        "persistent": store.persistent,
    }
    return result


@app.post("/api/competitions")
async def create_competition(data: CompetitionInput, request: Request):
    require_host(request)
    async with state_lock:
        competition = store.create_competition(data.name, data.mode)
        if data.mode == "tournament":
            tournament = competition["state"]["tournament"]
            tournament["format"] = data.tournament_format
            tournament["group_count"] = data.group_count
            tournament["qualifiers_per_group"] = data.qualifiers_per_group
            store.save()
    await broadcast()
    return {
        "id": competition["id"],
        "name": competition["name"],
        "mode": competition["mode"],
        "created_at": competition["created_at"],
    }


@app.post("/api/competitions/{competition_id}/select")
async def select_competition(competition_id: str, request: Request):
    require_host(request)
    try:
        async with state_lock:
            store.select_competition(competition_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast()
    return {"ok": True}


@app.delete("/api/competitions/{competition_id}")
async def delete_competition(competition_id: str, request: Request):
    require_host(request)
    try:
        async with state_lock:
            store.delete_competition(competition_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast()
    return {"ok": True}


@app.put("/api/participation/settings")
async def update_participation_settings(
    data: ParticipationSettingsInput, request: Request
):
    require_host(request)
    async with state_lock:
        store.state.setdefault("participation", {})
        store.state["participation"]["enabled"] = data.enabled
        store.state["participation"]["terms"] = data.terms
        store.state["participation"].setdefault("applications", [])
        store.save()
    await broadcast()
    return {"ok": True}


@app.post("/api/participation/apply")
async def apply_participation(
    data: ParticipationApplyInput, request: Request
):
    viewer = require_participant(request)
    if not data.terms_agreed:
        raise HTTPException(400, "약관 동의가 필요합니다.")
    async with state_lock:
        participation = store.state.setdefault(
            "participation",
            {"enabled": False, "terms": "", "applications": []},
        )
        if not participation.get("enabled"):
            raise HTTPException(409, "현재 참가 신청이 열려 있지 않습니다.")
        applications = participation.setdefault("applications", [])
        existing = next(
            (
                application
                for application in applications
                if application.get("user_id") == viewer.get("user_id")
            ),
            None,
        )
        applied_at = time.time()
        if existing:
            existing["applied_at"] = applied_at
            existing["terms_agreed"] = True
            existing.setdefault("status", "APPLIED")
        else:
            applications.append(
                {
                    "user_id": viewer["user_id"],
                    "name": viewer.get("name", ""),
                    "riot_id": viewer.get("riot_id", ""),
                    "terms_agreed": True,
                    "applied_at": applied_at,
                    "status": "APPLIED",
                }
            )
        competition = store.active_competition
        competition_id = competition["id"] if competition else "default"
        competition_name = competition["name"] if competition else store.state["settings"]["room_name"]
        with scrim_db.connect() as connection:
            scrim_db.record_competition_participation(
                connection,
                user_id=viewer["user_id"],
                competition_id=competition_id,
                competition_name=competition_name,
                applied_at=applied_at,
            )
        store.save()
    await broadcast()
    return {"ok": True}


@app.get("/api/participation/applications")
async def participation_applications(request: Request):
    require_host(request)
    participation = store.state.setdefault(
        "participation",
        {"enabled": False, "terms": "", "applications": []},
    )
    applications = {
        application["user_id"]: application
        for application in participation.get("applications", [])
    }
    with scrim_db.connect() as connection:
        users = [
            user
            for user in scrim_db.search_users(connection, "")
            if user["role"] != "ADMIN" and user.get("approved")
        ]
    applied = []
    not_applied = []
    for user in users:
        payload = {
            "id": user["id"],
            "name": user["name"],
            "riot_id": user["riot_id"],
            "approved": bool(user.get("approved", False)),
            "created_at": user["created_at"],
            "applied_at": applications.get(user["id"], {}).get("applied_at"),
            "participation_status": applications.get(user["id"], {}).get("status", "APPLIED"),
        }
        if user["id"] in applications:
            applied.append(payload)
        else:
            not_applied.append(payload)
    return {
        "enabled": bool(participation.get("enabled")),
        "applied": applied,
        "not_applied": not_applied,
    }


@app.patch("/api/participation/applications/{user_id}")
async def update_participation_application(
    user_id: int,
    data: ParticipationStatusInput,
    request: Request,
):
    require_host(request)
    changed_at = time.time()
    async with state_lock:
        competition = store.active_competition
        competition_id = competition["id"] if competition else "default"
        competition_name = competition["name"] if competition else store.state["settings"]["room_name"]
        participation = store.state.setdefault(
            "participation",
            {"enabled": False, "terms": "", "applications": []},
        )
        applications = participation.setdefault("applications", [])
        application = next(
            (item for item in applications if item.get("user_id") == user_id),
            None,
        )
        if application is None:
            raise HTTPException(404, "참가 신청 기록을 찾을 수 없습니다.")
        application["status"] = data.status
        if data.status == "APPROVED":
            application["approved_at"] = changed_at
        elif data.status == "CANCELLED":
            application["cancelled_at"] = changed_at
        with scrim_db.connect() as connection:
            try:
                record = scrim_db.set_competition_participation_status(
                    connection,
                    user_id=user_id,
                    competition_id=competition_id,
                    status=data.status,
                    changed_at=changed_at,
                )
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc
        store.save()
    await broadcast()
    return record


@app.get("/api/members")
async def list_members(request: Request, query: str = ""):
    require_host(request)
    participation = store.state.setdefault(
        "participation",
        {"enabled": False, "terms": "", "applications": []},
    )
    applications = {
        application["user_id"]: application
        for application in participation.get("applications", [])
    }
    with scrim_db.connect() as connection:
        users = scrim_db.search_users(connection, query)
    members = [member_participation_payload(user, applications) for user in users]
    stats_members = [
        member
        for member in members
        if member["role"] != "ADMIN" and member["approved"]
    ]
    return {
        "members": members,
        "stats": {
            "approved_members": len(stats_members),
            "applied": sum(
                1 for member in stats_members if member["participation_status"] == "applied"
            ),
            "not_applied": sum(
                1
                for member in stats_members
                if member["participation_status"] == "not_applied"
            ),
        },
    }


@app.get("/api/roster")
async def list_roster(
    request: Request,
    query: str = "",
    filter: str = "with_id",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=500),
):
    require_host(request)
    participation = store.state.setdefault(
        "participation",
        {"enabled": False, "terms": "", "applications": []},
    )
    applications = {
        application["user_id"]: application
        for application in participation.get("applications", [])
    }
    with scrim_db.connect() as connection:
        counts = scrim_db.roster_counts(connection)
        has_riot_id = None
        user_ids = None
        participation_status = None
        payment_status = None
        if filter == "with_id":
            has_riot_id = True
        elif filter == "without_id":
            has_riot_id = False
        elif filter == "applied":
            participation_status = "applied"
        elif filter == "not_applied":
            participation_status = "not_applied"
        elif filter == "applied_unpaid":
            participation_status = "applied"
            payment_status = "unpaid"
        total = scrim_db.count_roster_entries(
            connection,
            query=query,
            has_riot_id=has_riot_id,
            participation_status=participation_status,
            payment_status=payment_status,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        entries = scrim_db.list_roster_entries(
            connection,
            query=query,
            has_riot_id=has_riot_id,
            user_ids=user_ids,
            participation_status=participation_status,
            payment_status=payment_status,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        participation_rows = scrim_db.list_competition_participations(
            connection,
            {entry["user_id"] for entry in entries if entry.get("user_id")},
        )
        applied_unpaid_count = scrim_db.count_roster_entries(
            connection,
            participation_status="applied",
            payment_status="unpaid",
        )
    participation_history: dict[int, list[dict]] = {}
    for row in participation_rows:
        participation_history.setdefault(row["user_id"], []).append(row)
    return {
        "entries": [
            roster_payload(entry, applications, participation_history)
            for entry in entries
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
        "stats": {
            **counts,
            "applied": counts["applied"],
            "not_applied": max(0, counts["total"] - counts["applied"]),
            "applied_unpaid": applied_unpaid_count,
        },
    }


@app.post("/api/roster/import")
async def import_roster(data: RosterImportInput, request: Request):
    require_host(request)
    summary = {
        "total_rows": len(data.rows),
        "with_riot_id": 0,
        "without_riot_id": 0,
        "created_or_updated": 0,
        "accounts_issued": 0,
    }
    with scrim_db.connect() as connection:
        for row in data.rows:
            payload = row.model_dump(exclude_unset=True)
            source_row = payload.pop("source_row")
            if payload.get("riot_id"):
                summary["with_riot_id"] += 1
            else:
                summary["without_riot_id"] += 1
            entry = scrim_db.upsert_roster_entry(
                connection,
                source_row=source_row,
                **payload,
            )
            summary["created_or_updated"] += 1
            if entry.get("account_status") == "ISSUED":
                summary["accounts_issued"] += 1
    return summary


@app.post("/api/admin/setup-test-competitions")
async def setup_test_competitions(request: Request):
    require_host(request)
    now = time.time()
    with scrim_db.connect() as connection:
        roster_sync = scrim_db.sync_roster_from_approved_members(connection)
        rows = connection.execute(
            """
            SELECT id AS user_id, name, riot_id
            FROM users
            WHERE role = 'USER'
              AND approved = 1
              AND is_active = 1
            ORDER BY name ASC, riot_id ASC
            """
        ).fetchall()
        users = [dict(row) for row in rows]
        connection.execute("DELETE FROM member_competition_participations")
        for user in users:
            scrim_db.record_competition_participation(
                connection,
                user_id=user["user_id"],
                competition_id=TEST_COMPETITION_ID,
                competition_name="test1",
                applied_at=now,
            )
            scrim_db.set_competition_participation_status(
                connection,
                user_id=user["user_id"],
                competition_id=TEST_COMPETITION_ID,
                status="APPROVED",
                changed_at=now,
            )
        total_row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM users
            WHERE role = 'USER' AND approved = 1 AND is_active = 1
            """
        ).fetchone()
    applications = [
        {
            "user_id": user["user_id"],
            "name": user.get("name") or "",
            "riot_id": user.get("riot_id") or "",
            "terms_agreed": True,
            "applied_at": now,
            "approved_at": now,
            "status": "APPROVED",
        }
        for user in users
    ]
    async with state_lock:
        store.document = {
            "version": 2,
            "active_competition_id": TEST2_COMPETITION_ID,
            "competitions": [
                {
                    "id": TEST_COMPETITION_ID,
                    "name": "test1",
                    "mode": "tournament",
                    "created_at": now,
                    "state": score_competition_state(
                        "test1",
                        participation_enabled=False,
                        applications=applications,
                    ),
                },
                {
                    "id": TEST2_COMPETITION_ID,
                    "name": "test2",
                    "mode": "tournament",
                    "created_at": now + 1,
                    "state": score_competition_state(
                        "test2",
                        participation_enabled=True,
                        applications=[],
                    ),
                },
            ],
        }
        store.save()
    await broadcast()
    return {
        "ok": True,
        "roster_total": dict(total_row)["count"],
        "account_issued": len(users),
        "test_approved": len(users),
        "test2_applications": 0,
        "roster_added": roster_sync["added"],
        "roster_linked": roster_sync["linked"],
    }


@app.post("/api/roster/riot/preview")
async def preview_roster_riot(data: RosterRiotLookupInput, request: Request):
    require_host(request)
    try:
        riot = await lookup_kr_player(data.riot_id)
    except RiotApiError as exc:
        raise HTTPException(400, str(exc)) from exc
    tier = roster_tier_from_riot_tier(riot.get("tier"))
    score_source = {
        "tier": tier,
        "preferred_lines": data.preferred_lines,
        "top_adjustment": data.top_adjustment,
        "game_count_adjustment": data.game_count_adjustment,
    }
    return {
        "name": riot.get("name"),
        "riot_id": riot.get("riot_id"),
        "riot_tier": riot.get("tier"),
        "tier": tier,
        "scores": scrim_db.calculate_roster_scores(score_source),
    }


@app.patch("/api/roster/{roster_id}")
async def update_roster_entry(roster_id: int, data: RosterEntryInput, request: Request):
    require_host(request)
    payload = data.model_dump(exclude_unset=True)
    try:
        with scrim_db.connect() as connection:
            entry = scrim_db.update_roster_entry(connection, roster_id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    participation = store.state.setdefault(
        "participation",
        {"enabled": False, "terms": "", "applications": []},
    )
    applications = {
        application["user_id"]: application
        for application in participation.get("applications", [])
    }
    with scrim_db.connect() as connection:
        participation_rows = scrim_db.list_competition_participations(
            connection,
            {entry["user_id"]} if entry.get("user_id") else set(),
        )
    participation_history: dict[int, list[dict]] = {}
    for row in participation_rows:
        participation_history.setdefault(row["user_id"], []).append(row)
    return roster_payload(entry, applications, participation_history)


@app.patch("/api/roster")
async def bulk_update_roster(data: RosterBulkUpdateInput, request: Request):
    require_host(request)
    try:
        with scrim_db.connect() as connection:
            for row in data.rows:
                scrim_db.update_roster_entry(
                    connection,
                    row.id,
                    row.model_dump(exclude={"id"}, exclude_unset=True),
                )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "updated": len(data.rows)}


@app.put("/api/settings")
async def update_settings(data: SettingsInput, request: Request):
    require_host(request)
    async with state_lock:
        if store.state["auction"]["status"] not in ("setup", "finished"):
            raise HTTPException(409, "경매 진행 중에는 설정을 바꿀 수 없습니다.")
        store.state["settings"] = data.model_dump()
        store.save()
    await broadcast()
    return engine.public_state(store.state)


@app.post("/api/captains")
async def create_captain(data: CaptainInput, request: Request):
    require_host(request)
    with scrim_db.connect() as connection:
        user = scrim_db.get_user_by_riot_id(connection, data.riot_id)
    if user is None:
        raise HTTPException(
            400, "해당 Riot ID로 가입된 계정이 없습니다. 먼저 회원가입해야 합니다."
        )
    async with state_lock:
        if store.state["auction"]["status"] != "setup":
            raise HTTPException(409, "경매 시작 후에는 팀장을 추가할 수 없습니다.")
        captain = engine.add_captain(
            store.state, data.player_id, data.budget, user["id"]
        )
        store.save()
    await broadcast()
    return {key: value for key, value in captain.items() if key != "user_id"}


@app.delete("/api/captains/{captain_id}")
async def delete_captain(captain_id: str, request: Request):
    require_host(request)
    async with state_lock:
        if store.state["auction"]["status"] != "setup":
            raise HTTPException(409, "경매 시작 후에는 팀장을 삭제할 수 없습니다.")
        before = len(store.state["captains"])
        removed = next(
            (c for c in store.state["captains"] if c["id"] == captain_id),
            None,
        )
        store.state["captains"] = [
            c for c in store.state["captains"] if c["id"] != captain_id
        ]
        if len(store.state["captains"]) == before:
            raise HTTPException(404, "팀장을 찾을 수 없습니다.")
        player = next(
            (
                p
                for p in store.state["players"]
                if removed and p["id"] == removed.get("player_id")
            ),
            None,
        )
        if player:
            player["status"] = "waiting"
            player["sold_to"] = None
            player["sold_amount"] = None
        store.save()
    await broadcast()
    return {"ok": True}


@app.post("/api/players")
async def create_player(data: PlayerInput, request: Request):
    require_host(request)
    async with state_lock:
        if store.state["auction"]["status"] != "setup":
            raise HTTPException(409, "경매 시작 후에는 참가자를 추가할 수 없습니다.")
        player = engine.add_player(store.state, **data.model_dump())
        store.save()
    await broadcast()
    return player


@app.post("/api/players/riot")
async def create_riot_player(data: RiotPlayerInput, request: Request):
    require_host(request)
    try:
        riot = await lookup_kr_player(data.riot_id)
    except RiotApiError as exc:
        raise HTTPException(400, str(exc)) from exc
    async with state_lock:
        if store.state["auction"]["status"] != "setup":
            raise HTTPException(409, "경매 시작 후에는 참가자를 추가할 수 없습니다.")
        player = engine.add_player(
            store.state,
            **riot,
            primary_position=data.primary_position,
            secondary_position=data.secondary_position,
            extra_positions=data.extra_positions,
            score=data.score,
            secondary_score=data.secondary_score,
        )
        store.save()
    await broadcast()
    return player


@app.post("/api/players/riot/preview")
async def preview_riot_player(data: RiotPlayerInput, request: Request):
    require_host(request)
    try:
        return await lookup_kr_player(data.riot_id)
    except RiotApiError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/players/{player_id}")
async def delete_player(player_id: str, request: Request):
    require_host(request)
    async with state_lock:
        if store.state["auction"]["status"] != "setup":
            raise HTTPException(409, "경매 시작 후에는 참가자를 삭제할 수 없습니다.")
        registered = any(
            player_id in team["members"].values()
            and team["status"] != "rejected"
            for team in store.state["tournament"]["teams"]
        )
        if registered:
            raise HTTPException(409, "점수제 팀에 등록된 참가자는 삭제할 수 없습니다.")
        before = len(store.state["players"])
        store.state["players"] = [
            p for p in store.state["players"] if p["id"] != player_id
        ]
        if len(store.state["players"]) == before:
            raise HTTPException(404, "참가자를 찾을 수 없습니다.")
        store.save()
    await broadcast()
    return {"ok": True}


@app.patch("/api/players/{player_id}/score")
async def update_player_score(
    player_id: str, data: PlayerScoreInput, request: Request
):
    require_host(request)
    try:
        async with state_lock:
            player = engine.update_player_score(
                store.state, player_id, data.score, data.secondary_score
            )
            store.save()
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast()
    return player


@app.put("/api/tournament/settings")
async def update_tournament_settings(
    data: TournamentSettingsInput, request: Request
):
    require_host(request)
    async with state_lock:
        tournament = store.state["tournament"]
        if tournament["status"] in ("running", "finished"):
            raise HTTPException(409, "본선 시작 후에는 대회 형식을 바꿀 수 없습니다.")
        tournament["score_limit"] = data.score_limit
        changed = (
            tournament.get("format") != data.format
            or tournament.get("group_count") != data.group_count
            or tournament.get("qualifiers_per_group") != data.qualifiers_per_group
        )
        tournament["format"] = data.format
        tournament["group_count"] = data.group_count
        tournament["qualifiers_per_group"] = data.qualifiers_per_group
        if changed and tournament["status"] == "group":
            tournament["status"] = "registration"
            tournament["groups"] = []
            tournament["qualified_team_ids"] = []
        store.save()
    await broadcast()
    return {"ok": True}


@app.post("/api/tournament/recommend")
async def recommend_tournament_team(data: TeamRecommendationInput):
    try:
        return {
            "recommendations": engine.recommend_team_combinations(
                store.state,
                data.locked,
                store.state["tournament"]["score_limit"],
                data.limit,
            )
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/tournament/teams")
async def register_tournament_team(
    data: TournamentTeamInput, request: Request
):
    viewer = require_participant(request)
    try:
        async with state_lock:
            team = engine.register_tournament_team(
                store.state,
                data.name,
                data.members,
                data.registration_pin,
                viewer.get("user_id"),
            )
            store.save()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast()
    return {
        key: value
        for key, value in team.items()
        if key not in ("registration_pin", "created_by_user_id")
    }


@app.post("/api/tournament/teams/{team_id}/approval")
async def approve_tournament_team(
    team_id: str, data: TeamApprovalInput, request: Request
):
    require_host(request)
    return await mutate(
        lambda: engine.approve_tournament_team(
            store.state, team_id, data.approved
        )
    )


@app.delete("/api/tournament/teams/{team_id}")
async def delete_tournament_team(team_id: str, request: Request):
    require_host(request)
    return await mutate(
        lambda: engine.delete_tournament_team(store.state, team_id)
    )


@app.post("/api/tournament/start")
async def start_tournament(request: Request):
    require_host(request)
    return await mutate(lambda: engine.start_tournament(store.state))


@app.put("/api/tournament/groups/qualifiers")
async def update_group_qualifiers(data: GroupQualifiersInput, request: Request):
    require_host(request)
    return await mutate(
        lambda: engine.set_group_qualifiers(
            store.state, data.group_index, data.team_ids
        )
    )


@app.post("/api/tournament/groups/start-knockout")
async def start_group_knockout(request: Request):
    require_host(request)
    return await mutate(lambda: engine.start_group_knockout(store.state))


@app.put("/api/tournament/bracket")
async def save_custom_bracket(data: CustomBracketInput, request: Request):
    require_host(request)
    return await mutate(
        lambda: engine.set_custom_bracket(
            store.state, [round_.model_dump() for round_ in data.rounds]
        )
    )


@app.post("/api/tournament/winner")
async def select_tournament_winner(
    data: MatchWinnerInput, request: Request
):
    require_host(request)
    return await mutate(
        lambda: engine.select_match_winner(
            store.state,
            data.round_index,
            data.match_index,
            data.team_id,
        )
    )


def scrim_result_payload(data: ScrimResultInput) -> dict:
    if data.team_a_id == data.team_b_id:
        raise HTTPException(400, "서로 다른 두 팀을 선택해 주세요.")
    if data.best_of not in (3, 5):
        raise HTTPException(400, "경기 방식은 BO3 또는 BO5만 선택할 수 있습니다.")
    winning_score = data.best_of // 2 + 1
    high_score = max(data.team_a_score, data.team_b_score)
    low_score = min(data.team_a_score, data.team_b_score)
    if high_score != winning_score or low_score >= winning_score:
        raise HTTPException(
            400,
            f"BO{data.best_of} 결과는 승리 팀이 {winning_score}세트를 이기도록 입력해 주세요.",
        )
    return {
        **data.model_dump(),
        "winner_team_id": (
            data.team_a_id
            if data.team_a_score > data.team_b_score
            else data.team_b_id
        ),
    }


def normalize_image_url(value: str | None) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "이미지 URL은 http 또는 https 주소여야 합니다.")
    return normalized


def blob_token_and_store_id() -> tuple[str, str]:
    token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "Vercel Blob 저장소가 아직 연결되지 않았습니다.")
    parts = token.split("_")
    store_id = parts[3] if len(parts) > 3 else ""
    if not store_id:
        raise HTTPException(503, "Vercel Blob 토큰 형식이 올바르지 않습니다.")
    return token, store_id


def blob_api_request(path: str, *, method: str, body: bytes, headers: dict[str, str]) -> dict | None:
    token, store_id = blob_token_and_store_id()
    request = urllib.request.Request(
        f"{BLOB_API_URL}{path}",
        data=body,
        headers={
            "authorization": f"Bearer {token}",
            "x-vercel-blob-store-id": store_id,
            "x-api-version": "12",
            "x-api-blob-request-id": f"{store_id}:{time.time()}:{uuid.uuid4().hex}",
            "x-api-blob-request-attempt": "0",
            **headers,
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(exc.code, f"Vercel Blob 요청 실패: {message or exc.reason}") from exc
    except OSError as exc:
        raise HTTPException(502, f"Vercel Blob 연결 실패: {exc}") from exc


def upload_result_image_to_blob(*, team_id: str, filename: str, content_type: str, data: bytes) -> dict:
    extension = {
        "image/webp": "webp",
        "image/jpeg": "jpg",
        "image/png": "png",
    }.get(content_type)
    if extension is None:
        raise HTTPException(400, "이미지는 JPG, PNG, WebP만 업로드할 수 있습니다.")
    safe_team_id = "".join(char for char in team_id if char.isalnum() or char in ("-", "_"))[:80]
    safe_name = Path(filename or f"result.{extension}").stem[:40] or "result"
    pathname = f"scrim-results/{safe_team_id}/{uuid.uuid4().hex}-{safe_name}.{extension}"
    query = urllib.parse.urlencode({"pathname": pathname})
    response = blob_api_request(
        f"/?{query}",
        method="PUT",
        body=data,
        headers={
            "content-type": content_type,
            "x-content-length": str(len(data)),
            "x-vercel-blob-access": "public",
            "x-add-random-suffix": "0",
            "x-content-type": content_type,
        },
    )
    return response or {}


def delete_result_image_from_blob(url: str | None) -> None:
    if not url or not os.getenv("BLOB_READ_WRITE_TOKEN"):
        return
    try:
        blob_api_request(
            "/delete",
            method="POST",
            body=json.dumps({"urls": [url]}).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
    except HTTPException:
        return


def validate_scrim_result_image(data: ScrimResultInput, existing_result: dict | None = None) -> None:
    data.image_url = normalize_image_url(data.image_url)
    if not data.image_url:
        data.image_size_bytes = None
        data.image_pathname = None
        return
    if data.image_size_bytes is not None and data.image_size_bytes > SCRIM_RESULT_IMAGE_MAX_BYTES:
        raise HTTPException(400, "대회 경기 결과 이미지는 1MB 이하로 압축해서 올려주세요.")
    if existing_result and existing_result.get("image_url") == data.image_url:
        return
    active_images = [
        item
        for item in store.state.setdefault("scrim_results", [])
        if item.get("team_id") == data.team_id
        and item.get("image_url")
        and not item.get("image_archived")
        and (not existing_result or item.get("id") != existing_result.get("id"))
    ]
    if len(active_images) >= SCRIM_RESULT_IMAGE_MAX_PER_TEAM:
        raise HTTPException(
            400,
            f"팀별 결과 이미지는 최대 {SCRIM_RESULT_IMAGE_MAX_PER_TEAM}개까지만 유지합니다. 오래된 이미지를 먼저 정리해주세요.",
        )


def apply_scrim_image_retention() -> None:
    now = time.time()
    retention_seconds = SCRIM_RESULT_IMAGE_RETENTION_DAYS * 24 * 60 * 60
    by_team: dict[str, list[dict]] = {}
    for result in store.state.setdefault("scrim_results", []):
        if not result.get("image_url"):
            continue
        result["image_archived"] = False
        age_base = result.get("created_at") or result.get("updated_at") or now
        if now - float(age_base) > retention_seconds:
            result["image_archived"] = True
            delete_result_image_from_blob(result.get("image_url"))
            result["image_deleted_at"] = result.get("image_deleted_at") or now
            result["image_url"] = None
        by_team.setdefault(result.get("team_id", ""), []).append(result)
    for results in by_team.values():
        active = [item for item in results if not item.get("image_archived")]
        active.sort(key=lambda item: item.get("created_at") or item.get("updated_at") or 0, reverse=True)
        for item in active[SCRIM_RESULT_IMAGE_MAX_PER_TEAM:]:
            item["image_archived"] = True
            delete_result_image_from_blob(item.get("image_url"))
            item["image_deleted_at"] = item.get("image_deleted_at") or now
            item["image_url"] = None


def require_scrim_result_manager(viewer: dict, team_id: str) -> dict:
    team = next(
        (
            item
            for item in store.state["tournament"]["teams"]
            if item["id"] == team_id
        ),
        None,
    )
    if team is None:
        raise HTTPException(404, "팀을 찾을 수 없습니다.")
    team_player_ids = set(team.get("members", {}).values())
    viewer_riot_id = str(viewer.get("riot_id") or "").casefold()
    belongs_to_team = any(
        player["id"] in team_player_ids
        and str(player.get("riot_id") or "").casefold() == viewer_riot_id
        for player in store.state["players"]
    )
    if not (
        viewer["role"] == "host"
        or team.get("created_by_user_id") == viewer.get("user_id")
        or belongs_to_team
    ):
        raise HTTPException(403, "해당 팀원 또는 강사님만 결과를 등록할 수 있습니다.")
    return team


@app.post("/api/scrim/results")
async def create_scrim_result(data: ScrimResultInput, request: Request):
    viewer = require_participant(request)
    async with state_lock:
        permission_granted = False
        try:
            require_scrim_result_manager(viewer, data.team_a_id)
            permission_granted = True
        except HTTPException as error:
            if error.status_code == 404:
                raise
        try:
            require_scrim_result_manager(viewer, data.team_b_id)
            permission_granted = True
        except HTTPException as error:
            if error.status_code == 404:
                raise
        if not permission_granted:
            raise HTTPException(403, "참가 팀원 또는 강사님만 결과를 등록할 수 있습니다.")
        result = {
            "id": uuid.uuid4().hex,
            **scrim_result_payload(data),
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        store.state.setdefault("scrim_results", []).append(result)
        store.save()
    await broadcast()
    return result


@app.put("/api/scrim/results/{result_id}")
async def update_scrim_result(
    result_id: str, data: ScrimResultInput, request: Request
):
    viewer = require_participant(request)
    async with state_lock:
        result = next(
            (
                item
                for item in store.state.setdefault("scrim_results", [])
                if item["id"] == result_id
            ),
            None,
        )
        if result is None:
            raise HTTPException(404, "결과를 찾을 수 없습니다.")
        original_team_ids = {result.get("team_a_id"), result.get("team_b_id")}
        permission_granted = False
        try:
            require_scrim_result_manager(viewer, result["team_a_id"])
            permission_granted = True
        except HTTPException as error:
            if error.status_code == 404:
                raise
        try:
            require_scrim_result_manager(viewer, result["team_b_id"])
            permission_granted = True
        except HTTPException as error:
            if error.status_code == 404:
                raise
        if not permission_granted:
            raise HTTPException(403, "참가 팀원 또는 강사님만 결과를 수정할 수 있습니다.")
        if {data.team_a_id, data.team_b_id} != original_team_ids:
            raise HTTPException(400, "등록된 경기의 팀은 변경할 수 없습니다.")
        result.update(scrim_result_payload(data))
        result["updated_at"] = time.time()
        store.save()
    await broadcast()
    return result


async def mutate(action):
    try:
        async with state_lock:
            result = action()
            store.save()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast()
    return result or {"ok": True}


@app.post("/api/auction/start")
async def start(request: Request):
    require_host(request)
    return await mutate(lambda: engine.start_auction(store.state))


@app.post("/api/auction/reauction")
async def reauction(request: Request):
    require_host(request)
    return await mutate(lambda: engine.start_reauction(store.state))


@app.post("/api/auction/timer/start")
async def start_auction_timer(request: Request):
    require_host(request)
    return await mutate(lambda: engine.start_timer(store.state))


@app.post("/api/auction/bid")
async def captain_bid(data: BidInput, request: Request):
    viewer = require_captain(request)
    return await mutate(
        lambda: engine.place_bid(
            store.state, viewer["captain_id"], data.amount
        )
    )


@app.post("/api/auction/pause")
async def pause(request: Request):
    require_host(request)
    return await mutate(lambda: engine.pause(store.state))


@app.post("/api/auction/resume")
async def resume(request: Request):
    require_host(request)
    return await mutate(lambda: engine.resume(store.state))


@app.post("/api/reset")
async def reset(request: Request):
    require_host(request)
    async with state_lock:
        store.reset()
    await broadcast()
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.add(websocket)
    viewer = compute_viewer(websocket.cookies.get(SCRIM_AUTH_COOKIE))
    connection_viewers[websocket] = viewer
    await broadcast()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections.discard(websocket)
        connection_viewers.pop(websocket, None)
        await broadcast()
