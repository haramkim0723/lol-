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
        "tournament": {
            "score_limit": 40,
            "status": "registration",
            "teams": [],
            "rounds": [],
            "champion_id": None,
        },
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
    tournament = result.setdefault(
        "tournament",
        {
            "score_limit": 40,
            "status": "registration",
            "teams": [],
            "rounds": [],
            "champion_id": None,
        },
    )
    for team in tournament["teams"]:
        team.pop("registration_pin", None)
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


def update_player_score(
    state: dict[str, Any], player_id: str, score: int
) -> dict[str, Any]:
    player = next(
        (item for item in state["players"] if item["id"] == player_id), None
    )
    if player is None:
        raise ValueError("참가자를 찾을 수 없습니다.")
    player["score"] = score
    for team in state["tournament"]["teams"]:
        if player_id in team["members"].values():
            team["total_score"] = sum(
                int(
                    next(
                        item
                        for item in state["players"]
                        if item["id"] == member_id
                    ).get("score", 0)
                )
                for member_id in team["members"].values()
            )
            team["over_score_limit"] = (
                team["total_score"] > state["tournament"]["score_limit"]
            )
    return player


def recommend_team_combinations(
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
            raise ValueError("선택한 참가자를 찾을 수 없습니다.")
        if position not in (
            player["primary_position"],
            player.get("secondary_position"),
        ):
            raise ValueError(
                f'{player["name"]} 님은 {position} 포지션으로 배치할 수 없습니다.'
            )
        lineup[position] = player

    empty_positions = [
        position for position in POSITIONS if position not in lineup
    ]
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

    best: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    combinations = product(*candidate_lists) if candidate_lists else [()]
    for choices in combinations:
        chosen = [choice[0] for choice in choices]
        chosen_ids = [player["id"] for player in chosen]
        if len(chosen_ids) != len(set(chosen_ids)):
            continue
        completed = dict(lineup)
        off_position_count = 0
        for position, (player, penalty) in zip(empty_positions, choices):
            completed[position] = player
            off_position_count += penalty
        total_score = sum(
            int(player.get("score", 0)) for player in completed.values()
        )
        result = {
            "lineup": {
                position: {
                    "id": completed[position]["id"],
                    "name": completed[position]["name"],
                    "score": int(completed[position].get("score", 0)),
                    "is_locked": position in lineup,
                    "is_off_position": (
                        completed[position]["primary_position"] != position
                    ),
                }
                for position in POSITIONS
            },
            "total_score": total_score,
            "target_score": target_score,
            "score_difference": abs(total_score - target_score),
            "off_position_count": off_position_count,
        }
        key = (
            result["score_difference"],
            off_position_count,
            0 if total_score <= target_score else 1,
            -total_score,
            tuple(result["lineup"][position]["name"] for position in POSITIONS),
        )
        best.append((key, result))
        best.sort(key=lambda item: item[0])
        if len(best) > limit:
            best.pop()
    return [item[1] for item in best]


def register_tournament_team(
    state: dict[str, Any],
    name: str,
    members: dict[str, str],
    registration_pin: str,
) -> dict[str, Any]:
    tournament = state["tournament"]
    if tournament["status"] != "registration":
        raise ValueError("현재는 팀 등록 기간이 아닙니다.")
    if set(members) != set(POSITIONS):
        raise ValueError("다섯 포지션을 모두 등록해 주세요.")

    players = state["players"]
    by_id = {player["id"]: player for player in players}
    selected_ids = list(members.values())
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("한 참가자를 여러 포지션에 중복 등록할 수 없습니다.")

    for existing in tournament["teams"]:
        if existing["status"] == "rejected":
            continue
        overlap = set(existing["members"].values()) & set(selected_ids)
        if overlap:
            player = by_id[next(iter(overlap))]
            raise ValueError(f'{player["name"]} 님은 이미 다른 팀에 등록되어 있습니다.')

    lineup: dict[str, dict[str, Any]] = {}
    for position, player_id in members.items():
        player = by_id.get(player_id)
        if player is None:
            raise ValueError("등록할 참가자를 찾을 수 없습니다.")
        if position not in (player["primary_position"], player["secondary_position"]):
            raise ValueError(
                f'{player["name"]} 님은 {position} 포지션으로 배치할 수 없습니다.'
            )
        lineup[position] = player

    total_score = sum(int(player.get("score", 0)) for player in lineup.values())
    if total_score > tournament["score_limit"]:
        raise ValueError(
            f'팀 총점 {total_score}점으로 제한 {tournament["score_limit"]}점을 초과합니다.'
        )
    if any(team["name"].casefold() == name.strip().casefold() for team in tournament["teams"]):
        raise ValueError("이미 사용 중인 팀명입니다.")

    team = {
        "id": uuid.uuid4().hex,
        "name": name.strip(),
        "members": dict(members),
        "total_score": total_score,
        "registration_pin": registration_pin,
        "status": "pending",
        "created_at": time.time(),
    }
    tournament["teams"].append(team)
    return team


def approve_tournament_team(
    state: dict[str, Any], team_id: str, approved: bool
) -> dict[str, Any]:
    tournament = state["tournament"]
    if tournament["status"] != "registration":
        raise ValueError("토너먼트 시작 후에는 승인 상태를 바꿀 수 없습니다.")
    team = next((item for item in tournament["teams"] if item["id"] == team_id), None)
    if team is None:
        raise ValueError("팀을 찾을 수 없습니다.")
    team["status"] = "approved" if approved else "rejected"
    return team


def delete_tournament_team(state: dict[str, Any], team_id: str) -> None:
    tournament = state["tournament"]
    if tournament["status"] != "registration":
        raise ValueError("토너먼트 시작 후에는 팀을 삭제할 수 없습니다.")
    before = len(tournament["teams"])
    tournament["teams"] = [
        team for team in tournament["teams"] if team["id"] != team_id
    ]
    if len(tournament["teams"]) == before:
        raise ValueError("팀을 찾을 수 없습니다.")


def start_tournament(state: dict[str, Any]) -> None:
    tournament = state["tournament"]
    approved = [
        team["id"] for team in tournament["teams"] if team["status"] == "approved"
    ]
    if len(approved) < 2:
        raise ValueError("승인된 팀이 두 팀 이상 필요합니다.")
    random.SystemRandom().shuffle(approved)
    bracket_size = 1
    while bracket_size < len(approved):
        bracket_size *= 2
    seeds = approved + [None] * (bracket_size - len(approved))
    rounds: list[list[dict[str, Any]]] = []
    for round_index in range(bracket_size.bit_length() - 1):
        match_count = bracket_size // (2 ** (round_index + 1))
        rounds.append(
            [
                {
                    "id": uuid.uuid4().hex,
                    "team1_id": None,
                    "team2_id": None,
                    "winner_id": None,
                }
                for _ in range(match_count)
            ]
        )
    for index, match in enumerate(rounds[0]):
        match["team1_id"] = seeds[index * 2]
        match["team2_id"] = seeds[index * 2 + 1]
    tournament["rounds"] = rounds
    tournament["status"] = "running"
    tournament["champion_id"] = None
    _advance_byes(tournament)


def select_match_winner(
    state: dict[str, Any], round_index: int, match_index: int, team_id: str
) -> None:
    tournament = state["tournament"]
    if tournament["status"] != "running":
        raise ValueError("진행 중인 토너먼트가 아닙니다.")
    try:
        match = tournament["rounds"][round_index][match_index]
    except IndexError as exc:
        raise ValueError("경기를 찾을 수 없습니다.") from exc
    if team_id not in (match["team1_id"], match["team2_id"]):
        raise ValueError("이 경기에 참가하지 않은 팀입니다.")
    if not match["team1_id"] or not match["team2_id"]:
        raise ValueError("부전승 경기는 자동으로 처리됩니다.")
    match["winner_id"] = team_id
    if round_index == len(tournament["rounds"]) - 1:
        tournament["champion_id"] = team_id
        tournament["status"] = "finished"
        return
    next_match = tournament["rounds"][round_index + 1][match_index // 2]
    slot = "team1_id" if match_index % 2 == 0 else "team2_id"
    next_match[slot] = team_id
    next_match["winner_id"] = None
    _advance_byes(tournament)


def _advance_byes(tournament: dict[str, Any]) -> None:
    changed = True
    while changed:
        changed = False
        for round_index, round_matches in enumerate(tournament["rounds"]):
            for match_index, match in enumerate(round_matches):
                teams = [match["team1_id"], match["team2_id"]]
                present = [team_id for team_id in teams if team_id]
                if len(present) != 1 or match["winner_id"]:
                    continue
                # 첫 라운드의 실제 빈 시드만 부전승으로 처리한다.
                if round_index > 0:
                    previous = tournament["rounds"][round_index - 1]
                    source_matches = previous[match_index * 2: match_index * 2 + 2]
                    if any(source["winner_id"] is None for source in source_matches):
                        continue
                winner_id = present[0]
                match["winner_id"] = winner_id
                if round_index == len(tournament["rounds"]) - 1:
                    tournament["champion_id"] = winner_id
                    tournament["status"] = "finished"
                    return
                next_match = tournament["rounds"][round_index + 1][match_index // 2]
                slot = "team1_id" if match_index % 2 == 0 else "team2_id"
                next_match[slot] = winner_id
                changed = True


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
