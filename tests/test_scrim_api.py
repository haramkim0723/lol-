import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ["SCRIM_DB_FILE"] = str(
    Path(tempfile.gettempdir()) / f"lol-scrim-api-test-{uuid.uuid4().hex}.db"
)

from fastapi.testclient import TestClient

from app.main import app
from app.scrim_db import db_path


class ScrimApiTest(unittest.TestCase):
    def setUp(self):
        path = db_path()
        if path.exists():
            path.unlink()

    def test_create_user_team_join_and_schedule_with_scrim_session(self):
        with TestClient(app) as leader_client:
            health = leader_client.get("/api/scrim/health")
            self.assertEqual(health.status_code, 200)

            leader = leader_client.post(
                "/api/scrim/users",
                json={
                    "name": "API Leader",
                    "riot_id": "api-leader#KR1",
                    "password": "1234",
                },
            )
            self.assertEqual(leader.status_code, 200)
            self.assertIn("scrim_auth", leader_client.cookies)
            self.assertNotIn("password_hash", leader.json())

            me = leader_client.get("/api/scrim/me")
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.json()["riot_id"], "api-leader#KR1")

            team = leader_client.post(
                "/api/scrim/teams",
                json={"name": "API Scrim Team"},
            )
            self.assertEqual(team.status_code, 200)
            self.assertEqual(team.json()["members"][0]["role"], "LEADER")

            schedule = leader_client.post(
                "/api/scrim/schedules",
                json={
                    "team_id": team.json()["id"],
                    "scheduled_date": "2026-07-07",
                    "start_time": "20:00",
                    "end_time": "21:00",
                    "opponent_team_name": "Opponent",
                },
            )
            self.assertEqual(schedule.status_code, 200)

            overlap = leader_client.post(
                "/api/scrim/schedules",
                json={
                    "team_id": team.json()["id"],
                    "scheduled_date": "2026-07-07",
                    "start_time": "20:30",
                    "end_time": "21:30",
                },
            )
            self.assertEqual(overlap.status_code, 400)

            with TestClient(app) as member_client:
                member = member_client.post(
                    "/api/scrim/users",
                    json={
                        "name": "API Member",
                        "riot_id": "api-member#KR1",
                        "password": "1234",
                    },
                )
                self.assertEqual(member.status_code, 200)
                joined = member_client.post(
                    "/api/scrim/teams/join",
                    json={"invite_code": team.json()["invite_code"]},
                )
                self.assertEqual(joined.status_code, 200)
                self.assertEqual(len(joined.json()["members"]), 2)

                member_schedule = member_client.post(
                    "/api/scrim/schedules",
                    json={
                        "team_id": team.json()["id"],
                        "scheduled_date": "2026-07-08",
                        "start_time": "20:00",
                        "end_time": "21:00",
                    },
                )
                self.assertEqual(member_schedule.status_code, 403)

    def test_scrim_session_is_separate_from_auction_session(self):
        with TestClient(app) as client:
            client.get("/api/scrim/health")
            client.cookies.set("auction_auth", "not-a-scrim-session")
            response = client.get("/api/scrim/me")
            self.assertEqual(response.status_code, 401)

    def test_admin_can_search_users_and_reset_passwords(self):
        with TestClient(app) as member_client:
            member_client.get("/api/scrim/health")
            member = member_client.post(
                "/api/scrim/users",
                json={
                    "name": "Password Target",
                    "riot_id": "password-target#KR1",
                    "password": "oldpass",
                },
            )
            self.assertEqual(member.status_code, 200)
            member_client.post("/api/scrim/auth/logout")

            old_login = member_client.post(
                "/api/scrim/auth/login",
                json={"riot_id": "password-target#KR1", "password": "oldpass"},
            )
            self.assertEqual(old_login.status_code, 200)
            member_client.post("/api/scrim/auth/logout")

            with TestClient(app) as admin_client:
                admin_login = admin_client.post(
                    "/api/scrim/auth/login",
                    json={
                        "riot_id": "\uc7a5\uc6d0\ud601#ADMIN",
                        "password": "1234",
                    },
                )
                self.assertEqual(admin_login.status_code, 200)
                self.assertEqual(admin_login.json()["role"], "ADMIN")

                search = admin_client.get(
                    "/api/scrim/admin/users",
                    params={"query": "password-target"},
                )
                self.assertEqual(search.status_code, 200)
                self.assertEqual(search.json()["users"][0]["id"], member.json()["id"])

                reset = admin_client.patch(
                    f'/api/scrim/admin/users/{member.json()["id"]}/password',
                    json={"new_password": "newpass"},
                )
                self.assertEqual(reset.status_code, 200)
                self.assertNotIn("password_hash", reset.json())

            old_after_reset = member_client.post(
                "/api/scrim/auth/login",
                json={"riot_id": "password-target#KR1", "password": "oldpass"},
            )
            self.assertEqual(old_after_reset.status_code, 401)
            new_after_reset = member_client.post(
                "/api/scrim/auth/login",
                json={"riot_id": "password-target#KR1", "password": "newpass"},
            )
            self.assertEqual(new_after_reset.status_code, 200)

    def test_scrim_management_page_loads(self):
        with TestClient(app) as client:
            response = client.get("/scrim")
            self.assertEqual(response.status_code, 200)
            self.assertIn("스크림 관리", response.text)
            self.assertIn("/static/scrim.js", response.text)


if __name__ == "__main__":
    unittest.main()
