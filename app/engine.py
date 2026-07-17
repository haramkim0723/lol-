from __future__ import annotations

import random
import time
import uuid
from copy import deepcopy
from typing import Any


POSITIONS = ("TOP", "JUG", "MID", "ADC", "SUP")
MAX_RECOMMENDATION_CANDIDATES_PER_POSITION = 24


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
        "notices": [],
        "roster_score_table": [],
        "captains": [],
        "players": [],
        "tournament": {
            "score_limit": 40,
            "format": "single_elimination",
            "group_count": 2,
            "qualifiers_per_group": 2,
            "status": "registration",
            "teams": [],
            "groups": [],
            "qualified_team_ids": [],
            "rounds": [],
            "round_labels": [],
            "champion_id": None,
        },
        "participation": {
            "enabled": False,
            "score_visible": False,
            "terms": (
                "대회 진행 공지와 운영 규칙을 확인했고, 참가 신청 후 "
                "강사님의 안내에 따르는 것에 동의합니다."
            ),
            "applications": [],
        },
        "scrim_results": [],
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


def public_state_base(
    state: dict[str, Any],
    now: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(state)
    for captain in result["captains"]:
        captain.pop("user_id", None)
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
    team_access = []
    for team in tournament["teams"]:
        team_player_ids = set(team.get("members", {}).values())
        member_riot_ids = {
            str(player.get("riot_id") or "").casefold()
            for player in result["players"]
            if player["id"] in team_player_ids
        }
        team_access.append(
            {
                "created_by_user_id": team.get("created_by_user_id"),
                "member_riot_ids": member_riot_ids,
            }
        )
        team.pop("registration_pin", None)
        team.pop("created_by_user_id", None)
    participation = result.setdefault(
        "participation",
        {
            "enabled": False,
            "score_visible": False,
            "terms": "",
            "applications": [],
        },
    )
    participation.setdefault("score_visible", False)
    applications = participation.pop("applications", [])
    active_application_user_ids = {
        application.get("user_id")
        for application in applications
        if application.get("status", "APPLIED") in {"APPLIED", "APPROVED"}
    }
    participation["application_count"] = len(active_application_user_ids)
    now = now or time.time()
    deadline = result["auction"].get("deadline")
    result["server_time"] = now
    result["auction"]["remaining_seconds"] = (
        max(0, deadline - now) if deadline is not None else None
    )
    return result, {
        "active_application_user_ids": active_application_user_ids,
        "team_access": team_access,
    }


def public_state_from_base(
    base_state: dict[str, Any],
    context: dict[str, Any],
    viewer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    viewer = viewer or {"role": "spectator", "captain_id": None}
    result = dict(base_state)
    tournament = dict(base_state["tournament"])
    participation = dict(base_state["participation"])
    score_visible = bool(participation.get("score_visible")) or viewer.get("role") == "host"
    if not score_visible:
        hidden_score_fields = {"score", "secondary_score", "position_scores", "tier"}
        result["players"] = [
            {
                key: value
                for key, value in player.items()
                if key not in hidden_score_fields
            }
            for player in base_state.get("players", [])
        ]
    viewer_riot_id = str(viewer.get("riot_id") or "").casefold()
    viewer_user_id = viewer.get("user_id")
    tournament["teams"] = []
    for team, access in zip(
        base_state["tournament"]["teams"],
        context.get("team_access", []),
    ):
        public_team = dict(team)
        belongs_to_team = viewer_riot_id in access.get("member_riot_ids", set())
        public_team["can_manage_scrim_result"] = bool(
            viewer
            and (
                viewer.get("role") == "host"
                or access.get("created_by_user_id") == viewer_user_id
                or belongs_to_team
            )
        )
        tournament["teams"].append(public_team)
    result["tournament"] = tournament
    participation["viewer_has_applied"] = viewer_user_id in context.get(
        "active_application_user_ids",
        set(),
    )
    result["participation"] = participation
    result["viewer"] = viewer
    return result


def public_state(
    state: dict[str, Any], viewer: dict[str, Any] | None = None
) -> dict[str, Any]:
    base_state, context = public_state_base(state)
    return public_state_from_base(base_state, context, viewer)


def add_captain(
    state: dict[str, Any], player_id: str, budget: int, user_id: int
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
        "user_id": user_id,
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
    extra_positions: list[str] | None = None,
    position_scores: dict[str, float] | None = None,
    profile_icon_url: str | None = None,
    score: int = 0,
    secondary_score: int | None = None,
) -> dict[str, Any]:
    extra_positions = [
        position
        for position in (extra_positions or [])
        if position and position not in (primary_position, secondary_position)
    ][:2]
    player = {
        "id": uuid.uuid4().hex,
        "name": name.strip(),
        "riot_id": riot_id.strip(),
        "tier": tier.strip() or "UNRANKED",
        "primary_position": primary_position,
        "secondary_position": secondary_position or None,
        "extra_positions": extra_positions,
        "position_scores": position_scores or {},
        "profile_icon_url": profile_icon_url,
        "score": score,
        "secondary_score": score if secondary_score is None else secondary_score,
        "status": "waiting",
        "sold_to": None,
        "sold_amount": None,
        "unsold_count": 0,
    }
    state["players"].append(player)
    return player


def player_score_for_position(player: dict[str, Any], position: str) -> float:
    position_scores = player.get("position_scores") or {}
    if position in position_scores and position_scores[position] not in (None, ""):
        return float(position_scores[position])
    if position != player.get("primary_position") and player_can_play_position(
        player, position
    ):
        return int(player.get("secondary_score", player.get("score", 0)))
    return int(player.get("score", 0))


def player_positions(player: dict[str, Any]) -> list[str]:
    return [
        position
        for position in (
            player.get("primary_position"),
            player.get("secondary_position"),
            *(player.get("extra_positions") or []),
        )
        if position in POSITIONS
    ]


def player_can_play_position(player: dict[str, Any], position: str) -> bool:
    return position in player_positions(player)



def update_player_score(
    state: dict[str, Any],
    player_id: str,
    score: int,
    secondary_score: int | None = None,
) -> dict[str, Any]:
    player = next(
        (item for item in state["players"] if item["id"] == player_id), None
    )
    if player is None:
        raise ValueError("참가자를 찾을 수 없습니다.")
    player["score"] = score
    if secondary_score is not None:
        player["secondary_score"] = secondary_score
    for team in state["tournament"]["teams"]:
        if player_id in team["members"].values():
            team["total_score"] = sum(
                player_score_for_position(
                    next(
                        item
                        for item in state["players"]
                        if item["id"] == member_id
                    ),
                    position,
                )
                for position, member_id in team["members"].items()
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
    excluded_player_ids: set[str] | None = None,
    minimum_score: float | None = None,
) -> list[dict[str, Any]]:
    minimum_recommended_score = 0 if minimum_score is None else max(0, minimum_score)
    players = state["players"]
    by_id = {player["id"]: player for player in players}
    excluded_player_ids = excluded_player_ids or set()
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
        if player_id in excluded_player_ids:
            raise ValueError("이미 팀에 등록된 참가자는 조합 시뮬레이션에 사용할 수 없습니다.")
        if not player_can_play_position(player, position):
            raise ValueError(
                f'{player["name"]} 님은 {position} 포지션으로 배치할 수 없습니다.'
            )
        lineup[position] = player

    empty_positions = [
        position for position in POSITIONS if position not in lineup
    ]
    candidate_lists: list[list[tuple[dict[str, Any], int]]] = []
    target_per_position = target_score / len(POSITIONS)
    for position in empty_positions:
        candidates = []
        for player in players:
            if player["id"] in selected_ids:
                continue
            if player["id"] in excluded_player_ids:
                continue
            if not player_can_play_position(player, position):
                continue
            if player["primary_position"] == position:
                candidates.append((player, 0))
            else:
                candidates.append((player, 1))
        if not candidates:
            raise ValueError(f"{position}에 배치 가능한 참가자가 없습니다.")
        candidates.sort(
            key=lambda item: (
                item[1],
                abs(player_score_for_position(item[0], position) - target_per_position),
                -player_score_for_position(item[0], position),
                item[0]["name"],
            )
        )
        candidate_lists.append(
            candidates[:MAX_RECOMMENDATION_CANDIDATES_PER_POSITION]
        )

    best: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    remaining_min_scores: list[float] = [0] * (len(candidate_lists) + 1)
    remaining_max_scores: list[float] = [0] * (len(candidate_lists) + 1)
    for index in range(len(candidate_lists) - 1, -1, -1):
        position = empty_positions[index]
        scores = [
            player_score_for_position(player, position)
            for player, _penalty in candidate_lists[index]
        ]
        remaining_min_scores[index] = remaining_min_scores[index + 1] + min(scores)
        remaining_max_scores[index] = remaining_max_scores[index + 1] + max(scores)

    def result_key(result: dict[str, Any]) -> tuple[Any, ...]:
        total_score = result["total_score"]
        return (
            result["score_difference"],
            result["off_position_count"],
            0 if total_score <= target_score else 1,
            -total_score,
            tuple(result["lineup"][position]["name"] for position in POSITIONS),
        )

    def best_possible_difference(index: int, score_so_far: float) -> float:
        minimum = score_so_far + remaining_min_scores[index]
        maximum = score_so_far + remaining_max_scores[index]
        if target_score < minimum:
            return minimum - target_score
        if target_score > maximum:
            return target_score - maximum
        return 0

    def remember_result(
        completed: dict[str, dict[str, Any]],
        off_position_count: int,
    ) -> None:
        raw_total_score = sum(
            player_score_for_position(completed[position], position)
            for position in POSITIONS
        )
        if not (
            minimum_recommended_score - 1e-9
            <= raw_total_score
            <= target_score + 1e-9
        ):
            return
        total_score = round(raw_total_score, 2)
        result = {
            "lineup": {
                position: {
                    "id": completed[position]["id"],
                    "name": completed[position]["name"],
                    "score": player_score_for_position(
                        completed[position], position
                    ),
                    "is_locked": position in lineup,
                    "is_off_position": (
                        completed[position]["primary_position"] != position
                    ),
                }
                for position in POSITIONS
            },
            "total_score": total_score,
            "target_score": target_score,
            "score_difference": round(target_score - total_score, 2),
            "off_position_count": off_position_count,
        }
        key = result_key(result)
        best.append((key, result))
        best.sort(key=lambda item: item[0])
        if len(best) > limit:
            best.pop()

    def backtrack(
        index: int,
        completed: dict[str, dict[str, Any]],
        used_ids: set[str],
        score_so_far: float,
        off_position_count: int,
    ) -> None:
        if score_so_far > target_score + 1e-9:
            return
        if (
            score_so_far + remaining_max_scores[index]
            < minimum_recommended_score - 1e-9
        ):
            return
        if (
            len(best) >= limit
            and best_possible_difference(index, score_so_far) > best[-1][0][0]
        ):
            return
        if index == len(empty_positions):
            remember_result(completed, off_position_count)
            return
        position = empty_positions[index]
        for player, penalty in candidate_lists[index]:
            player_id = player["id"]
            if player_id in used_ids:
                continue
            completed[position] = player
            used_ids.add(player_id)
            backtrack(
                index + 1,
                completed,
                used_ids,
                score_so_far + player_score_for_position(player, position),
                off_position_count + penalty,
            )
            used_ids.remove(player_id)
            completed.pop(position, None)

    locked_score = sum(
        player_score_for_position(player, position)
        for position, player in lineup.items()
    )
    backtrack(0, dict(lineup), set(selected_ids), locked_score, 0)
    return [item[1] for item in best]


def register_tournament_team(
    state: dict[str, Any],
    name: str,
    members: dict[str, str],
    registration_pin: str,
    created_by_user_id: int | None = None,
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
        if not player_can_play_position(player, position):
            raise ValueError(
                f'{player["name"]} 님은 {position} 포지션으로 배치할 수 없습니다.'
            )
        lineup[position] = player

    total_score = sum(
        player_score_for_position(lineup[position], position)
        for position in POSITIONS
    )
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
        "created_by_user_id": created_by_user_id,
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
    if tournament.get("format") == "group_then_knockout":
        group_count = tournament.get("group_count", 2)
        if len(approved) < group_count:
            raise ValueError("승인된 팀 수가 조 수보다 적습니다.")
        qualifiers = tournament.get("qualifiers_per_group", 2)
        if len(approved) < group_count * qualifiers:
            raise ValueError(
                f"조당 {qualifiers}팀 진출에는 승인 팀이 최소 "
                f"{group_count * qualifiers}팀 필요합니다."
            )
        random.SystemRandom().shuffle(approved)
        groups = [
            {"name": f"{chr(65 + index)}조", "team_ids": [], "qualified_team_ids": []}
            for index in range(group_count)
        ]
        for index, team_id in enumerate(approved):
            groups[index % group_count]["team_ids"].append(team_id)
        tournament["groups"] = groups
        tournament["qualified_team_ids"] = []
        tournament["rounds"] = []
        tournament["champion_id"] = None
        tournament["status"] = "group"
        return
    _create_knockout(tournament, approved)


def set_group_qualifiers(
    state: dict[str, Any], group_index: int, team_ids: list[str]
) -> None:
    tournament = state["tournament"]
    if tournament["status"] != "group":
        raise ValueError("조별 진행 단계가 아닙니다.")
    try:
        group = tournament["groups"][group_index]
    except IndexError as exc:
        raise ValueError("조를 찾을 수 없습니다.") from exc
    limit = tournament.get("qualifiers_per_group", 2)
    if len(team_ids) > limit:
        raise ValueError(f"한 조에서 최대 {limit}팀까지 진출할 수 있습니다.")
    if len(set(team_ids)) != len(team_ids) or any(
        team_id not in group["team_ids"] for team_id in team_ids
    ):
        raise ValueError("해당 조에 속하지 않은 팀이 포함되어 있습니다.")
    group["qualified_team_ids"] = team_ids
    tournament["qualified_team_ids"] = [
        team_id
        for item in tournament["groups"]
        for team_id in item["qualified_team_ids"]
    ]


def start_group_knockout(state: dict[str, Any]) -> None:
    tournament = state["tournament"]
    if tournament["status"] != "group":
        raise ValueError("조별 진행 단계가 아닙니다.")
    required = tournament.get("qualifiers_per_group", 2)
    if any(len(group["qualified_team_ids"]) != required for group in tournament["groups"]):
        raise ValueError(f"각 조에서 진출팀을 {required}팀씩 선택해 주세요.")
    seeds = [
        team_id
        for rank in range(required)
        for group in tournament["groups"]
        for team_id in group["qualified_team_ids"][rank:rank + 1]
    ]
    _create_knockout(tournament, seeds)


def _create_knockout(tournament: dict[str, Any], approved: list[str]) -> None:
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
    tournament["round_labels"] = []
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
    loser_id = (
        match["team2_id"] if team_id == match["team1_id"] else match["team1_id"]
    )
    if "winner_to" in match or "loser_to" in match:
        _route_custom_result(tournament, match.get("winner_to"), team_id)
        _route_custom_result(tournament, match.get("loser_to"), loser_id)
        if not match.get("winner_to"):
            tournament["champion_id"] = team_id
            tournament["status"] = "finished"
        return
    if round_index == len(tournament["rounds"]) - 1:
        tournament["champion_id"] = team_id
        tournament["status"] = "finished"
        return
    next_match = tournament["rounds"][round_index + 1][match_index // 2]
    slot = "team1_id" if match_index % 2 == 0 else "team2_id"
    next_match[slot] = team_id
    next_match["winner_id"] = None
    _advance_byes(tournament)


def set_custom_bracket(
    state: dict[str, Any], round_definitions: list[dict[str, Any]]
) -> None:
    tournament = state["tournament"]
    allowed_team_ids = {
        team["id"] for team in tournament["teams"] if team["status"] == "approved"
    }
    if tournament.get("groups"):
        allowed_team_ids &= set(tournament["qualified_team_ids"])
    rounds: list[list[dict[str, Any]]] = []
    labels: list[str] = []
    for round_definition in round_definitions:
        labels.append(round_definition["label"].strip())
        matches = []
        for definition in round_definition["matches"]:
            team_ids = [definition.get("team1_id"), definition.get("team2_id")]
            if any(team_id and team_id not in allowed_team_ids for team_id in team_ids):
                raise ValueError("본선 참가 대상이 아닌 팀이 포함되어 있습니다.")
            matches.append(
                {
                    "id": uuid.uuid4().hex,
                    "team1_id": definition.get("team1_id"),
                    "team2_id": definition.get("team2_id"),
                    "winner_id": None,
                    "winner_to": definition.get("winner_to"),
                    "loser_to": definition.get("loser_to"),
                }
            )
        rounds.append(matches)
    for round_index, matches in enumerate(rounds):
        for match in matches:
            for route in (match.get("winner_to"), match.get("loser_to")):
                if route is None:
                    continue
                target_round = route["round_index"]
                target_match = route["match_index"]
                if target_round <= round_index:
                    raise ValueError("승자·패자는 이후 라운드 경기로만 이동할 수 있습니다.")
                if target_round >= len(rounds) or target_match >= len(rounds[target_round]):
                    raise ValueError("이동 대상 경기를 찾을 수 없습니다.")
    tournament["rounds"] = rounds
    tournament["round_labels"] = labels
    tournament["champion_id"] = None
    tournament["status"] = "running"


def _route_custom_result(
    tournament: dict[str, Any], route: dict[str, Any] | None, team_id: str
) -> None:
    if route is None:
        return
    target = tournament["rounds"][route["round_index"]][route["match_index"]]
    target[route["slot"]] = team_id
    target["winner_id"] = None


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
        auction["deadline"] = None
        auction["status"] = "ready"
    elif auction["unsold"]:
        auction["current_player_id"] = None
        auction["deadline"] = None
        auction["status"] = "waiting_reauction"
    else:
        auction["current_player_id"] = None
        auction["deadline"] = None
        auction["status"] = "finished"


def start_timer(state: dict[str, Any]) -> None:
    auction = state["auction"]
    if auction["status"] != "ready" or not auction["current_player_id"]:
        raise ValueError("타이머를 시작할 후보가 준비되지 않았습니다.")
    auction["deadline"] = time.time() + state["settings"]["countdown_seconds"]
    auction["status"] = "running"


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
    for position in player_positions(player):
        if captain["team"].get(position) is None:
            captain["team"][position] = player["id"]
            return
    captain["bench"].append(player["id"])
