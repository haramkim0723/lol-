import time
import unittest

from app import engine


class AuctionEngineTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.new_state()
        self.state["settings"]["countdown_seconds"] = 5
        self.state["settings"]["minimum_bid"] = 10
        self.state["settings"]["bid_increment"] = 5
        self.player = engine.add_player(
            self.state, "선수", "선수#KR1", "GOLD IV", "MID"
        )
        self.captain_player = engine.add_player(
            self.state, "팀장", "팀장#KR1", "PLATINUM IV", "TOP"
        )
        self.captain = engine.add_captain(
            self.state, self.captain_player["id"], 100, "1234"
        )

    def test_captain_is_assigned_to_own_position_without_cost(self):
        self.assertEqual(
            self.captain["team"]["TOP"], self.captain_player["id"]
        )
        self.assertEqual(self.captain_player["status"], "captain")
        self.assertEqual(self.captain["remaining_budget"], 100)

    def test_successful_bid_deducts_budget_and_assigns_position(self):
        engine.start_auction(self.state, shuffle=False)
        engine.place_bid(self.state, self.captain["id"], 20)
        engine.finalize_if_due(self.state, now=time.time() + 10)
        self.assertEqual(self.captain["remaining_budget"], 80)
        self.assertEqual(self.captain["team"]["MID"], self.player["id"])
        self.assertEqual(self.player["status"], "sold")

    def test_unsold_player_moves_to_separate_list(self):
        engine.start_auction(self.state, shuffle=False)
        engine.finalize_if_due(self.state, now=time.time() + 10)
        self.assertEqual(self.state["auction"]["status"], "waiting_reauction")
        self.assertEqual(self.state["auction"]["unsold"], [self.player["id"]])
        self.assertEqual(self.player["unsold_count"], 1)

    def test_bid_must_reserve_minimum_for_empty_slots(self):
        engine.start_auction(self.state, shuffle=False)
        with self.assertRaisesRegex(ValueError, "최대 70점"):
            engine.place_bid(self.state, self.captain["id"], 80)


class TournamentEngineTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.new_state()
        self.members = {}
        for position, score in zip(engine.POSITIONS, (8, 7, 10, 9, 6)):
            player = engine.add_player(
                self.state, position, "", "GOLD", position, score=score
            )
            self.members[position] = player["id"]

    def test_people_can_register_complete_team_within_limit(self):
        team = engine.register_tournament_team(
            self.state, "직접 만든 팀", self.members, "1234"
        )
        self.assertEqual(team["total_score"], 40)
        self.assertEqual(team["status"], "pending")

    def test_team_over_host_score_limit_is_rejected(self):
        self.state["tournament"]["score_limit"] = 39
        with self.assertRaisesRegex(ValueError, "제한 39점"):
            engine.register_tournament_team(
                self.state, "초과 팀", self.members, "1234"
            )

    def test_approved_teams_create_bracket_and_winner_advances(self):
        first = engine.register_tournament_team(
            self.state, "A팀", self.members, "1234"
        )
        engine.approve_tournament_team(self.state, first["id"], True)
        second_members = {}
        for position, score in zip(engine.POSITIONS, (7, 7, 8, 8, 7)):
            player = engine.add_player(
                self.state, f"B{position}", "", "GOLD", position, score=score
            )
            second_members[position] = player["id"]
        second = engine.register_tournament_team(
            self.state, "B팀", second_members, "5678"
        )
        engine.approve_tournament_team(self.state, second["id"], True)
        engine.start_tournament(self.state)
        match = self.state["tournament"]["rounds"][0][0]
        winner = match["team1_id"]
        engine.select_match_winner(self.state, 0, 0, winner)
        self.assertEqual(self.state["tournament"]["champion_id"], winner)
        self.assertEqual(self.state["tournament"]["status"], "finished")


if __name__ == "__main__":
    unittest.main()
