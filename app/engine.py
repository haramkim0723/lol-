from __future__ import annotations

import random
import time
import uuid
from copy import deepcopy
from itertools import product
from typing import Any


POSITIONS = ("TOP", "JUG", "MID", "ADC", "SUP")


def new_state() -> dict[str, Any]:
    return {
        "settings": {
            "room_name": "소환사의 협곡 경매",
            "countdown_seconds": 20,
            "minimum_bid": 10,
            "bid_increment": 10,
            "extension_trigger_seconds": 5,
            "extension_seconds": 5,
        },
        "captains": [],
        "players": [],
        "auction": {
            "status": "setup",
            "queue": [],
            "unsold": [],
            "current_player_id": None,
            "highest_bid": None,
            "deadline": None,
            "paused_remaining": None,
            "round": 1,
            "history": [],
        },
    }


def public_state(
    state: dict[str, Any], viewer: dict[str, Any] | None = None
) -> dict[str, Any]:
    result = deepcopy(state)
    for captain in result["captains"]:
        captain.pop("pin", None)
    now = time.time()
    deadline = result["auction"].get("deadline")
    result["server_time"] = now
    result["auction"]["remaining_seconds"] = (
        max(0, deadline - now) if deadline is not None else None
    )
    result["viewer"] = viewer or {"role": "spectator", "captain_id": None}
    return result


def add_captain(
    state: dict[str, Any], player_id: str, budget: int, pin: str
) -> dict[str, Any]:
    player = next(
        (item for item in state["players"] if item["id"] == player_id), None
    )
    if player is None:
        raise ValueError("팀장으로 지정할 참가자를 찾을 수 없습니다.")
    if player["status"] != "waiting":
        raise ValueError("이미 팀장이거나 배정된 참가자입니다.")
    captain = {
        "id": uuid.uuid4().hex,
        "name": player["name"],
        "player_id": player_id,
        "initial_budget": budget,
        "remaining_budget": budget,
        "pin": pin,
        "team": {position: None for position in POSITIONS},
        "bench": [],
    }
    captain["team"][player["primary_position"]] = player_id
    player["status"] = "captain"
    player["sold_to"] = captain["id"]
    player["sold_amount"] = 0
    state["captains"].append(captain)
    return captain


def add_player(
    state: dict[str, Any],
    name: str,
    riot_id: str,
    tier: str,
    primary_position: str,
    secondary_position: str | None = None,
    profile_icon_url: str | None = None,
    score: int = 0,
) -> dict[str, Any]:
    player = {
        "id": uuid.uuid4().hex,
        "name": name.strip(),
        "riot_id": riot_id.strip(),
        "tier": tier.strip() or "UNRANKED",
        "primary_position": primary_position,
        "secondary_position": secondary_position or None,
        "profile_icon_url": profile_icon_url,
        "score": score,
        "status": "waiting",
        "sold_to": None,
        "sold_amount": None,
        "unsold_count": 0,
    }
    state["players"].append(player)
    return player


def recommend_completions(
    state: dict[str, Any],
    locked: dict[str, str | None],
    target_score: int,
    limit: int = 12,
) -> list[dict[str, Any]]:
    players = state["players"]
    by_id = {player["id"]: player for player in players}
    selected_ids = [player_id for player_id in locked.values() if player_id]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("한 참가자를 여러 포지션에 중복 배치할 수 없습니다.")

    lineup: dict[str, dict[str, Any]] = {}
    for position, player_id in locked.items():
        if not player_id:
            continue
        player = by_id.get(player_id)
        if player is None:
            raise ValueError("고정 참가자를 찾을 수 없습니다.")
        if position not in (player["primary_position"], player["secondary_position"]):
            raise ValueError(
                f'{player["name"]} 님은 {position} 포지션으로 배치할 수 없습니다.'
            )
        lineup[position] = player

    empty_positions = [position for position in POSITIONS if position not in lineup]
    if not empty_positions:
        return [_score_lineup(lineup, target_score)]

    candidate_lists: list[list[tuple[dict[str, Any], int]]] = []
    for position in empty_positions:
        candidates = []
        for player in players:
            if player["id"] in selected_ids:
                continue
            if player["primary_position"] == position:
                candidates.append((player, 0))
            elif player.get("secondary_position") == position:
                candidates.append((player, 1))
        if not candidates:
            raise ValueError(f"{position}에 배치 가능한 참가자가 없습니다.")
        candidate_lists.append(candidates)

    recommendations: list[dict[str, Any]] = []
    for choices in product(*candidate_lists):
        chosen_players = [choice[0] for choice in choices]
        chosen_ids = [player["id"] for player in chosen_players]
        if len(chosen_ids) != len(set(chosen_ids)):
            continue
        completed = dict(lineup)
        fit_penalty = 0
        for position, (player, penalty) in zip(empty_positions, choices):
            completed[position] = player
            fit_penalty += penalty
        recommendation = _score_lineup(completed, target_score)
        recommendation["fit_penalty"] = fit_penalty
        recommendations.append(recommendation)

    recommendations.sort(
        key=lambda item: (
            item["score_difference"],
            item["fit_penalty"],
            -item["total_score"],
            tuple(item["lineup"][position]["name"] for position in POSITIONS),
        )
    )
    return recommendations[:limit]


def _score_lineup(
    lineup: dict[str, dict[str, Any]], target_score: int
) -> dict[str, Any]:
    total_score = sum(int(player.get("score", 0)) for player in lineup.values())
    return {
        "lineup": {
            position: {
                "id": player["id"],
                "name": player["name"],
                "score": int(player.get("score", 0)),
                "primary_position": player["primary_position"],
                "secondary_position": player.get("secondary_position"),
                "is_off_position": player["primary_position"] != position,
            }
            for position, player in lineup.items()
        },
        "total_score": total_score,
        "target_score": target_score,
        "score_difference": abs(total_score - target_score),
        "fit_penalty": 0,
    }


def start_auction(state: dict[str, Any], *, shuffle: bool = True) -> None:
    if not state["captains"]:
        raise ValueError("팀장을 한 명 이상 등록해 주세요.")
    waiting = [p["id"] for p in state["players"] if p["status"] == "waiting"]
    if not waiting:
        raise ValueError("경매할 참가자가 없습니다.")
    if shuffle:
        random.SystemRandom().shuffle(waiting)
    auction = state["auction"]
    auction["queue"] = waiting
    auction["unsold"] = []
    auction["round"] = 1
    auction["history"] = []
    _begin_next(state)


def start_reauction(state: dict[str, Any]) -> None:
    auction = state["auction"]
    if auction["status"] != "waiting_reauction" or not auction["unsold"]:
        raise ValueError("재경매할 유찰자가 없습니다.")
    auction["queue"] = list(auction["unsold"])
    auction["unsold"] = []
    auction["round"] += 1
    _begin_next(state)


def _begin_next(state: dict[str, Any]) -> None:
    auction = state["auction"]
    auction["highest_bid"] = None
    auction["paused_remaining"] = None
    if auction["queue"]:
        auction["current_player_id"] = auction["queue"].pop(0)
        auction["deadline"] = time.time() + state["settings"]["countdown_seconds"]
        auction["status"] = "running"
    elif auction["unsold"]:
        auction["current_player_id"] = None
        auction["deadline"] = None
        auction["status"] = "waiting_reauction"
    else:
        auction["current_player_id"] = None
        auction["deadline"] = None
        auction["status"] = "finished"


def place_bid(
    state: dict[str, Any], captain_id: str, amount: int
) -> dict[str, Any]:
    auction = state["auction"]
    if auction["status"] != "running":
        raise ValueError("현재 입찰할 수 없습니다.")
    captain = next((c for c in state["captains"] if c["id"] == captain_id), None)
    if captain is None:
        raise ValueError("팀장을 찾을 수 없습니다.")

    highest = auction["highest_bid"]
    settings = state["settings"]
    required = settings["minimum_bid"]
    if highest:
        required = highest["amount"] + settings["bid_increment"]
    if amount < required:
        raise ValueError(f"최소 {required}점부터 입찰할 수 있습니다.")

    empty_slots = sum(value is None for value in captain["team"].values())
    reserve = max(0, empty_slots - 1) * settings["minimum_bid"]
    maximum = captain["remaining_budget"] - reserve
    if amount > maximum:
        raise ValueError(f"남은 포지션 예산을 고려하면 최대 {maximum}점입니다.")

    auction["highest_bid"] = {
        "captain_id": captain_id,
        "captain_name": captain["name"],
        "amount": amount,
        "created_at": time.time(),
    }

    remaining = auction["deadline"] - time.time()
    if remaining <= settings["extension_trigger_seconds"]:
        auction["deadline"] += settings["extension_seconds"]
    return auction["highest_bid"]


def pause(state: dict[str, Any]) -> None:
    auction = state["auction"]
    if auction["status"] != "running":
        raise ValueError("진행 중인 경매만 일시정지할 수 있습니다.")
    auction["paused_remaining"] = max(0, auction["deadline"] - time.time())
    auction["deadline"] = None
    auction["status"] = "paused"


def resume(state: dict[str, Any]) -> None:
    auction = state["auction"]
    if auction["status"] != "paused":
        raise ValueError("일시정지된 경매가 아닙니다.")
    auction["deadline"] = time.time() + auction["paused_remaining"]
    auction["paused_remaining"] = None
    auction["status"] = "running"


def finalize_if_due(state: dict[str, Any], now: float | None = None) -> bool:
    now = now or time.time()
    auction = state["auction"]
    if (
        auction["status"] != "running"
        or auction["deadline"] is None
        or now < auction["deadline"]
    ):
        return False

    player = next(
        p for p in state["players"] if p["id"] == auction["current_player_id"]
    )
    bid = auction["highest_bid"]
    if bid is None:
        player["status"] = "unsold"
        player["unsold_count"] += 1
        auction["unsold"].append(player["id"])
        auction["history"].append(
            {
                "type": "unsold",
                "player_id": player["id"],
                "player_name": player["name"],
                "round": auction["round"],
                "created_at": now,
            }
        )
    else:
        captain = next(
            c for c in state["captains"] if c["id"] == bid["captain_id"]
        )
        captain["remaining_budget"] -= bid["amount"]
        player["status"] = "sold"
        player["sold_to"] = captain["id"]
        player["sold_amount"] = bid["amount"]
        _assign_player(captain, player)
        auction["history"].append(
            {
                "type": "sold",
                "player_id": player["id"],
                "player_name": player["name"],
                "captain_id": captain["id"],
                "captain_name": captain["name"],
                "amount": bid["amount"],
                "round": auction["round"],
                "created_at": now,
            }
        )
    _begin_next(state)
    return True


def _assign_player(captain: dict[str, Any], player: dict[str, Any]) -> None:
    primary = player["primary_position"]
    secondary = player["secondary_position"]
    if captain["team"].get(primary) is None:
        captain["team"][primary] = player["id"]
    elif secondary and captain["team"].get(secondary) is None:
        captain["team"][secondary] = player["id"]
    else:
        captain["bench"].append(player["id"])
