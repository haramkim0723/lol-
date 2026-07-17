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
            self.state, self.captain_player["id"], 100, 1
        )

    def test_captain_is_assigned_to_own_position_without_cost(self):
        self.assertEqual(
            self.captain["team"]["TOP"], self.captain_player["id"]
        )
        self.assertEqual(self.captain_player["status"], "captain")
        self.assertEqual(self.captain["remaining_budget"], 100)

    def test_successful_bid_deducts_budget_and_assigns_position(self):
        engine.start_auction(self.state, shuffle=False)
        self.assertEqual(self.state["auction"]["status"], "ready")
        engine.start_timer(self.state)
        engine.place_bid(self.state, self.captain["id"], 20)
        engine.finalize_if_due(self.state, now=time.time() + 10)
        self.assertEqual(self.captain["remaining_budget"], 80)
        self.assertEqual(self.captain["team"]["MID"], self.player["id"])
        self.assertEqual(self.player["status"], "sold")

    def test_unsold_player_moves_to_separate_list(self):
        engine.start_auction(self.state, shuffle=False)
        engine.start_timer(self.state)
        engine.finalize_if_due(self.state, now=time.time() + 10)
        self.assertEqual(self.state["auction"]["status"], "waiting_reauction")
        self.assertEqual(self.state["auction"]["unsold"], [self.player["id"]])
        self.assertEqual(self.player["unsold_count"], 1)

    def test_bid_must_reserve_minimum_for_empty_slots(self):
        engine.start_auction(self.state, shuffle=False)
        engine.start_timer(self.state)
        with self.assertRaisesRegex(ValueError, "최대 70점"):
            engine.place_bid(self.state, self.captain["id"], 80)

    def test_each_candidate_waits_for_host_to_start_timer(self):
        second = engine.add_player(
            self.state, "두번째 선수", "두번째#KR1", "SILVER II", "ADC"
        )
        engine.start_auction(self.state, shuffle=False)
        self.assertEqual(self.state["auction"]["status"], "ready")
        self.assertIsNone(self.state["auction"]["deadline"])
        engine.start_timer(self.state)
        engine.finalize_if_due(self.state, now=time.time() + 10)
        self.assertEqual(self.state["auction"]["current_player_id"], second["id"])
        self.assertEqual(self.state["auction"]["status"], "ready")
        self.assertIsNone(self.state["auction"]["deadline"])


class TournamentEngineTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.new_state()
        self.members = {}
        for position, score in zip(engine.POSITIONS, (8, 7, 10, 9, 6)):
            player = engine.add_player(
                self.state, position, "", "GOLD", position, score=score
            )
            self.members[position] = player["id"]

    def make_complete_state(self):
        state = engine.new_state()
        members = {}
        for position, score in zip(engine.POSITIONS, (8, 7, 10, 9, 6)):
            player = engine.add_player(
                state, f"base-{position}", "", "GOLD", position, score=score
            )
            members[position] = player["id"]
        return state, members

    def test_public_state_hides_scores_until_score_visibility_is_enabled(self):
        hidden = engine.public_state(
            self.state,
            {"role": "participant", "authenticated": True, "user_id": 1},
        )
        self.assertFalse(hidden["participation"]["score_visible"])
        self.assertNotIn("score", hidden["players"][0])
        self.assertNotIn("position_scores", hidden["players"][0])

        self.state["participation"]["score_visible"] = True
        visible = engine.public_state(
            self.state,
            {"role": "participant", "authenticated": True, "user_id": 1},
        )
        self.assertIn("score", visible["players"][0])
        self.assertIn("position_scores", visible["players"][0])

    def test_host_can_see_scores_before_public_score_visibility(self):
        visible = engine.public_state(
            self.state,
            {"role": "host", "authenticated": True, "user_id": 1},
        )
        self.assertFalse(visible["participation"]["score_visible"])
        self.assertIn("score", visible["players"][0])

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

    def test_teacher_score_edit_recalculates_registered_team(self):
        team = engine.register_tournament_team(
            self.state, "수정 팀", self.members, "1234"
        )
        top_id = self.members["TOP"]
        engine.update_player_score(self.state, top_id, 10)
        self.assertEqual(team["total_score"], 42)
        self.assertTrue(team["over_score_limit"])

    def test_partial_lineup_recommends_closest_complete_team(self):
        extra_members = {}
        for position, score in (("JUG", 6), ("ADC", 8), ("SUP", 7)):
            player = engine.add_player(
                self.state,
                f"추천{position}",
                "",
                "GOLD",
                position,
                score=score,
            )
            extra_members[position] = player["id"]
        recommendations = engine.recommend_team_combinations(
            self.state,
            {
                "TOP": self.members["TOP"],
                "JUG": None,
                "MID": self.members["MID"],
                "ADC": None,
                "SUP": None,
            },
            target_score=40,
        )
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0]["score_difference"], 0)
        self.assertTrue(recommendations[0]["lineup"]["TOP"]["is_locked"])

    def test_recommendations_only_include_scores_within_five_below_target(self):
        state = engine.new_state()
        for position, score in zip(engine.POSITIONS, (31, 31, 31, 31, 31)):
            engine.add_player(state, position, "", "GOLD", position, score=score)
        for position, score in zip(engine.POSITIONS, (30, 30, 30, 30, 29)):
            engine.add_player(state, f"low-{position}", "", "GOLD", position, score=score)
        engine.add_player(state, "over-TOP", "", "GOLD", "TOP", score=32)

        recommendations = engine.recommend_team_combinations(
            state,
            {position: None for position in engine.POSITIONS},
            target_score=155,
            minimum_score=150,
        )

        self.assertTrue(recommendations)
        self.assertTrue(
            all(150 <= result["total_score"] <= 155 for result in recommendations)
        )

    def test_recommendations_can_use_secondary_position(self):
        secondary_only = engine.add_player(
            self.state,
            "미드가 부포지션",
            "",
            "GOLD",
            "TOP",
            secondary_position="MID",
            score=10,
            secondary_score=4,
        )
        recommendations = engine.recommend_team_combinations(
            self.state,
            {"TOP": None, "JUG": None, "MID": None, "ADC": None, "SUP": None},
            target_score=40,
        )
        self.assertTrue(recommendations)
        locked_secondary = engine.recommend_team_combinations(
            self.state,
            {
                "TOP": None,
                "JUG": None,
                "MID": secondary_only["id"],
                "ADC": None,
                "SUP": None,
            },
            target_score=40,
        )
        self.assertTrue(locked_secondary)
        self.assertTrue(locked_secondary[0]["lineup"]["MID"]["is_off_position"])
        self.assertEqual(locked_secondary[0]["lineup"]["MID"]["score"], 4)

    def test_recommendations_can_lock_extra_positions_for_every_position(self):
        for target in engine.POSITIONS:
            with self.subTest(target=target):
                state, members = self.make_complete_state()
                primary = next(position for position in engine.POSITIONS if position != target)
                secondary = next(
                    position
                    for position in engine.POSITIONS
                    if position not in (target, primary)
                )
                extra_player = engine.add_player(
                    state,
                    f"extra-locked-{target}",
                    "",
                    "GOLD",
                    primary,
                    secondary_position=secondary,
                    extra_positions=[target],
                    score=12,
                    secondary_score=3,
                )
                locked = dict(members)
                locked[target] = extra_player["id"]

                recommendations = engine.recommend_team_combinations(
                    state, locked, target_score=40
                )

                self.assertTrue(recommendations)
                self.assertEqual(
                    recommendations[0]["lineup"][target]["id"],
                    extra_player["id"],
                )
                self.assertEqual(recommendations[0]["lineup"][target]["score"], 3)

    def test_recommendations_can_fill_extra_positions_for_every_position(self):
        for target in engine.POSITIONS:
            with self.subTest(target=target):
                state, members = self.make_complete_state()
                primary = next(position for position in engine.POSITIONS if position != target)
                secondary = next(
                    position
                    for position in engine.POSITIONS
                    if position not in (target, primary)
                )
                extra_player = engine.add_player(
                    state,
                    f"extra-auto-{target}",
                    "",
                    "GOLD",
                    primary,
                    secondary_position=secondary,
                    extra_positions=[target],
                    score=12,
                    secondary_score=3,
                )
                locked = {
                    position: player_id if position != target else None
                    for position, player_id in members.items()
                }

                recommendations = engine.recommend_team_combinations(
                    state,
                    locked,
                    target_score=40,
                    excluded_player_ids={members[target]},
                )

                self.assertTrue(recommendations)
                self.assertEqual(
                    recommendations[0]["lineup"][target]["id"],
                    extra_player["id"],
                )

    def test_team_registration_accepts_extra_positions_for_every_position(self):
        for target in engine.POSITIONS:
            with self.subTest(target=target):
                state, members = self.make_complete_state()
                primary = next(position for position in engine.POSITIONS if position != target)
                secondary = next(
                    position
                    for position in engine.POSITIONS
                    if position not in (target, primary)
                )
                extra_player = engine.add_player(
                    state,
                    f"extra-register-{target}",
                    "",
                    "GOLD",
                    primary,
                    secondary_position=secondary,
                    extra_positions=[target],
                    score=12,
                    secondary_score=3,
                )
                members[target] = extra_player["id"]

                team = engine.register_tournament_team(
                    state, f"extra-team-{target}", members, "1234"
                )

                self.assertEqual(team["members"][target], extra_player["id"])

    def test_simulator_accepts_player_with_adc_and_sup_secondary_positions(self):
        state, members = self.make_complete_state()
        haram = engine.add_player(
            state,
            "김하람",
            "",
            "GOLD",
            "MID",
            secondary_position="ADC",
            extra_positions=["SUP"],
            score=10,
            secondary_score=6,
        )

        adc_locked = dict(members)
        adc_locked["ADC"] = haram["id"]
        adc_recommendations = engine.recommend_team_combinations(
            state, adc_locked, target_score=40
        )

        sup_locked = dict(members)
        sup_locked["SUP"] = haram["id"]
        sup_recommendations = engine.recommend_team_combinations(
            state, sup_locked, target_score=40
        )

        self.assertEqual(adc_recommendations[0]["lineup"]["ADC"]["id"], haram["id"])
        self.assertEqual(sup_recommendations[0]["lineup"]["SUP"]["id"], haram["id"])
        self.assertEqual(adc_recommendations[0]["lineup"]["ADC"]["score"], 6)
        self.assertEqual(sup_recommendations[0]["lineup"]["SUP"]["score"], 6)

    def test_team_total_uses_secondary_position_score(self):
        secondary_mid = engine.add_player(
            self.state,
            "부포지션 미드",
            "",
            "GOLD",
            "TOP",
            secondary_position="MID",
            score=12,
            secondary_score=3,
        )
        members = dict(self.members)
        members["MID"] = secondary_mid["id"]
        team = engine.register_tournament_team(
            self.state, "부포지션 점수팀", members, "1234"
        )
        self.assertEqual(team["total_score"], 33)

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

    def test_group_draw_qualifiers_then_knockout(self):
        team_ids = []
        for team_index in range(4):
            members = {}
            for position in engine.POSITIONS:
                player = engine.add_player(
                    self.state,
                    f"{team_index}-{position}",
                    "",
                    "GOLD",
                    position,
                    score=1,
                )
                members[position] = player["id"]
            team = engine.register_tournament_team(
                self.state, f"{team_index}팀", members, f"123{team_index}"
            )
            engine.approve_tournament_team(self.state, team["id"], True)
            team_ids.append(team["id"])
        tournament = self.state["tournament"]
        tournament["format"] = "group_then_knockout"
        tournament["group_count"] = 2
        tournament["qualifiers_per_group"] = 1

        engine.start_tournament(self.state)

        self.assertEqual(tournament["status"], "group")
        self.assertEqual(len(tournament["groups"]), 2)
        for index, group in enumerate(tournament["groups"]):
            engine.set_group_qualifiers(
                self.state, index, [group["team_ids"][0]]
            )
        engine.start_group_knockout(self.state)
        self.assertEqual(tournament["status"], "running")
        self.assertEqual(len(tournament["rounds"][0]), 1)

    def test_custom_bracket_routes_winner_and_loser(self):
        first = engine.register_tournament_team(
            self.state, "A팀", self.members, "1234"
        )
        engine.approve_tournament_team(self.state, first["id"], True)
        other_members = {}
        for position in engine.POSITIONS:
            player = engine.add_player(
                self.state, f"B-{position}", "", "GOLD", position, score=1
            )
            other_members[position] = player["id"]
        second = engine.register_tournament_team(
            self.state, "B팀", other_members, "5678"
        )
        engine.approve_tournament_team(self.state, second["id"], True)
        engine.set_custom_bracket(
            self.state,
            [
                {
                    "label": "승자조",
                    "matches": [{
                        "team1_id": first["id"],
                        "team2_id": second["id"],
                        "winner_to": {"round_index": 1, "match_index": 0, "slot": "team1_id"},
                        "loser_to": {"round_index": 1, "match_index": 0, "slot": "team2_id"},
                    }],
                },
                {
                    "label": "최종전",
                    "matches": [{
                        "team1_id": None,
                        "team2_id": None,
                        "winner_to": None,
                        "loser_to": None,
                    }],
                },
            ],
        )
        engine.select_match_winner(self.state, 0, 0, first["id"])
        final = self.state["tournament"]["rounds"][1][0]
        self.assertEqual(final["team1_id"], first["id"])
        self.assertEqual(final["team2_id"], second["id"])


if __name__ == "__main__":
    unittest.main()
