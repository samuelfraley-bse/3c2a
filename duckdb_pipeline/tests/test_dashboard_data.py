import importlib.util
import tempfile
import unittest

from duckdb_pipeline.dashboard_data import (
    OFFENSE_METRIC_DIRECTION,
    load_team_stats,
    metric_direction_for_side,
)
from duckdb_pipeline.db import connect, init_db, insert_rows


class MetricDirectionTests(unittest.TestCase):
    def test_offense_matches_canonical_map_unchanged(self) -> None:
        self.assertEqual(metric_direction_for_side("offense"), OFFENSE_METRIC_DIRECTION)

    def test_defense_inverts_non_neutral_entries(self) -> None:
        defense = metric_direction_for_side("defense")
        # pass_yds is higher-is-better on offense (yards gained) but
        # lower-is-better on defense (yards allowed).
        self.assertTrue(OFFENSE_METRIC_DIRECTION["pass_yds"])
        self.assertFalse(defense["pass_yds"])
        # pass_int is a turnover: bad for the offense that throws it, good
        # for the defense that forces it.
        self.assertFalse(OFFENSE_METRIC_DIRECTION["pass_int"])
        self.assertTrue(defense["pass_int"])

    def test_defense_keeps_neutral_entries_neutral(self) -> None:
        defense = metric_direction_for_side("defense")
        for key in ("games", "pass_att", "dropbacks", "rush_att"):
            self.assertIsNone(OFFENSE_METRIC_DIRECTION[key])
            self.assertIsNone(defense[key])

    def test_invalid_side_raises(self) -> None:
        with self.assertRaises(ValueError):
            metric_direction_for_side("special_teams")


@unittest.skipUnless(importlib.util.find_spec("duckdb"), "duckdb not installed")
class DashboardDataTests(unittest.TestCase):
    """Formula-drift guard: with no situational filters applied, dashboard_data's
    re-expressed formulas must produce the exact same numbers as the canonical
    views in db.py (v_team_season_offense_ranked_current / v_team_game_offense_current
    and their _defense_ mirrors). If these ever disagree, one of the two SQL
    implementations has drifted from METRICS.md's formulas.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = f"{self._tmpdir.name}/test.duckdb"
        self.conn = connect(db_path)
        init_db(self.conn)
        insert_rows(
            self.conn,
            "pipeline_runs",
            [
                {
                    "run_id": "plays-dash",
                    "season": "2025-26",
                    "started_at": "2026-01-01 00:00:00",
                    "finished_at": "2026-01-01 00:01:00",
                    "status": "completed",
                    "stage": "plays",
                },
            ],
        )

        def base_play(game_id: str, play_id: int, offense: str, defense: str, **overrides: object) -> dict[str, object]:
            row: dict[str, object] = {
                "run_id": "plays-dash",
                "season": "2025-26",
                "game_id": game_id,
                "home_team": offense,
                "away_team": defense,
                "schedule_home": offense,
                "schedule_away": defense,
                "play_id": play_id,
                "drive_id": 1,
                "quarter": 1,
                "down": 1,
                "distance": 10,
                "offense": offense,
                "defense": defense,
                "play_type": "rush",
                "yards_gained": 0,
                "is_pass_attempt": False,
                "is_rush_attempt": True,
                "completion": False,
                "is_interception": False,
                "is_td": False,
                "is_conversion": False,
                "is_sack": False,
                "is_fumble": False,
                "fumble_recovered_by": None,
                "is_safety": False,
                "is_defensive_td": False,
                "is_penalty": False,
                "fg_result": None,
                "raw_text": "placeholder",
            }
            row.update(overrides)
            return row

        insert_rows(
            self.conn,
            "plays",
            [
                # g1: Team A offense vs Team B defense -- 2 games total for Team A.
                base_play("g1", 1, "Team A", "Team B", yards_gained=15),  # explosive + success rush
                base_play(
                    "g1", 2, "Team A", "Team B",
                    play_type="pass", is_pass_attempt=True, is_rush_attempt=False,
                    completion=True, yards_gained=25,
                ),
                base_play("g1", 3, "Team A", "Team B", down=2, distance=5, yards_gained=-3),  # stuffed
                base_play("g1", 4, "Team A", "Team B", quarter=2, yards_gained=0, is_td=True),  # quarter 2, scores
                # g2: Team A offense vs Team C defense.
                base_play("g2", 1, "Team A", "Team C", yards_gained=4),
                base_play(
                    "g2", 2, "Team A", "Team C",
                    play_type="pass", is_pass_attempt=True, is_rush_attempt=False,
                    completion=False, yards_gained=0,
                ),
            ],
        )

    def tearDown(self) -> None:
        self.conn.close()
        self._tmpdir.cleanup()

    def test_season_passing_matches_ranked_view_with_no_extra_filters(self) -> None:
        dashboard_rows = load_team_stats(
            self.conn, side="offense", grain="season", family="passing", season="2025-26",
        )
        dashboard_row = next(r for r in dashboard_rows if r["team_name"] == "Team A")

        canonical = dict(
            zip(
                ["pass_att", "pass_comp", "comp_pct", "pass_yds", "pass_ypa", "pass_td", "passer_rating"],
                self.conn.execute(
                    """
                    SELECT pass_att, pass_comp, comp_pct, pass_yds, pass_ypa, pass_td, passer_rating
                    FROM v_team_season_offense_ranked_current
                    WHERE season = '2025-26' AND team_name = 'Team A'
                    """
                ).fetchone(),
            )
        )
        for key, value in canonical.items():
            self.assertEqual(dashboard_row[key], value, f"mismatch on {key}")
        self.assertEqual(dashboard_row["games"], 2)

    def test_game_passing_matches_game_view_with_no_extra_filters(self) -> None:
        dashboard_rows = load_team_stats(
            self.conn, side="offense", grain="game", family="passing", season="2025-26",
        )
        dashboard_row = next(r for r in dashboard_rows if r["team_name"] == "Team A" and r["game_id"] == "g1")

        canonical = dict(
            zip(
                ["pass_att", "pass_comp", "pass_yds", "pass_td", "dropbacks", "sacks"],
                self.conn.execute(
                    """
                    SELECT pass_att, pass_comp, pass_yds, pass_td, dropbacks, sacks
                    FROM v_team_game_offense_current
                    WHERE season = '2025-26' AND team_name = 'Team A' AND game_id = 'g1'
                    """
                ).fetchone(),
            )
        )
        for key, value in canonical.items():
            self.assertEqual(dashboard_row[key], value, f"mismatch on {key}")

    def test_game_grain_includes_opponent(self) -> None:
        rows = load_team_stats(self.conn, side="offense", grain="game", family="passing", season="2025-26")
        by_game = {r["game_id"]: r["opponent"] for r in rows if r["team_name"] == "Team A"}
        self.assertEqual(by_game, {"g1": "Team B", "g2": "Team C"})

        defense_rows = load_team_stats(self.conn, side="defense", grain="game", family="passing", season="2025-26")
        team_b_row = next(r for r in defense_rows if r["team_name"] == "Team B")
        self.assertEqual(team_b_row["opponent"], "Team A")

    def test_season_grain_has_no_opponent_column(self) -> None:
        rows = load_team_stats(self.conn, side="offense", grain="season", family="passing", season="2025-26")
        self.assertNotIn("opponent", rows[0])

    def test_season_rushing_matches_ranked_view_with_no_extra_filters(self) -> None:
        dashboard_rows = load_team_stats(
            self.conn, side="offense", grain="season", family="rushing", season="2025-26",
        )
        dashboard_row = next(r for r in dashboard_rows if r["team_name"] == "Team A")

        canonical = dict(
            zip(
                ["rush_att", "rush_yds", "rush_ypa", "rush_td", "rush_success_rate", "run_stuff_rate"],
                self.conn.execute(
                    """
                    SELECT rush_att, rush_yds, rush_ypa, rush_td, rush_success_rate, run_stuff_rate
                    FROM v_team_season_offense_ranked_current
                    WHERE season = '2025-26' AND team_name = 'Team A'
                    """
                ).fetchone(),
            )
        )
        for key, value in canonical.items():
            self.assertEqual(dashboard_row[key], value, f"mismatch on {key}")

    def test_defense_side_matches_defense_ranked_view(self) -> None:
        dashboard_rows = load_team_stats(
            self.conn, side="defense", grain="season", family="passing", season="2025-26",
        )
        dashboard_row = next(r for r in dashboard_rows if r["team_name"] == "Team B")

        canonical = dict(
            zip(
                ["pass_att", "pass_comp", "pass_yds", "pass_td"],
                self.conn.execute(
                    """
                    SELECT opp_pass_att, opp_pass_comp, opp_pass_yds, opp_pass_td
                    FROM v_team_season_defense_ranked_current
                    WHERE season = '2025-26' AND team_name = 'Team B'
                    """
                ).fetchone(),
            )
        )
        for key, value in canonical.items():
            self.assertEqual(dashboard_row[key], value, f"mismatch on {key}")

    def test_quarter_filter_narrows_plays_before_aggregation(self) -> None:
        all_rows = load_team_stats(
            self.conn, side="offense", grain="season", family="rushing", season="2025-26",
        )
        team_a_all = next(r for r in all_rows if r["team_name"] == "Team A")

        q1_rows = load_team_stats(
            self.conn, side="offense", grain="season", family="rushing", season="2025-26", quarter=1,
        )
        team_a_q1 = next(r for r in q1_rows if r["team_name"] == "Team A")

        # Play g1/4 (the scoring rush) is quarter=2; every other rush is quarter=1.
        self.assertEqual(team_a_all["rush_att"], team_a_q1["rush_att"] + 1)
        self.assertEqual(team_a_q1["rush_td"], 0)

    def test_quarter_filter_accepts_multi_select_list(self) -> None:
        rows = load_team_stats(
            self.conn, side="offense", grain="season", family="rushing", season="2025-26", quarter=[1, 2],
        )
        team_a = next(r for r in rows if r["team_name"] == "Team A")
        all_rows = load_team_stats(
            self.conn, side="offense", grain="season", family="rushing", season="2025-26",
        )
        team_a_all = next(r for r in all_rows if r["team_name"] == "Team A")
        self.assertEqual(team_a["rush_att"], team_a_all["rush_att"])


@unittest.skipUnless(importlib.util.find_spec("duckdb"), "duckdb not installed")
class FumbleRecoveryDefensiveTdTests(unittest.TestCase):
    """Same scenario as test_db.py's
    test_fumble_recovery_defensive_td_excluded_from_pass_td_and_sack_rate --
    dashboard_data.py re-expresses pass_td/sack_rate independently (it can't
    just query the pre-aggregated views, since filters apply before
    aggregation), so it needs its own regression coverage for the same
    is_defensive_td guard.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = f"{self._tmpdir.name}/test.duckdb"
        self.conn = connect(db_path)
        init_db(self.conn)
        insert_rows(
            self.conn,
            "pipeline_runs",
            [
                {
                    "run_id": "plays-fix",
                    "season": "2025-26",
                    "started_at": "2026-01-01 00:00:00",
                    "finished_at": "2026-01-01 00:01:00",
                    "status": "completed",
                    "stage": "plays",
                },
            ],
        )

        def base_play(play_id: int, **overrides: object) -> dict[str, object]:
            row: dict[str, object] = {
                "run_id": "plays-fix",
                "season": "2025-26",
                "game_id": "g-fix",
                "home_team": "Home",
                "away_team": "Away",
                "schedule_home": "Home",
                "schedule_away": "Away",
                "play_id": play_id,
                "quarter": 1,
                "down": 1,
                "distance": 10,
                "offense": "Away",
                "defense": "Home",
                "play_type": "pass",
                "yards_gained": 0,
                "is_dropback": True,
                "is_pass_attempt": True,
                "is_rush_attempt": False,
                "completion": False,
                "is_interception": False,
                "is_td": False,
                "is_conversion": False,
                "is_sack": False,
                "is_fumble": False,
                "fumble_recovered_by": None,
                "is_safety": False,
                "is_defensive_td": False,
                "is_penalty": False,
                "fg_result": None,
                "raw_text": "placeholder",
            }
            row.update(overrides)
            return row

        insert_rows(
            self.conn,
            "plays",
            [
                base_play(1, completion=True, yards_gained=20),
                base_play(2, is_pass_attempt=False, is_rush_attempt=True, is_sack=True, yards_gained=-7),
                base_play(
                    3,
                    yards_gained=-3,
                    is_fumble=True,
                    fumble_recovered_by="HOMEPRE John Smith",
                    is_td=True,
                    raw_text=(
                        "Away QB pass complete, fumble recovered by "
                        "HOMEPRE John Smith, return 30 yards, TOUCHDOWN, clock 05:00."
                    ),
                ),
            ],
        )
        insert_rows(
            self.conn,
            "field_position_crosswalk",
            [
                {
                    "season": "2025-26",
                    "source_plays_run_id": "plays-fix",
                    "game_id": "g-fix",
                    "prefix": "HOMEPRE",
                    "canonical_team": "Home",
                    "resolution_method": "manual",
                    "note": "test fixture",
                    "resolved_at": "2026-01-01 00:00:00",
                },
            ],
        )

    def tearDown(self) -> None:
        self.conn.close()
        self._tmpdir.cleanup()

    def test_offense_pass_td_excludes_defensive_td_and_computes_sack_rate(self) -> None:
        rows = load_team_stats(self.conn, side="offense", grain="season", family="passing", season="2025-26")
        away = next(r for r in rows if r["team_name"] == "Away")
        self.assertEqual(away["pass_att"], 2)
        self.assertEqual(away["pass_td"], 0)
        self.assertEqual(away["sacks"], 1)
        self.assertEqual(away["dropbacks"], 3)
        self.assertEqual(away["sack_rate"], 33.3)

    def test_defense_opp_pass_td_excludes_own_defensive_score(self) -> None:
        rows = load_team_stats(self.conn, side="defense", grain="season", family="passing", season="2025-26")
        home = next(r for r in rows if r["team_name"] == "Home")
        self.assertEqual(home["pass_td"], 0)


if __name__ == "__main__":
    unittest.main()
