import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

_DATA_FILE = Path(tempfile.gettempdir()) / "lol-auction-api-test.json"
if _DATA_FILE.exists():
    _DATA_FILE.unlink()
os.environ["DATA_FILE"] = str(_DATA_FILE)
os.environ["SCRIM_DB_FILE"] = str(
    Path(tempfile.gettempdir()) / f"lol-auction-api-test-scrim-{uuid.uuid4().hex}.db"
)
os.environ["SCRIM_ALLOW_PUBLIC_SIGNUP"] = "true"

from fastapi.testclient import TestClient

from app.main import app, store
from app import scrim_db
from app.scrim_db import db_path as scrim_db_path

ADMIN_RIOT_ID = "장원혁#ADMIN"
ADMIN_PASSWORD = "1234"


def login_as_host(client: TestClient):
    return client.post(
        "/api/scrim/auth/login",
        json={"riot_id": ADMIN_RIOT_ID, "password": ADMIN_PASSWORD},
    )


class ApiFlowTest(unittest.TestCase):
    def setUp(self):
        store.reset()
        store.active_competition["mode"] = "auction"
        store.save()
        path = scrim_db_path()
        if path.exists():
            path.unlink()

    def test_setup_and_start_flow(self):
        with TestClient(app) as client:
            root = client.get("/")
            self.assertEqual(root.status_code, 200)
            self.assertIn("SUMMONER'S AUCTION", root.text)

            login = login_as_host(client)
            self.assertEqual(login.status_code, 200)

            settings = client.put(
                "/api/settings",
                json={
                    "room_name": "테스트 경매",
                    "countdown_seconds": 5,
                    "minimum_bid": 10,
                    "bid_increment": 5,
                    "extension_trigger_seconds": 2,
                    "extension_seconds": 3,
                },
            )
            self.assertEqual(settings.status_code, 200)

            captain_player = client.post(
                "/api/players",
                json={
                    "name": "탑팀장",
                    "riot_id": "탑팀장#KR1",
                    "tier": "PLATINUM IV",
                    "primary_position": "TOP",
                    "secondary_position": None,
                },
            )
            self.assertEqual(captain_player.status_code, 200)

            captain_client = TestClient(app)
            signup = captain_client.post(
                "/api/scrim/users",
                json={
                    "name": "탑팀장",
                    "riot_id": "탑팀장#KR1",
                    "password": "captainpw",
                },
            )
            self.assertEqual(signup.status_code, 200)

            captain = client.post(
                "/api/captains",
                json={
                    "player_id": captain_player.json()["id"],
                    "budget": 100,
                    "riot_id": "탑팀장#KR1",
                },
            )
            self.assertEqual(captain.status_code, 200)
            self.assertNotIn("user_id", captain.json())

            player = client.post(
                "/api/players",
                json={
                    "name": "미드선수",
                    "riot_id": "미드선수#KR1",
                    "tier": "GOLD IV",
                    "primary_position": "MID",
                    "secondary_position": None,
                },
            )
            self.assertEqual(player.status_code, 200)

            started = client.post("/api/auction/start")
            self.assertEqual(started.status_code, 200)

            state = client.get("/api/state").json()
            self.assertEqual(state["auction"]["status"], "ready")
            self.assertEqual(state["settings"]["room_name"], "테스트 경매")
            timer_started = client.post("/api/auction/timer/start")
            self.assertEqual(timer_started.status_code, 200)

            bid = captain_client.post(
                "/api/auction/bid",
                json={"amount": 20},
            )
            self.assertEqual(bid.status_code, 200)
            self.assertEqual(bid.json()["amount"], 20)

            state = captain_client.get("/api/state").json()
            self.assertEqual(state["viewer"]["role"], "captain")
            self.assertNotIn("user_id", state["captains"][0])

    def test_admin_roster_update_issues_member_account(self):
        with TestClient(app) as client:
            login = login_as_host(client)
            self.assertEqual(login.status_code, 200)

            with scrim_db.connect() as connection:
                entry = scrim_db.upsert_roster_entry(
                    connection,
                    source_row=200,
                    name="Roster User",
                    riot_id=None,
                    preferred_lines="MID",
                )

            roster = client.get("/api/roster?filter=without_id")
            self.assertEqual(roster.status_code, 200)
            self.assertTrue(
                any(item["id"] == entry["id"] for item in roster.json()["entries"])
            )

            updated = client.patch(
                f"/api/roster/{entry['id']}",
                json={
                    "name": "Roster User",
                    "riot_id": "RosterUser#KR1",
                    "secondary_riot_id": "RosterSub#KR1",
                    "preferred_lines": "MID",
                },
            )
            self.assertEqual(updated.status_code, 200)
            payload = updated.json()
            self.assertEqual(payload["account_status"], "ISSUED")
            self.assertEqual(payload["tournament_status"], "not_applied")

            member_login = client.post(
                "/api/scrim/auth/login",
                json={"riot_id": "RosterUser#KR1", "password": "1234"},
            )
            self.assertEqual(member_login.status_code, 200)

    def test_spectator_cannot_start_auction(self):
        with TestClient(app) as client:
            response = client.post("/api/auction/start")
            self.assertEqual(response.status_code, 403)

    def test_teacher_manages_competitions_and_delete_cascades(self):
        with TestClient(app) as client:
            login_as_host(client)
            created = client.post(
                "/api/competitions",
                json={"name": "여름 멸망전", "mode": "tournament"},
            )
            self.assertEqual(created.status_code, 200)
            competition_id = created.json()["id"]
            player = client.post(
                "/api/players",
                json={
                    "name": "대회 참가자",
                    "riot_id": "",
                    "tier": "GOLD",
                    "score": 8,
                    "primary_position": "TOP",
                    "secondary_position": None,
                },
            )
            self.assertEqual(player.status_code, 200)
            state = client.get("/api/state").json()
            self.assertEqual(
                state["competition_registry"]["active_competition_id"],
                competition_id,
            )
            self.assertEqual(len(state["players"]), 1)

            deleted = client.delete(f"/api/competitions/{competition_id}")
            self.assertEqual(deleted.status_code, 200)
            after = client.get("/api/state").json()
            self.assertNotEqual(
                after["competition_registry"]["active_competition_id"],
                competition_id,
            )
            self.assertEqual(len(after["players"]), 0)

    def test_captain_role_does_not_leak_across_competitions(self):
        with TestClient(app) as client:
            login_as_host(client)
            client.post(
                "/api/competitions",
                json={"name": "팀장 배정 대회", "mode": "auction"},
            )
            player = client.post(
                "/api/players",
                json={
                    "name": "팀장후보",
                    "riot_id": "",
                    "tier": "GOLD",
                    "primary_position": "TOP",
                    "secondary_position": None,
                },
            ).json()

            captain_client = TestClient(app)
            captain_client.post(
                "/api/scrim/users",
                json={
                    "name": "팀장후보",
                    "riot_id": "팀장후보#KR1",
                    "password": "pw1234",
                },
            )
            captain = client.post(
                "/api/captains",
                json={
                    "player_id": player["id"],
                    "budget": 100,
                    "riot_id": "팀장후보#KR1",
                },
            )
            self.assertEqual(captain.status_code, 200)

            state = captain_client.get("/api/state").json()
            self.assertEqual(state["viewer"]["role"], "captain")

            created = client.post(
                "/api/competitions",
                json={"name": "다른 대회", "mode": "tournament"},
            )
            self.assertEqual(created.status_code, 200)

            state_after_switch = captain_client.get("/api/state").json()
            self.assertEqual(state_after_switch["viewer"]["role"], "spectator")

    def test_creating_captain_requires_existing_account(self):
        with TestClient(app) as client:
            login_as_host(client)
            player = client.post(
                "/api/players",
                json={
                    "name": "미가입자",
                    "riot_id": "",
                    "tier": "GOLD",
                    "primary_position": "TOP",
                    "secondary_position": None,
                },
            ).json()
            response = client.post(
                "/api/captains",
                json={
                    "player_id": player["id"],
                    "budget": 100,
                    "riot_id": "존재하지않음#KR1",
                },
            )
            self.assertEqual(response.status_code, 400)

    def test_teacher_can_edit_player_doomsday_score(self):
        with TestClient(app) as client:
            login_as_host(client)
            player = client.post(
                "/api/players",
                json={
                    "name": "점수수정",
                    "riot_id": "",
                    "tier": "GOLD",
                    "score": 5,
                    "primary_position": "MID",
                    "secondary_position": None,
                },
            ).json()
            updated = client.patch(
                f'/api/players/{player["id"]}/score',
                json={"score": 9},
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["score"], 9)

    def test_teacher_can_set_team_total_score_limit(self):
        with TestClient(app) as client:
            login_as_host(client)
            response = client.put(
                "/api/tournament/settings", json={"score_limit": 55}
            )
            self.assertEqual(response.status_code, 200)
            state = client.get("/api/state").json()
            self.assertEqual(state["tournament"]["score_limit"], 55)

    def test_public_simulator_recommends_from_partial_lineup(self):
        with TestClient(app) as client:
            login_as_host(client)
            ids = {}
            for position, score in zip(
                ("TOP", "JUG", "MID", "ADC", "SUP"), (8, 7, 10, 9, 6)
            ):
                player = client.post(
                    "/api/players",
                    json={
                        "name": position,
                        "riot_id": "",
                        "tier": "GOLD",
                        "score": score,
                        "primary_position": position,
                        "secondary_position": None,
                    },
                ).json()
                ids[position] = player["id"]
            client.post("/api/scrim/auth/logout")
            response = client.post(
                "/api/tournament/recommend",
                json={
                    "locked": {
                        "TOP": ids["TOP"],
                        "JUG": None,
                        "MID": ids["MID"],
                        "ADC": None,
                        "SUP": None,
                    },
                    "limit": 5,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["recommendations"][0]["total_score"], 40
            )

    def test_team_pages_are_separated(self):
        with TestClient(app) as client:
            simulator = client.get("/team-simulator")
            registration = client.get("/team-register")
            tournament = client.get("/tournament")
            participation = client.get("/participation")
            members = client.get("/members")
            mypage = client.get("/mypage")
            score_players = client.get("/score-players")
            self.assertEqual(simulator.status_code, 200)
            self.assertEqual(registration.status_code, 200)
            self.assertEqual(tournament.status_code, 200)
            self.assertEqual(participation.status_code, 200)
            self.assertEqual(members.status_code, 200)
            self.assertEqual(mypage.status_code, 200)
            self.assertEqual(score_players.status_code, 200)
            self.assertIn("team-simulator-panel", simulator.text)
            self.assertIn("team-register-panel", registration.text)
            self.assertIn("tournament-panel", tournament.text)
            self.assertIn("participation-panel", participation.text)
            self.assertIn("members-panel", members.text)
            self.assertIn("mypage-panel", mypage.text)

    def test_host_opens_participation_and_splits_applicants(self):
        with TestClient(app) as host_client:
            login_as_host(host_client)
            settings = host_client.put(
                "/api/participation/settings",
                json={
                    "enabled": True,
                    "terms": "테스트 약관에 동의합니다.",
                },
            )
            self.assertEqual(settings.status_code, 200)

            with TestClient(app) as applicant_client:
                applicant = applicant_client.post(
                    "/api/scrim/users",
                    json={
                        "name": "Applicant",
                        "riot_id": "applicant#KR1",
                        "password": "1234",
                    },
                )
                self.assertEqual(applicant.status_code, 200)
                host_client.patch(
                    f'/api/scrim/admin/users/{applicant.json()["id"]}/approval',
                    json={"approved": True},
                )

                with TestClient(app) as waiting_client:
                    waiting = waiting_client.post(
                        "/api/scrim/users",
                        json={
                            "name": "Waiting",
                            "riot_id": "waiting#KR1",
                            "password": "1234",
                        },
                    )
                    self.assertEqual(waiting.status_code, 200)
                    host_client.patch(
                        f'/api/scrim/admin/users/{waiting.json()["id"]}/approval',
                        json={"approved": True},
                    )

                applied = applicant_client.post(
                    "/api/participation/apply",
                    json={"terms_agreed": True},
                )
                self.assertEqual(applied.status_code, 200)

            applications = host_client.get("/api/participation/applications")
            self.assertEqual(applications.status_code, 200)
            applied_ids = {user["riot_id"] for user in applications.json()["applied"]}
            not_applied_ids = {
                user["riot_id"] for user in applications.json()["not_applied"]
            }
            self.assertIn("applicant#KR1", applied_ids)
            self.assertIn("waiting#KR1", not_applied_ids)

    def test_participant_registers_team_and_host_sets_score_limit(self):
        with TestClient(app) as client:
            login_as_host(client)
            settings = client.put(
                "/api/tournament/settings", json={"score_limit": 40}
            )
            self.assertEqual(settings.status_code, 200)
            players = {}
            for name, position, score in (
                ("탑", "TOP", 8),
                ("정글", "JUG", 7),
                ("미드", "MID", 10),
                ("원딜", "ADC", 9),
                ("서폿", "SUP", 6),
            ):
                response = client.post(
                    "/api/players",
                    json={
                        "name": name,
                        "riot_id": "",
                        "tier": "GOLD",
                        "score": score,
                        "primary_position": position,
                        "secondary_position": None,
                    },
                )
                players[position] = response.json()["id"]

            response = client.post(
                "/api/tournament/teams",
                json={
                    "name": "참가자 직접 등록팀",
                    "registration_pin": "5678",
                    "members": {
                        "TOP": players["TOP"],
                        "JUG": players["JUG"],
                        "MID": players["MID"],
                        "ADC": players["ADC"],
                        "SUP": players["SUP"],
                    },
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["total_score"], 40)
            self.assertNotIn("registration_pin", response.json())

    def test_team_member_can_create_and_update_scrim_result(self):
        with TestClient(app) as host_client:
            login_as_host(host_client)
            players = {}
            for name, riot_id, position, score in (
                ("Result Top", "result-member#KR1", "TOP", 8),
                ("Result Jug", "result-jug#KR1", "JUG", 7),
                ("Result Mid", "result-mid#KR1", "MID", 10),
                ("Result Adc", "result-adc#KR1", "ADC", 9),
                ("Result Sup", "result-sup#KR1", "SUP", 6),
            ):
                response = host_client.post(
                    "/api/players",
                    json={
                        "name": name,
                        "riot_id": riot_id,
                        "tier": "GOLD",
                        "score": score,
                        "primary_position": position,
                        "secondary_position": None,
                    },
                )
                self.assertEqual(response.status_code, 200)
                players[position] = response.json()["id"]

            team = host_client.post(
                "/api/tournament/teams",
                json={
                    "name": "Result Team",
                    "registration_pin": "5678",
                    "members": {
                        "TOP": players["TOP"],
                        "JUG": players["JUG"],
                        "MID": players["MID"],
                        "ADC": players["ADC"],
                        "SUP": players["SUP"],
                    },
                },
            )
            self.assertEqual(team.status_code, 200)
            team_id = team.json()["id"]

            with TestClient(app) as member_client:
                member = member_client.post(
                    "/api/scrim/users",
                    json={
                        "name": "Result Member",
                        "riot_id": "result-member#KR1",
                        "password": "1234",
                    },
                )
                self.assertEqual(member.status_code, 200)
                approval = host_client.patch(
                    f'/api/scrim/admin/users/{member.json()["id"]}/approval',
                    json={"approved": True},
                )
                self.assertEqual(approval.status_code, 200)

                with patch(
                    "app.main.upload_result_image_to_blob",
                    return_value={
                        "url": "https://example.public.blob.vercel-storage.com/result.webp",
                        "downloadUrl": "https://example.public.blob.vercel-storage.com/result.webp?download=1",
                        "pathname": "scrim-results/team/result.webp",
                    },
                ):
                    uploaded = member_client.post(
                        "/api/scrim/results/image",
                        params={"team_id": team_id, "filename": "result.webp"},
                        content=b"webp-bytes",
                        headers={"content-type": "image/webp"},
                    )
                self.assertEqual(uploaded.status_code, 200)
                self.assertEqual(uploaded.json()["size_bytes"], 10)
                self.assertEqual(
                    uploaded.json()["url"],
                    "https://example.public.blob.vercel-storage.com/result.webp",
                )

                created = member_client.post(
                    "/api/scrim/results",
                    json={
                        "team_id": team_id,
                        "match_date": "2026-07-07",
                        "opponent_team_name": "Opponent",
                        "our_score": 2,
                        "opponent_score": 1,
                        "image_url": "https://example.com/result.webp",
                        "image_size_bytes": 120000,
                    },
                )
                self.assertEqual(created.status_code, 200)
                self.assertEqual(created.json()["result"], "WIN")
                self.assertEqual(created.json()["image_url"], "https://example.com/result.webp")

                updated = member_client.put(
                    f'/api/scrim/results/{created.json()["id"]}',
                    json={
                        "team_id": team_id,
                        "match_date": "2026-07-08",
                        "opponent_team_name": "Opponent 2",
                        "our_score": 0,
                        "opponent_score": 0,
                        "image_url": "https://example.com/result.webp",
                        "image_size_bytes": 120000,
                    },
                )
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()["result"], "DRAW")

                too_large = member_client.post(
                    "/api/scrim/results",
                    json={
                        "team_id": team_id,
                        "match_date": "2026-07-09",
                        "opponent_team_name": "Opponent",
                        "our_score": 1,
                        "opponent_score": 1,
                        "image_url": "https://example.com/large.webp",
                        "image_size_bytes": 1048577,
                    },
                )
                self.assertEqual(too_large.status_code, 400)

            with TestClient(app) as outsider_client:
                outsider = outsider_client.post(
                    "/api/scrim/users",
                    json={
                        "name": "Outsider",
                        "riot_id": "outsider#KR1",
                        "password": "1234",
                    },
                )
                self.assertEqual(outsider.status_code, 200)
                host_client.patch(
                    f'/api/scrim/admin/users/{outsider.json()["id"]}/approval',
                    json={"approved": True},
                )
                forbidden = outsider_client.post(
                    "/api/scrim/results",
                    json={
                        "team_id": team_id,
                        "match_date": "2026-07-07",
                        "opponent_team_name": "Opponent",
                        "our_score": 1,
                        "opponent_score": 1,
                    },
                )
                self.assertEqual(forbidden.status_code, 403)

    def test_websocket_sends_initial_state(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as websocket:
                message = websocket.receive_json()
                self.assertEqual(message["type"], "state")
                self.assertIn("auction", message["data"])


if __name__ == "__main__":
    unittest.main()
