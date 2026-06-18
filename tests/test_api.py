import os
import tempfile
import unittest
from pathlib import Path

os.environ["DATA_FILE"] = str(Path(tempfile.gettempdir()) / "lol-auction-api-test.json")

from fastapi.testclient import TestClient

from app.main import app, store


class ApiFlowTest(unittest.TestCase):
    def setUp(self):
        store.reset()

    def test_setup_and_start_flow(self):
        with TestClient(app) as client:
            root = client.get("/")
            self.assertEqual(root.status_code, 200)
            self.assertIn("SUMMONER'S AUCTION", root.text)

            login = client.post(
                "/api/login",
                json={"role": "host", "pin": "1234", "captain_id": None},
            )
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

            captain = client.post(
                "/api/captains",
                json={
                    "player_id": captain_player.json()["id"],
                    "budget": 100,
                    "pin": "5678",
                },
            )
            self.assertEqual(captain.status_code, 200)

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
            self.assertEqual(state["auction"]["status"], "running")
            self.assertEqual(state["settings"]["room_name"], "테스트 경매")

            captain_client = TestClient(app)
            captain_login = captain_client.post(
                "/api/login",
                json={
                    "role": "captain",
                    "pin": "5678",
                    "captain_id": captain.json()["id"],
                },
            )
            self.assertEqual(captain_login.status_code, 200)
            bid = captain_client.post(
                "/api/auction/bid",
                json={"amount": 20},
            )
            self.assertEqual(bid.status_code, 200)
            self.assertEqual(bid.json()["amount"], 20)

            state = captain_client.get("/api/state").json()
            self.assertEqual(state["viewer"]["role"], "captain")
            self.assertNotIn("pin", state["captains"][0])

    def test_spectator_cannot_start_auction(self):
        with TestClient(app) as client:
            client.post(
                "/api/login",
                json={"role": "spectator", "pin": "", "captain_id": None},
            )
            response = client.post("/api/auction/start")
            self.assertEqual(response.status_code, 403)

    def test_teacher_manages_competitions_and_delete_cascades(self):
        with TestClient(app) as client:
            client.post(
                "/api/login",
                json={"role": "host", "pin": "1234", "captain_id": None},
            )
            created = client.post(
                "/api/competitions", json={"name": "여름 멸망전"}
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

    def test_participant_registers_team_and_host_sets_score_limit(self):
        with TestClient(app) as client:
            client.post(
                "/api/login",
                json={"role": "host", "pin": "1234", "captain_id": None},
            )
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

            client.post("/api/logout")
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

    def test_websocket_sends_initial_state(self):
        with TestClient(app) as client:
            client.post(
                "/api/login",
                json={"role": "spectator", "pin": "", "captain_id": None},
            )
            with client.websocket_connect("/ws") as websocket:
                message = websocket.receive_json()
                self.assertEqual(message["type"], "state")
                self.assertIn("auction", message["data"])


if __name__ == "__main__":
    unittest.main()
