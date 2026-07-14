import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ["SCRIM_DB_FILE"] = str(
    Path(tempfile.gettempdir()) / f"lol-scrim-api-test-{uuid.uuid4().hex}.db"
)
os.environ["SCRIM_ALLOW_PUBLIC_SIGNUP"] = "true"

from fastapi.testclient import TestClient

from app.main import app
from app.scrim_db import db_path
from app.scrim_api import make_session, read_session


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

    def test_invalid_session_cookie_is_rejected(self):
        with TestClient(app) as client:
            client.get("/api/scrim/health")
            client.cookies.set("scrim_auth", "not-a-valid-session")
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
                self.assertFalse(search.json()["users"][0]["approved"])

                approval = admin_client.patch(
                    f'/api/scrim/admin/users/{member.json()["id"]}/approval',
                    json={"approved": True},
                )
                self.assertEqual(approval.status_code, 200)
                self.assertTrue(approval.json()["approved"])

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

    def test_public_signup_blocked_and_admin_creates_member_with_secondary_id(self):
        with patch.dict(os.environ, {"SCRIM_ALLOW_PUBLIC_SIGNUP": ""}):
            with TestClient(app) as client:
                client.get("/api/scrim/health")
                blocked = client.post(
                    "/api/scrim/users",
                    json={
                        "name": "Blocked",
                        "riot_id": "blocked#KR1",
                        "password": "1234",
                    },
                )
                self.assertEqual(blocked.status_code, 403)

                admin_login = client.post(
                    "/api/scrim/auth/login",
                    json={
                        "riot_id": "\uc7a5\uc6d0\ud601#ADMIN",
                        "password": "1234",
                    },
                )
                self.assertEqual(admin_login.status_code, 200)
                created = client.post(
                    "/api/scrim/admin/users",
                    json={
                        "name": "Created Member",
                        "riot_id": "main#KR1",
                        "secondary_riot_id": "sub#KR1",
                    },
                )
                self.assertEqual(created.status_code, 200)
                self.assertEqual(created.json()["riot_id"], "main#KR1")
                self.assertEqual(created.json()["secondary_riot_id"], "sub#KR1")
                self.assertTrue(created.json()["approved"])

            with TestClient(app) as member_client:
                login = member_client.post(
                    "/api/scrim/auth/login",
                    json={"riot_id": "main#KR1", "password": "1234"},
                )
                self.assertEqual(login.status_code, 200)
                updated = member_client.patch(
                    "/api/scrim/me",
                    json={
                        "riot_id": "changed#KR1",
                        "secondary_riot_id": "changed-sub#KR1",
                        "nickname": "Changed",
                        "password": "5678",
                    },
                )
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()["riot_id"], "changed#KR1")
                self.assertEqual(updated.json()["secondary_riot_id"], "changed-sub#KR1")

            with TestClient(app) as old_password_client:
                old_login = old_password_client.post(
                    "/api/scrim/auth/login",
                    json={"riot_id": "changed#KR1", "password": "1234"},
                )
                self.assertEqual(old_login.status_code, 401)
                random_login = old_password_client.post(
                    "/api/scrim/auth/login",
                    json={"riot_id": "changed#KR1", "password": "wrongpass"},
                )
                self.assertEqual(random_login.status_code, 401)
                new_login = old_password_client.post(
                    "/api/scrim/auth/login",
                    json={"riot_id": "changed#KR1", "password": "5678"},
                )
                self.assertEqual(new_login.status_code, 200)

    def test_scrim_page_serves_main_spa_with_scrim_tab(self):
        with TestClient(app) as client:
            response = client.get("/scrim")
            self.assertEqual(response.status_code, 200)
            self.assertIn('data-view="scrim"', response.text)
            self.assertIn("/static/app.js", response.text)

            competition_room = client.get("/competition-room")
            self.assertEqual(competition_room.status_code, 200)
            self.assertIn("대회 진행방", competition_room.text)

    def test_login_session_expires_after_one_hour(self):
        user = {"id": 123, "role": "USER"}
        with patch("app.scrim_api.time.time", return_value=1_000):
            token = make_session(user)
        with patch("app.scrim_api.time.time", return_value=4_599):
            self.assertEqual(read_session(token)["user_id"], 123)
        with patch("app.scrim_api.time.time", return_value=4_600):
            self.assertIsNone(read_session(token))


if __name__ == "__main__":
    unittest.main()
