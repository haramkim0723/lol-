from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import scrim_db
from app.engine import new_state
from app.store import JsonStore


TEST_ID = "test-score-approved"
TEST2_ID = "test2-score-open"


def load_env(path: Path | None) -> None:
    if not path or not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value.strip().strip('"')


def score_state(name: str, *, participation_enabled: bool, applications: list[dict]) -> dict:
    state = new_state()
    state["settings"]["room_name"] = name
    state["players"] = []
    state["tournament"]["status"] = "registration"
    state["participation"]["enabled"] = participation_enabled
    state["participation"]["applications"] = applications
    return state


def active_members() -> list[dict]:
    with scrim_db.connect() as connection:
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
    return [dict(row) for row in rows]


def reset_local_state(applications: list[dict]) -> None:
    store = JsonStore()
    now = time.time()
    store.document = {
        "version": 2,
        "active_competition_id": TEST2_ID,
        "competitions": [
            {
                "id": TEST_ID,
                "name": "test1",
                "mode": "tournament",
                "created_at": now,
                "state": score_state(
                    "test1",
                    participation_enabled=False,
                    applications=applications,
                ),
            },
            {
                "id": TEST2_ID,
                "name": "test2",
                "mode": "tournament",
                "created_at": now + 1,
                "state": score_state(
                    "test2",
                    participation_enabled=True,
                    applications=[],
                ),
            },
        ],
    }
    store.save()


def reset_participation_db() -> dict:
    scrim_db.init_db()
    now = time.time()
    users = active_members()
    with scrim_db.connect() as connection:
        connection.execute("DELETE FROM member_competition_participations")
        for user in users:
            scrim_db.record_competition_participation(
                connection,
                user_id=user["user_id"],
                competition_id=TEST_ID,
                competition_name="test1",
                applied_at=now,
            )
            scrim_db.set_competition_participation_status(
                connection,
                user_id=user["user_id"],
                competition_id=TEST_ID,
                status="APPROVED",
                changed_at=now,
            )
        total = connection.execute(
            """
            SELECT COUNT(*) AS count FROM users
            WHERE role = 'USER' AND approved = 1 AND is_active = 1
            """
        ).fetchone()
        issued = connection.execute(
            "SELECT COUNT(*) AS count FROM roster_entries WHERE user_id IS NOT NULL"
        ).fetchone()
        approved = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM member_competition_participations
            WHERE competition_id = ? AND status = 'APPROVED'
            """,
            (TEST_ID,),
        ).fetchone()
        test2 = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM member_competition_participations
            WHERE competition_id = ?
            """,
            (TEST2_ID,),
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
    return {
        "applications": applications,
        "roster_total": dict(total)["count"],
        "account_issued": dict(issued)["count"],
        "test_approved": dict(approved)["count"],
        "test2_records": dict(test2)["count"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--skip-state", action="store_true")
    args = parser.parse_args()
    load_env(args.env_file)
    summary = reset_participation_db()
    applications = summary.pop("applications")
    if not args.skip_state:
        reset_local_state(applications)
        summary["state"] = "test1/test2 reset"
    for key, value in summary.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
