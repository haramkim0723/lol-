from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import (
    Cookie,
    FastAPI,
    HTTPException,
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
    if user["role"] == "ADMIN":
        return {
            "role": "host",
            "captain_id": None,
            "authenticated": True,
            "approved": True,
            "user_id": user["id"],
            "riot_id": user["riot_id"],
            "secondary_riot_id": user.get("secondary_riot_id"),
            "nickname": user.get("nickname"),
            "name": user["name"],
        }
    captain = next(
        (
            c
            for c in store.state["captains"]
            if c.get("user_id") == user["id"]
        ),
        None,
    )
    if captain:
        return {
            "role": "captain",
            "captain_id": captain["id"],
            "authenticated": True,
            "approved": True,
            "user_id": user["id"],
            "riot_id": user["riot_id"],
            "secondary_riot_id": user.get("secondary_riot_id"),
            "nickname": user.get("nickname"),
            "name": user["name"],
        }
    if user.get("approved"):
        return {
            "role": "participant",
            "captain_id": None,
            "authenticated": True,
            "approved": True,
            "user_id": user["id"],
            "riot_id": user["riot_id"],
            "secondary_riot_id": user.get("secondary_riot_id"),
            "nickname": user.get("nickname"),
            "name": user["name"],
        }
    return {
        "role": "spectator",
        "captain_id": None,
        "authenticated": True,
        "approved": False,
        "user_id": user["id"],
        "riot_id": user["riot_id"],
        "secondary_riot_id": user.get("secondary_riot_id"),
        "nickname": user.get("nickname"),
        "name": user["name"],
    }


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
    score: int = Field(default=0, ge=0, le=1000)
    secondary_score: int | None = Field(default=None, ge=0, le=1000)


class BidInput(BaseModel):
    amount: int = Field(ge=0, le=10_000_000)


class TournamentSettingsInput(BaseModel):
    score_limit: int = Field(ge=0, le=5000)


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


class ScrimResultInput(BaseModel):
    team_id: str
    match_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    opponent_team_name: str = Field(min_length=1, max_length=100)
    our_score: int = Field(ge=0, le=99)
    opponent_score: int = Field(ge=0, le=99)
    memo: str | None = Field(default=None, max_length=500)


class ParticipationSettingsInput(BaseModel):
    enabled: bool
    terms: str = Field(min_length=1, max_length=2000)


class ParticipationApplyInput(BaseModel):
    terms_agreed: bool


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
    payload["applied_at"] = application.get("applied_at") if application else None
    return payload


class TeamRecommendationInput(BaseModel):
    locked: dict[
        Literal["TOP", "JUG", "MID", "ADC", "SUP"], str | None
    ]
    limit: int = Field(default=12, ge=1, le=30)


class CompetitionInput(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    mode: Literal["auction", "tournament"]


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


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


@app.get("/api/state")
async def get_state(scrim_auth: str | None = Cookie(default=None)):
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
        if existing:
            existing["applied_at"] = time.time()
            existing["terms_agreed"] = True
        else:
            applications.append(
                {
                    "user_id": viewer["user_id"],
                    "name": viewer.get("name", ""),
                    "riot_id": viewer.get("riot_id", ""),
                    "terms_agreed": True,
                    "applied_at": time.time(),
                }
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
            score=data.score,
            secondary_score=data.secondary_score,
        )
        store.save()
    await broadcast()
    return player


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
        if store.state["tournament"]["status"] != "registration":
            raise HTTPException(409, "토너먼트 시작 후에는 제한을 바꿀 수 없습니다.")
        store.state["tournament"]["score_limit"] = data.score_limit
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
    result = "DRAW"
    if data.our_score > data.opponent_score:
        result = "WIN"
    elif data.our_score < data.opponent_score:
        result = "LOSE"
    return {
        **data.model_dump(),
        "result": result,
    }


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
        require_scrim_result_manager(viewer, data.team_id)
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
        require_scrim_result_manager(viewer, result["team_id"])
        if data.team_id != result["team_id"]:
            raise HTTPException(400, "결과의 팀은 변경할 수 없습니다.")
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
