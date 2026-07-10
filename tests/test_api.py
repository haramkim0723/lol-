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
                    tier="D3",
                    preferred_lines="미드,서폿",
                )

            roster = client.get("/api/roster?filter=without_id")
            self.assertEqual(roster.status_code, 200)
            self.assertTrue(
                any(item["id"] == entry["id"] for item in roster.json()["entries"])
            )

            created = client.post(
                "/api/roster",
                json={
                    "name": "Manual Roster",
                    "riot_id": "ManualRoster#KR1",
                    "tier": "E4",
                    "preferred_lines": "탑,미드",
                },
            )
            self.assertEqual(created.status_code, 200)
            created_payload = created.json()
            self.assertEqual(created_payload["name"], "Manual Roster")
            self.assertEqual(created_payload["account_status"], "ISSUED")
            self.assertEqual(created_payload["tournament_status"], "not_applied")

            updated = client.patch(
                f"/api/roster/{entry['id']}",
                json={
                    "name": "Roster User",
                    "riot_id": "RosterUser#KR1",
                    "secondary_riot_id": "RosterSub#KR1",
                    "tier": "D3",
                    "preferred_lines": "미드,서폿",
                },
            )
            self.assertEqual(updated.status_code, 200)
            payload = updated.json()
            self.assertEqual(payload["account_status"], "ISSUED")
            self.assertEqual(payload["tournament_status"], "not_applied")

            bulk = client.patch(
                "/api/roster",
                json={
                    "rows": [
                        {
                            "id": entry["id"],
                            "name": "Roster User",
                            "notes": "일괄 저장 확인",
                        }
                    ]
                },
            )
            self.assertEqual(bulk.status_code, 200)
            self.assertEqual(bulk.json()["updated"], 1)
            with scrim_db.connect() as connection:
                self.assertEqual(
                    scrim_db.get_roster_entry(connection, entry["id"])["notes"],
                    "일괄 저장 확인",
                )

            member_login = client.post(
                "/api/scrim/auth/login",
                json={"riot_id": "RosterUser#KR1", "password": "1234"},
            )
            self.assertEqual(member_login.status_code, 200)
            member_state = client.get("/api/state")
            self.assertEqual(member_state.status_code, 200)
            viewer = member_state.json()["viewer"]
            self.assertEqual(viewer["roster_tier"], "D3")
            self.assertEqual(
                viewer["score_lines"],
                [
                    {
                        "position": "MID",
                        "label": "미드",
                        "role": "주 라인",
                        "score": "34.3",
                    },
                    {
                        "position": "SUP",
                        "label": "서폿",
                        "role": "부 라인",
                        "score": "33.2",
                    },
                ],
            )

    def test_roster_applied_unpaid_filter(self):
        with TestClient(app) as client:
            login = login_as_host(client)
            self.assertEqual(login.status_code, 200)
            with scrim_db.connect() as connection:
                unpaid = scrim_db.upsert_roster_entry(
                    connection,
                    source_row=210,
                    name="Unpaid Applied",
                    participation_status_text="\ub300\ud68c \ucc38\uac00",
                    payment_status="X",
                )
                scrim_db.upsert_roster_entry(
                    connection,
                    source_row=211,
                    name="Paid Applied",
                    participation_status_text="\ub300\ud68c \ucc38\uac00",
                    payment_status="O",
                )
                scrim_db.upsert_roster_entry(
                    connection,
                    source_row=212,
                    name="Unpaid Not Applied",
                    participation_status_text="\ub300\ud68c \ubbf8\ucc38\uac00",
                    payment_status="X",
                )

            roster = client.get("/api/roster?filter=applied_unpaid")
            self.assertEqual(roster.status_code, 200)
            payload = roster.json()
            self.assertEqual(payload["stats"]["applied_unpaid"], 1)
            self.assertEqual([entry["id"] for entry in payload["entries"]], [unpaid["id"]])

    def test_roster_riot_preview_returns_tier_scores(self):
        async def fake_lookup_kr_player(riot_id: str):
            return {
                "name": "RosterUser#KR1",
                "riot_id": "RosterUser#KR1",
                "tier": "DIAMOND III \u00b7 12 LP",
                "champions": [],
                "profile_icon_url": None,
            }

        with TestClient(app) as client:
            login = login_as_host(client)
            self.assertEqual(login.status_code, 200)
            with patch("app.main.lookup_kr_player", fake_lookup_kr_player):
                response = client.post(
                    "/api/roster/riot/preview",
                    json={
                        "riot_id": "RosterUser#KR1",
                        "preferred_lines": "\ubbf8\ub4dc,\uc11c\ud3ff",
                    },
                )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["tier"], "D3")
            self.assertEqual(payload["scores"]["score_mid"], "34.3")
            self.assertEqual(payload["scores"]["score_support"], "33.2")

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

    def test_test_competitions_are_rebuilt_from_approved_members(self):
        with TestClient(app) as host_client:
            login_as_host(host_client)
            with TestClient(app) as member_client:
                member = member_client.post(
                    "/api/scrim/users",
                    json={
                        "name": "정회원",
                        "riot_id": "member#KR1",
                        "password": "1234",
                    },
                )
                self.assertEqual(member.status_code, 200)
            host_client.patch(
                f'/api/scrim/admin/users/{member.json()["id"]}/approval',
                json={"approved": True},
            )

            response = host_client.post("/api/admin/setup-test-competitions")

            self.assertEqual(response.status_code, 200)
            state = host_client.get("/api/state").json()
            competitions = state["competition_registry"]["competitions"]
            self.assertEqual(
                [competition["name"] for competition in competitions],
                ["test1", "test2"],
            )
            self.assertEqual(state["participation"]["application_count"], 0)
            host_client.post(
                "/api/competitions/test-score-approved/select"
            )
            test1 = host_client.get("/api/state").json()
            self.assertEqual(test1["participation"]["application_count"], 1)
            roster = host_client.get("/api/roster?filter=all").json()
            self.assertEqual(roster["stats"]["total"], 1)
            self.assertEqual(roster["entries"][0]["user_id"], member.json()["id"])

    def test_rejected_participation_can_be_reapplied(self):
        with TestClient(app) as host_client:
            login_as_host(host_client)
            with TestClient(app) as member_client:
                member = member_client.post(
                    "/api/scrim/users",
                    json={
                        "name": "Reject Reapply",
                        "riot_id": "reject-reapply#KR1",
                        "password": "1234",
                    },
                )
                self.assertEqual(member.status_code, 200)
                approval = host_client.patch(
                    f'/api/scrim/admin/users/{member.json()["id"]}/approval',
                    json={"approved": True},
                )
                self.assertEqual(approval.status_code, 200)
                settings = host_client.put(
                    "/api/participation/settings",
                    json={"enabled": True, "terms": "terms"},
                )
                self.assertEqual(settings.status_code, 200)

                login = member_client.post(
                    "/api/scrim/auth/login",
                    json={"riot_id": "reject-reapply#KR1", "password": "1234"},
                )
                self.assertEqual(login.status_code, 200)
                first_apply = member_client.post(
                    "/api/participation/apply",
                    json={"terms_agreed": True},
                )
                self.assertEqual(first_apply.status_code, 200)
                self.assertTrue(
                    member_client.get("/api/state").json()["participation"]["viewer_has_applied"]
                )

                rejected = host_client.patch(
                    f'/api/participation/applications/{member.json()["id"]}',
                    json={"status": "CANCELLED"},
                )
                self.assertEqual(rejected.status_code, 200)
                self.assertEqual(rejected.json()["status"], "CANCELLED")

                rejected_state = member_client.get("/api/state").json()
                self.assertFalse(rejected_state["participation"]["viewer_has_applied"])
                self.assertEqual(rejected_state["participation"]["application_count"], 0)
                applications = host_client.get("/api/participation/applications").json()
                self.assertEqual(applications["applied"], [])
                not_applied_user = next(
                    user
                    for user in applications["not_applied"]
                    if user["riot_id"] == "reject-reapply#KR1"
                )
                self.assertEqual(not_applied_user["participation_status"], "CANCELLED")

                second_apply = member_client.post(
                    "/api/participation/apply",
                    json={"terms_agreed": True},
                )
                self.assertEqual(second_apply.status_code, 200)
                reapplied_state = member_client.get("/api/state").json()
                self.assertTrue(reapplied_state["participation"]["viewer_has_applied"])
                self.assertEqual(reapplied_state["participation"]["application_count"], 1)

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

    def test_five_team_test_tournament_and_scrim_winrates(self):
        def create_team(client: TestClient, index: int) -> dict:
            members = {}
            for position_index, position in enumerate(("TOP", "JUG", "MID", "ADC", "SUP")):
                player = client.post(
                    "/api/players",
                    json={
                        "name": f"Test {index} {position}",
                        "riot_id": f"test{index}-{position.lower()}#KR1",
                        "tier": "GOLD",
                        "score": 1,
                        "primary_position": position,
                        "secondary_position": None,
                    },
                )
                self.assertEqual(player.status_code, 200)
                members[position] = player.json()["id"]
            team = client.post(
                "/api/tournament/teams",
                json={
                    "name": f"Test Team {index}",
                    "registration_pin": f"100{index}",
                    "members": members,
                },
            )
            self.assertEqual(team.status_code, 200)
            approval = client.post(
                f'/api/tournament/teams/{team.json()["id"]}/approval',
                json={"approved": True},
            )
            self.assertEqual(approval.status_code, 200)
            return approval.json()

        def scrim_stats(state_payload: dict) -> dict[str, dict[str, int]]:
            stats = {
                team["id"]: {
                    "set_wins": 0,
                    "set_losses": 0,
                    "series_wins": 0,
                    "series_losses": 0,
                    "bo3_wins": 0,
                    "bo3_losses": 0,
                    "bo5_wins": 0,
                    "bo5_losses": 0,
                }
                for team in state_payload["tournament"]["teams"]
            }
            for result in state_payload["scrim_results"]:
                a = stats[result["team_a_id"]]
                b = stats[result["team_b_id"]]
                a["set_wins"] += result["team_a_score"]
                a["set_losses"] += result["team_b_score"]
                b["set_wins"] += result["team_b_score"]
                b["set_losses"] += result["team_a_score"]
                a_won = result["winner_team_id"] == result["team_a_id"]
                a["series_wins"] += 1 if a_won else 0
                a["series_losses"] += 0 if a_won else 1
                b["series_wins"] += 0 if a_won else 1
                b["series_losses"] += 1 if a_won else 0
                prefix = "bo5" if result["best_of"] == 5 else "bo3"
                a[f"{prefix}_wins"] += 1 if a_won else 0
                a[f"{prefix}_losses"] += 0 if a_won else 1
                b[f"{prefix}_wins"] += 0 if a_won else 1
                b[f"{prefix}_losses"] += 1 if a_won else 0
            return stats

        with TestClient(app) as host_client:
            login_as_host(host_client)
            settings = host_client.put(
                "/api/tournament/settings",
                json={
                    "score_limit": 100,
                    "format": "group_then_knockout",
                    "group_count": 2,
                    "qualifiers_per_group": 2,
                },
            )
            self.assertEqual(settings.status_code, 200)
            teams = [create_team(host_client, index) for index in range(1, 6)]
            self.assertEqual(len(teams), 5)

            start = host_client.post("/api/tournament/start")
            self.assertEqual(start.status_code, 200)
            group_state = host_client.get("/api/state").json()
            self.assertEqual(group_state["tournament"]["status"], "group")
            self.assertEqual(len(group_state["tournament"]["teams"]), 5)
            for group_index, group in enumerate(group_state["tournament"]["groups"]):
                qualifiers = group["team_ids"][:2]
                response = host_client.put(
                    "/api/tournament/groups/qualifiers",
                    json={"group_index": group_index, "team_ids": qualifiers},
                )
                self.assertEqual(response.status_code, 200)
            knockout = host_client.post("/api/tournament/groups/start-knockout")
            self.assertEqual(knockout.status_code, 200)
            knockout_state = host_client.get("/api/state").json()
            first_match = knockout_state["tournament"]["rounds"][0][0]
            winner_id = first_match["team1_id"] or first_match["team2_id"]
            winner = host_client.post(
                "/api/tournament/winner",
                json={"round_index": 0, "match_index": 0, "team_id": winner_id},
            )
            self.assertEqual(winner.status_code, 200)

            for team_a, team_b, best_of, score_a, score_b in (
                (teams[0], teams[1], 3, 2, 0),
                (teams[0], teams[2], 3, 1, 2),
                (teams[3], teams[4], 5, 3, 2),
            ):
                result = host_client.post(
                    "/api/scrim/results",
                    json={
                        "team_a_id": team_a["id"],
                        "team_b_id": team_b["id"],
                        "match_date": "2026-07-10",
                        "best_of": best_of,
                        "team_a_score": score_a,
                        "team_b_score": score_b,
                    },
                )
                self.assertEqual(result.status_code, 200)

            state_payload = host_client.get("/api/state").json()
            self.assertEqual(len(state_payload["scrim_results"]), 3)
            stats = scrim_stats(state_payload)
            self.assertEqual(stats[teams[0]["id"]]["series_wins"], 1)
            self.assertEqual(stats[teams[0]["id"]]["series_losses"], 1)
            self.assertEqual(stats[teams[0]["id"]]["set_wins"], 3)
            self.assertEqual(stats[teams[0]["id"]]["set_losses"], 2)
            self.assertEqual(stats[teams[3]["id"]]["bo5_wins"], 1)
            self.assertEqual(
                round(
                    stats[teams[0]["id"]]["series_wins"]
                    / (
                        stats[teams[0]["id"]]["series_wins"]
                        + stats[teams[0]["id"]]["series_losses"]
                    )
                    * 100
                ),
                50,
            )

    def test_participation_approval_updates_member_and_roster_views(self):
        with TestClient(app) as host_client:
            login_as_host(host_client)
            with TestClient(app) as member_client:
                member = member_client.post(
                    "/api/scrim/users",
                    json={
                        "name": "Roster Applicant",
                        "riot_id": "roster-applicant#KR1",
                        "password": "1234",
                    },
                )
                self.assertEqual(member.status_code, 200)
                approval = host_client.patch(
                    f'/api/scrim/admin/users/{member.json()["id"]}/approval',
                    json={"approved": True},
                )
                self.assertEqual(approval.status_code, 200)

            setup = host_client.post("/api/admin/setup-test-competitions")
            self.assertEqual(setup.status_code, 200)
            with scrim_db.connect() as connection:
                roster_entry = scrim_db.get_roster_entry_by_user_id(
                    connection, member.json()["id"]
                )
                self.assertIsNotNone(roster_entry)
                scrim_db.update_roster_entry(
                    connection,
                    roster_entry["id"],
                    {
                        "tier": "D3",
                        "preferred_lines": "정글,미드,원딜",
                    },
                )
            select = host_client.post("/api/competitions/test2-score-open/select")
            self.assertEqual(select.status_code, 200)
            state = host_client.get("/api/state").json()
            self.assertTrue(state["participation"]["enabled"])
            current_roster_before_apply = host_client.get("/api/roster?filter=all").json()
            current_entry_before_apply = next(
                entry
                for entry in current_roster_before_apply["entries"]
                if entry["riot_id"] == "roster-applicant#KR1"
            )
            self.assertEqual(current_entry_before_apply["tournament_status"], "not_applied")
            self.assertEqual(current_entry_before_apply["participation_count"], 1)

            with TestClient(app) as member_client:
                login = member_client.post(
                    "/api/scrim/auth/login",
                    json={"riot_id": "roster-applicant#KR1", "password": "1234"},
                )
                self.assertEqual(login.status_code, 200)
                apply = member_client.post(
                    "/api/participation/apply",
                    json={"terms_agreed": True},
                )
                self.assertEqual(apply.status_code, 200)

            applications = host_client.get("/api/participation/applications")
            self.assertEqual(applications.status_code, 200)
            applied = applications.json()["applied"]
            self.assertEqual([user["riot_id"] for user in applied], ["roster-applicant#KR1"])
            self.assertEqual(applied[0]["participation_status"], "APPLIED")

            approved = host_client.patch(
                f'/api/participation/applications/{member.json()["id"]}',
                json={"status": "APPROVED"},
            )
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.json()["status"], "APPROVED")
            with scrim_db.connect() as connection:
                connection.execute(
                    "UPDATE roster_entries SET user_id = NULL WHERE riot_id = ?",
                    ("roster-applicant#KR1",),
                )

            members = host_client.get("/api/members").json()
            matching_members = [
                item
                for item in members["members"]
                if item["riot_id"] == "roster-applicant#KR1"
            ]
            self.assertEqual(len(matching_members), 1)
            self.assertEqual(matching_members[0]["participation_status"], "applied")
            self.assertEqual(members["stats"]["applied"], 1)

            roster = host_client.get("/api/roster?filter=applied").json()
            self.assertEqual(roster["stats"]["applied"], 1)
            matching_roster = [
                entry
                for entry in roster["entries"]
                if entry["riot_id"] == "roster-applicant#KR1"
            ]
            self.assertEqual(len(matching_roster), 1)
            self.assertEqual(matching_roster[0]["tournament_status"], "applied")
            store.state["players"] = []
            store.save()
            state_after_approval = host_client.get("/api/state").json()
            matching_players = [
                player
                for player in state_after_approval["players"]
                if player["riot_id"] == "roster-applicant#KR1"
            ]
            self.assertEqual(len(matching_players), 1)
            self.assertEqual(matching_players[0]["primary_position"], "JUG")
            self.assertEqual(matching_players[0]["secondary_position"], "MID")
            self.assertEqual(matching_players[0]["extra_positions"], ["ADC"])
            self.assertEqual(matching_players[0]["position_scores"]["JUG"], 34.9)

    def test_test3_full_flow_from_new_competition_to_results(self):
        positions = ("TOP", "JUG", "MID", "ADC", "SUP")

        def scrim_stats(state_payload: dict) -> dict[str, dict[str, int]]:
            stats = {
                team["id"]: {
                    "set_wins": 0,
                    "set_losses": 0,
                    "series_wins": 0,
                    "series_losses": 0,
                }
                for team in state_payload["tournament"]["teams"]
            }
            for result in state_payload["scrim_results"]:
                a = stats[result["team_a_id"]]
                b = stats[result["team_b_id"]]
                a["set_wins"] += result["team_a_score"]
                a["set_losses"] += result["team_b_score"]
                b["set_wins"] += result["team_b_score"]
                b["set_losses"] += result["team_a_score"]
                a_won = result["winner_team_id"] == result["team_a_id"]
                a["series_wins"] += 1 if a_won else 0
                a["series_losses"] += 0 if a_won else 1
                b["series_wins"] += 0 if a_won else 1
                b["series_losses"] += 1 if a_won else 0
            return stats

        with TestClient(app) as host_client:
            login_as_host(host_client)
            users = []
            for index in range(10):
                with TestClient(app) as member_client:
                    member = member_client.post(
                        "/api/scrim/users",
                        json={
                            "name": f"Test3 Member {index + 1}",
                            "riot_id": f"test3-member-{index + 1}#KR1",
                            "password": "1234",
                        },
                    )
                    self.assertEqual(member.status_code, 200)
                    approval = host_client.patch(
                        f'/api/scrim/admin/users/{member.json()["id"]}/approval',
                        json={"approved": True},
                    )
                    self.assertEqual(approval.status_code, 200)
                    users.append(member.json())

            created = host_client.post(
                "/api/competitions",
                json={
                    "name": "test3",
                    "mode": "tournament",
                    "tournament_format": "single_elimination",
                },
            )
            self.assertEqual(created.status_code, 200)
            competition_id = created.json()["id"]
            initial_state = host_client.get("/api/state").json()
            self.assertEqual(
                initial_state["competition_registry"]["active_competition_id"],
                competition_id,
            )
            self.assertEqual(initial_state["settings"]["room_name"], "test3")
            self.assertEqual(initial_state["participation"]["application_count"], 0)
            self.assertFalse(initial_state["participation"]["enabled"])
            self.assertEqual(initial_state["tournament"]["status"], "registration")
            self.assertEqual(initial_state["tournament"]["teams"], [])
            self.assertEqual(initial_state["scrim_results"], [])

            applications = host_client.get("/api/participation/applications")
            self.assertEqual(applications.status_code, 200)
            self.assertEqual(applications.json()["applied"], [])
            self.assertEqual(
                {user["riot_id"] for user in applications.json()["not_applied"]},
                {user["riot_id"] for user in users},
            )

            settings = host_client.put(
                "/api/participation/settings",
                json={"enabled": True, "terms": "test3 participation terms"},
            )
            self.assertEqual(settings.status_code, 200)

            approved_user_ids = []
            for user in users:
                with TestClient(app) as member_client:
                    login = member_client.post(
                        "/api/scrim/auth/login",
                        json={"riot_id": user["riot_id"], "password": "1234"},
                    )
                    self.assertEqual(login.status_code, 200)
                    apply = member_client.post(
                        "/api/participation/apply",
                        json={"terms_agreed": True},
                    )
                    self.assertEqual(apply.status_code, 200)
                pending = host_client.get("/api/participation/applications").json()
                pending_user = next(
                    item for item in pending["applied"] if item["riot_id"] == user["riot_id"]
                )
                self.assertEqual(pending_user["participation_status"], "APPLIED")
                approved = host_client.patch(
                    f'/api/participation/applications/{user["id"]}',
                    json={"status": "APPROVED"},
                )
                self.assertEqual(approved.status_code, 200)
                self.assertEqual(approved.json()["status"], "APPROVED")
                approved_user_ids.append(user["id"])

            after_approval = host_client.get("/api/state").json()
            self.assertEqual(after_approval["participation"]["application_count"], 10)
            roster = host_client.get("/api/roster?filter=applied&page_size=20").json()
            self.assertEqual(roster["stats"]["applied"], 10)
            self.assertEqual(
                {entry["riot_id"] for entry in roster["entries"]},
                {user["riot_id"] for user in users},
            )

            player_ids = []
            for index, user in enumerate(users):
                position = positions[index % len(positions)]
                player = host_client.post(
                    "/api/players",
                    json={
                        "name": user["name"],
                        "riot_id": user["riot_id"],
                        "tier": "GOLD",
                        "score": 1,
                        "primary_position": position,
                        "secondary_position": None,
                    },
                )
                self.assertEqual(player.status_code, 200)
                player_ids.append(player.json()["id"])

            teams = []
            for team_index, captain_user in enumerate((users[0], users[5])):
                with TestClient(app) as captain_client:
                    login = captain_client.post(
                        "/api/scrim/auth/login",
                        json={"riot_id": captain_user["riot_id"], "password": "1234"},
                    )
                    self.assertEqual(login.status_code, 200)
                    offset = team_index * 5
                    team = captain_client.post(
                        "/api/tournament/teams",
                        json={
                            "name": f"test3 Team {team_index + 1}",
                            "registration_pin": f"300{team_index + 1}",
                            "members": {
                                position: player_ids[offset + position_index]
                                for position_index, position in enumerate(positions)
                            },
                        },
                    )
                    self.assertEqual(team.status_code, 200)
                    teams.append(team.json())
                approval = host_client.post(
                    f'/api/tournament/teams/{teams[-1]["id"]}/approval',
                    json={"approved": True},
                )
                self.assertEqual(approval.status_code, 200)

            with TestClient(app) as captain_client:
                login = captain_client.post(
                    "/api/scrim/auth/login",
                    json={"riot_id": users[0]["riot_id"], "password": "1234"},
                )
                self.assertEqual(login.status_code, 200)
                scrim_result = captain_client.post(
                    "/api/scrim/results",
                    json={
                        "team_a_id": teams[0]["id"],
                        "team_b_id": teams[1]["id"],
                        "match_date": "2026-07-10",
                        "best_of": 3,
                        "team_a_score": 2,
                        "team_b_score": 1,
                    },
                )
                self.assertEqual(scrim_result.status_code, 200)
                self.assertEqual(scrim_result.json()["winner_team_id"], teams[0]["id"])

            state_with_scrim = host_client.get("/api/state").json()
            stats = scrim_stats(state_with_scrim)
            self.assertEqual(stats[teams[0]["id"]]["series_wins"], 1)
            self.assertEqual(stats[teams[1]["id"]]["series_losses"], 1)
            self.assertEqual(stats[teams[0]["id"]]["set_wins"], 2)
            self.assertEqual(stats[teams[0]["id"]]["set_losses"], 1)

            start = host_client.post("/api/tournament/start")
            self.assertEqual(start.status_code, 200)
            running_state = host_client.get("/api/state").json()
            self.assertEqual(running_state["tournament"]["status"], "running")
            match = running_state["tournament"]["rounds"][0][0]
            self.assertEqual({match["team1_id"], match["team2_id"]}, {teams[0]["id"], teams[1]["id"]})
            winner = host_client.post(
                "/api/tournament/winner",
                json={
                    "round_index": 0,
                    "match_index": 0,
                    "team_id": teams[0]["id"],
                },
            )
            self.assertEqual(winner.status_code, 200)
            finished_state = host_client.get("/api/state").json()
            self.assertEqual(finished_state["tournament"]["status"], "finished")
            self.assertEqual(finished_state["tournament"]["champion_id"], teams[0]["id"])

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
            opponent_id = uuid.uuid4().hex
            store.state["tournament"]["teams"].append(
                {
                    "id": opponent_id,
                    "name": "Opponent Team",
                    "members": {},
                    "status": "approved",
                    "total_score": 0,
                }
            )

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

                created = member_client.post(
                    "/api/scrim/results",
                    json={
                        "team_a_id": team_id,
                        "team_b_id": opponent_id,
                        "match_date": "2026-07-07",
                        "best_of": 3,
                        "team_a_score": 2,
                        "team_b_score": 1,
                    },
                )
                self.assertEqual(created.status_code, 200)
                self.assertEqual(created.json()["winner_team_id"], team_id)

                updated = member_client.put(
                    f'/api/scrim/results/{created.json()["id"]}',
                    json={
                        "team_a_id": team_id,
                        "team_b_id": opponent_id,
                        "match_date": "2026-07-08",
                        "best_of": 5,
                        "team_a_score": 2,
                        "team_b_score": 3,
                    },
                )
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()["winner_team_id"], opponent_id)

                invalid_score = member_client.post(
                    "/api/scrim/results",
                    json={
                        "team_a_id": team_id,
                        "team_b_id": opponent_id,
                        "match_date": "2026-07-09",
                        "best_of": 5,
                        "team_a_score": 2,
                        "team_b_score": 2,
                    },
                )
                self.assertEqual(invalid_score.status_code, 400)

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
                        "team_a_id": team_id,
                        "team_b_id": opponent_id,
                        "match_date": "2026-07-07",
                        "best_of": 3,
                        "team_a_score": 2,
                        "team_b_score": 1,
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
