from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.engine import add_player, new_state


DATA_PATH = ROOT / "data" / "state.json"

PLAYERS = [
    ("탑가렌", "GOLD IV", "TOP", "MID", 9, 6),
    ("탑피오라", "PLATINUM III", "TOP", "MID", 11, 7),
    ("탑오른", "SILVER I", "TOP", "SUP", 7, 5),
    ("탑잭스", "EMERALD IV", "TOP", "JUG", 13, 9),
    ("탑케넨", "GOLD II", "TOP", "MID", 10, 8),
    ("정글리신", "PLATINUM IV", "JUG", "TOP", 10, 7),
    ("정글바이", "GOLD III", "JUG", "TOP", 8, 6),
    ("정글니달리", "EMERALD III", "JUG", "MID", 13, 8),
    ("정글자르반", "SILVER II", "JUG", "SUP", 7, 5),
    ("정글비에고", "PLATINUM II", "JUG", "MID", 11, 7),
    ("미드아리", "PLATINUM III", "MID", "SUP", 11, 6),
    ("미드오리아나", "GOLD I", "MID", "SUP", 9, 7),
    ("미드제드", "EMERALD IV", "MID", "TOP", 13, 8),
    ("미드빅토르", "GOLD III", "MID", "ADC", 8, 5),
    ("미드사일러스", "PLATINUM I", "MID", "TOP", 12, 8),
    ("원딜징크스", "PLATINUM IV", "ADC", "MID", 10, 6),
    ("원딜카이사", "GOLD II", "ADC", "MID", 9, 6),
    ("원딜이즈리얼", "EMERALD IV", "ADC", "MID", 12, 8),
    ("원딜애쉬", "SILVER I", "ADC", "SUP", 7, 6),
    ("원딜자야", "PLATINUM II", "ADC", "MID", 11, 7),
    ("서폿쓰레쉬", "PLATINUM III", "SUP", "JUG", 10, 6),
    ("서폿나미", "GOLD III", "SUP", "MID", 8, 5),
    ("서폿레오나", "SILVER I", "SUP", "TOP", 7, 5),
    ("서폿라칸", "EMERALD IV", "SUP", "MID", 12, 7),
    ("서폿룰루", "GOLD I", "SUP", "MID", 9, 6),
]


def build_document() -> dict:
    state = new_state()
    state["settings"]["room_name"] = "포지션 점수 테스트 대회"
    state["tournament"]["score_limit"] = 50
    for index, (name, tier, primary, secondary, score, secondary_score) in enumerate(
        PLAYERS,
        start=1,
    ):
        add_player(
            state,
            name=name,
            riot_id=f"더미선수{index:02d}#KR1",
            tier=tier,
            primary_position=primary,
            secondary_position=secondary,
            score=score,
            secondary_score=secondary_score,
        )
    competition_id = uuid.uuid4().hex
    return {
        "version": 2,
        "teacher_auth": None,
        "active_competition_id": competition_id,
        "competitions": [
            {
                "id": competition_id,
                "name": "포지션 점수 테스트 대회",
                "mode": "tournament",
                "created_at": time.time(),
                "state": state,
            }
        ],
    }


def main() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DATA_PATH.exists():
        backup = DATA_PATH.with_suffix(".before-dummy.json")
        backup.write_text(DATA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    DATA_PATH.write_text(
        json.dumps(build_document(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Created {DATA_PATH} with {len(PLAYERS)} players.")


if __name__ == "__main__":
    main()
