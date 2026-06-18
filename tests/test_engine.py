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


class BalanceEngineTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.new_state()
        self.top = engine.add_player(
            self.state, "탑고정", "", "GOLD", "TOP", score=8
        )
        self.jug = engine.add_player(
            self.state, "정글고정", "", "GOLD", "JUG", score=7
        )
        self.mid = engine.add_player(
            self.state, "미드고정", "", "GOLD", "MID", score=10
        )
        engine.add_player(
            self.state, "원딜A", "", "GOLD", "ADC", score=9
        )
        engine.add_player(
            self.state, "원딜B", "", "GOLD", "ADC", score=5
        )
        engine.add_player(
            self.state, "서폿A", "", "GOLD", "SUP", score=6
        )
        engine.add_player(
            self.state, "서폿B", "", "GOLD", "MID", "SUP", score=4
        )
        engine.add_player(
            self.state, "서폿C", "", "GOLD", "SUP", score=4
        )

    def test_locked_core_recommends_closest_bottom_duo(self):
        recommendations = engine.recommend_completions(
            self.state,
            {
                "TOP": self.top["id"],
                "JUG": self.jug["id"],
                "MID": self.mid["id"],
                "ADC": None,
                "SUP": None,
            },
            target_score=40,
        )
        self.assertEqual(recommendations[0]["total_score"], 40)
        self.assertEqual(
            recommendations[0]["lineup"]["ADC"]["name"], "원딜A"
        )
        self.assertEqual(
            recommendations[0]["lineup"]["SUP"]["name"], "서폿A"
        )

    def test_primary_position_wins_tie_over_secondary(self):
        recommendations = engine.recommend_completions(
            self.state,
            {
                "TOP": self.top["id"],
                "JUG": self.jug["id"],
                "MID": self.mid["id"],
                "ADC": None,
                "SUP": None,
            },
            target_score=38,
        )
        self.assertEqual(recommendations[0]["fit_penalty"], 0)
        self.assertEqual(
            recommendations[0]["lineup"]["SUP"]["name"], "서폿C"
        )


if __name__ == "__main__":
    unittest.main()
