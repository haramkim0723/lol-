from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import (
    Cookie,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine
from .riot import RiotApiError, lookup_kr_player
from .store import JsonStore


ROOT = Path(__file__).parent
store = JsonStore()
state_lock = asyncio.Lock()
connections: set[WebSocket] = set()
connection_viewers: dict[WebSocket, dict] = {}


def _sign(payload: str) -> str:
    secret = os.getenv("SESSION_SECRET", "local-development-secret").encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def make_session(role: str, captain_id: str | None = None) -> str:
    raw = json.dumps(
        {"role": role, "captain_id": captain_id, "nonce": secrets.token_hex(4)},
        separators=(",", ":"),
    )
    payload = base64.urlsafe_b64encode(raw.encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_session(token: str | None) -> dict:
    fallback = {
        "role": "spectator",
        "captain_id": None,
        "authenticated": False,
    }
    if not token or "." not in token:
        return fallback
    payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(payload)):
        return fallback
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except (ValueError, json.JSONDecodeError):
        return fallback
    if data.get("role") not in ("host", "captain", "spectator"):
        return fallback
    return {
        "role": data["role"],
        "captain_id": data.get("captain_id"),
        "authenticated": True,
    }


def require_host(request: Request) -> dict:
    viewer = read_session(request.cookies.get("auction_auth"))
    if viewer["role"] != "host":
        raise HTTPException(403, "강사님만 사용할 수 있는 기능입니다.")
    return viewer


def require_captain(request: Request) -> dict:
    viewer = read_session(request.cookies.get("auction_auth"))
    if viewer["role"] != "captain" or not viewer["captain_id"]:
        raise HTTPException(403, "팀장으로 입장해야 입찰할 수 있습니다.")
    return viewer


def require_authenticated(request: Request) -> dict:
    viewer = read_session(request.cookies.get("auction_auth"))
    if not viewer["authenticated"]:
        raise HTTPException(401, "먼저 입장해 주세요.")
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
    task = None
    if not os.getenv("VERCEL"):
        task = asyncio.create_task(timer_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="LoL Auction", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


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
    pin: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]+$")


class PlayerInput(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    riot_id: str = Field(default="", max_length=80)
    tier: str = Field(default="UNRANKED", max_length=40)
    primary_position: Literal["TOP", "JUG", "MID", "ADC", "SUP"]
    secondary_position: Literal["TOP", "JUG", "MID", "ADC", "SUP"] | None = None
    profile_icon_url: str | None = None
    score: int = Field(default=0, ge=0, le=1000)


class PlayerScoreInput(BaseModel):
    score: int = Field(ge=0, le=1000)


class RiotPlayerInput(BaseModel):
    riot_id: str = Field(min_length=3, max_length=80)
    primary_position: Literal["TOP", "JUG", "MID", "ADC", "SUP"]
    secondary_position: Literal["TOP", "JUG", "MID", "ADC", "SUP"] | None = None
    score: int = Field(default=0, ge=0, le=1000)


class BidInput(BaseModel):
    amount: int = Field(ge=0, le=10_000_000)


class LoginInput(BaseModel):
    role: Literal["host", "captain", "spectator"]
    pin: str = ""
    captain_id: str | None = None


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


class TeamRecommendationInput(BaseModel):
    locked: dict[
        Literal["TOP", "JUG", "MID", "ADC", "SUP"], str | None
    ]
    limit: int = Field(default=12, ge=1, le=30)


class CompetitionInput(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    mode: Literal["auction", "tournament"]


class TeacherPinChangeInput(BaseModel):
    current_pin: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]+$")
    new_pin: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]+$")


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


@app.get("/api/state")
async def get_state(auction_auth: str | None = Cookie(default=None)):
    result = engine.public_state(store.state, read_session(auction_auth))
    result["competition_registry"] = store.competition_summary()
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


@app.post("/api/login")
async def login(data: LoginInput, response: Response):
    if data.role == "host":
        if not store.verify_teacher_pin(data.pin):
            raise HTTPException(401, "강사님 PIN이 올바르지 않습니다.")
        viewer = {"role": "host", "captain_id": None, "authenticated": True}
    elif data.role == "captain":
        if (
            store.active_competition is None
            or store.active_competition.get("mode", "auction") != "auction"
        ):
            raise HTTPException(
                400, "팀장 입장은 경매 대회에서만 사용할 수 있습니다."
            )
        captain = next(
            (c for c in store.state["captains"] if c["id"] == data.captain_id),
            None,
        )
        if captain is None or not secrets.compare_digest(
            captain.get("pin", ""), data.pin
        ):
            raise HTTPException(401, "팀장 또는 PIN이 올바르지 않습니다.")
        viewer = {
            "role": "captain",
            "captain_id": captain["id"],
            "authenticated": True,
        }
    else:
        viewer = {
            "role": "spectator",
            "captain_id": None,
            "authenticated": True,
        }
    response.set_cookie(
        "auction_auth",
        make_session(viewer["role"], viewer["captain_id"]),
        httponly=True,
        samesite="lax",
        secure=bool(os.getenv("VERCEL")),
    )
    return viewer


@app.post("/api/teacher/pin")
async def change_teacher_pin(
    data: TeacherPinChangeInput, request: Request, response: Response
):
    require_host(request)
    if not store.verify_teacher_pin(data.current_pin):
        raise HTTPException(401, "현재 강사님 PIN이 올바르지 않습니다.")
    if data.current_pin == data.new_pin:
        raise HTTPException(400, "새 PIN은 현재 PIN과 달라야 합니다.")
    async with state_lock:
        store.change_teacher_pin(data.new_pin)
    response.delete_cookie("auction_auth")
    return {"ok": True, "reauthenticate": True}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie("auction_auth")
    return {"ok": True}


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
    async with state_lock:
        if store.state["auction"]["status"] != "setup":
            raise HTTPException(409, "경매 시작 후에는 팀장을 추가할 수 없습니다.")
        captain = engine.add_captain(
            store.state, data.player_id, data.budget, data.pin
        )
        store.save()
    await broadcast()
    return {key: value for key, value in captain.items() if key != "pin"}


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
                store.state, player_id, data.score
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
    try:
        async with state_lock:
            team = engine.register_tournament_team(
            store.state,
            data.name,
            data.members,
            data.registration_pin,
            )
            store.save()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast()
    return {key: value for key, value in team.items() if key != "registration_pin"}


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
    viewer = read_session(websocket.cookies.get("auction_auth"))
    connection_viewers[websocket] = viewer
    await websocket.send_json(
        {
            "type": "state",
            "data": {
                **engine.public_state(store.state, viewer),
                "competition_registry": store.competition_summary(),
            },
        }
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections.discard(websocket)
        connection_viewers.pop(websocket, None)
