from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine import add_player, new_state, register_tournament_team


DATA_PATH = ROOT / "data" / "state.json"
POSITIONS = ("TOP", "JUG", "MID", "ADC", "SUP")
TEAM_NAMES = (
    "블루 드래곤",
    "레드 바론",
    "골든 크루",
    "실버 애로우",
    "에메랄드 폭스",
    "다이아 울브즈",
    "마스터 스톰",
    "챌린저 스타",
)


def build_document() -> dict:
    state = new_state()
    state["settings"]["room_name"] = "스크림 화면 테스트"
    state["tournament"]["score_limit"] = 100

    teams = []
    for team_index, team_name in enumerate(TEAM_NAMES, start=1):
        members = {}
        for position_index, position in enumerate(POSITIONS, start=1):
            player = add_player(
                state,
                name=f"{team_name} {position}",
                riot_id=f"demo{team_index}-{position.lower()}#KR1",
                tier="GOLD",
                primary_position=position,
                score=team_index + position_index,
            )
            members[position] = player["id"]
        team = register_tournament_team(
            state,
            team_name,
            members,
            f"{1000 + team_index}",
        )
        team["status"] = "approved"
        teams.append(team)

    today = date.today()
    results = []
    score_patterns = ((2, 0), (1, 1), (0, 2))
    for index in range(16):
        team_a = teams[index % len(teams)]
        team_b = teams[(index * 3 + 1) % len(teams)]
        if team_a["id"] == team_b["id"]:
            team_b = teams[(index + 1) % len(teams)]
        score_a, score_b = score_patterns[index % len(score_patterns)]
        results.append(
            {
                "id": uuid.uuid4().hex,
                "team_a_id": team_a["id"],
                "team_b_id": team_b["id"],
                "match_date": (today - timedelta(days=15 - index)).isoformat(),
                "best_of": 2,
                "team_a_score": score_a,
                "team_b_score": score_b,
                "winner_team_id": (
                    team_a["id"]
                    if score_a > score_b
                    else team_b["id"]
                    if score_b > score_a
                    else None
                ),
                "memo": f"화면 확인용 스크림 {index + 1}",
                "created_at": time.time() + index,
                "updated_at": time.time() + index,
            }
        )
    state["scrim_results"] = results

    competition_id = "local-scrim-demo"
    return {
        "version": 2,
        "active_competition_id": competition_id,
        "competitions": [
            {
                "id": competition_id,
                "name": "스크림 화면 테스트",
                "mode": "tournament",
                "created_at": time.time(),
                "state": state,
            }
        ],
    }


def main() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DATA_PATH.exists():
        backup = DATA_PATH.with_name("state.before-scrim-demo.json")
        backup.write_text(DATA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Backed up existing state to {backup}")
    DATA_PATH.write_text(
        json.dumps(build_document(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Created {DATA_PATH} with "
        f"{len(TEAM_NAMES)} teams and 16 scrim results."
    )


if __name__ == "__main__":
    main()
