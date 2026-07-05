import tempfile
import unittest

from duckdb_pipeline import report_data as rd
from duckdb_pipeline.db import connect, init_db, insert_rows


def _base_play(play_id: int, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "run_id": "plays-report",
        "season": "2025-26",
        "game_id": "g-report",
        "home_team": "TeamA",
        "away_team": "TeamB",
        "schedule_home": "TeamA",
        "schedule_away": "TeamB",
        "play_id": play_id,
        "quarter": 1,
        "down": None,
        "distance": None,
        "offense": "TeamA",
        "defense": "TeamB",
        "play_type": "rush",
        "passer": None,
        "yards_gained": 0,
        "is_dropback": False,
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
        "fg_result": None,
        "raw_text": "placeholder",
    }
    row.update(overrides)
    return row


class ReportViewsTests(unittest.TestCase):
    def _seed_pipeline_run(self, conn) -> None:
        insert_rows(
            conn,
            "pipeline_runs",
            [
                {
                    "run_id": "plays-report",
                    "season": "2025-26",
                    "started_at": "2026-01-01 00:00:00",
                    "finished_at": "2026-01-01 00:01:00",
                    "status": "completed",
                    "stage": "plays",
                },
            ],
        )

    def test_is_early_down_and_is_passing_down_truth_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            self._seed_pipeline_run(conn)
            insert_rows(
                conn,
                "plays",
                [
                    # 1st & 10 -> early down, not passing down
                    _base_play(1, down=1, distance=10),
                    # 2nd & 5 -> early down (distance < 8), not passing down
                    _base_play(2, down=2, distance=5),
                    # 2nd & 8 -> passing down, not early down
                    _base_play(3, down=2, distance=8),
                    # 3rd & 3 -> neither (down not in 1/2, distance < 5)
                    _base_play(4, down=3, distance=3),
                    # 3rd & 8 -> passing down AND third down at once
                    # (the known, intentional overlap -- not mutually
                    # exclusive categories).
                    _base_play(5, down=3, distance=8),
                    # 4th & 2 -> neither
                    _base_play(6, down=4, distance=2),
                ],
            )

            rows = conn.execute(
                """
                SELECT play_id, down, distance, is_early_down, is_passing_down
                FROM v_play_context_current
                WHERE season = '2025-26' AND game_id = 'g-report'
                ORDER BY play_id
                """
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    (1, 1, 10, True, False),
                    (2, 2, 5, True, False),
                    (3, 2, 8, False, True),
                    (4, 3, 3, False, False),
                    (5, 3, 8, False, True),
                    (6, 4, 2, False, False),
                ],
            )

            # Play 5 (3rd & 8) must land in BOTH the 'passing_down' and
            # 'third_down' situation buckets -- these are independent
            # lenses on the same play, not a partition.
            situations = conn.execute(
                """
                SELECT DISTINCT situation
                FROM v_team_game_situation_offense_current
                WHERE season = '2025-26' AND game_id = 'g-report'
                  AND team_name = 'TeamA'
                ORDER BY situation
                """
            ).fetchall()
            self.assertIn(("passing_down",), situations)
            self.assertIn(("third_down",), situations)

            conn.close()

    def test_situation_rollup_row_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            self._seed_pipeline_run(conn)
            insert_rows(
                conn,
                "plays",
                [
                    _base_play(1, down=1, distance=10, yards_gained=6),
                    _base_play(2, down=2, distance=5, yards_gained=2),
                    _base_play(3, down=3, distance=8, yards_gained=9),
                ],
            )

            # Two early-down plays (1st&10, 2nd&5); one third/passing-down play.
            early_down_row = conn.execute(
                """
                SELECT play_count
                FROM v_team_season_situation_offense_current
                WHERE season = '2025-26' AND team_name = 'TeamA' AND situation = 'early_down'
                """
            ).fetchone()
            self.assertEqual(early_down_row, (2,))

            third_down_row = conn.execute(
                """
                SELECT play_count
                FROM v_team_season_situation_offense_current
                WHERE season = '2025-26' AND team_name = 'TeamA' AND situation = 'third_down'
                """
            ).fetchone()
            self.assertEqual(third_down_row, (1,))

            conn.close()

    def test_rank_direction_sanity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            self._seed_pipeline_run(conn)
            insert_rows(
                conn,
                "plays",
                [
                    # TeamA rushes for far more yards than TeamB -- TeamA
                    # should rank 1st offensively; TeamB's defense (which
                    # allowed the big total) should rank last defensively.
                    _base_play(1, offense="TeamA", defense="TeamB", down=1, distance=10, yards_gained=80),
                    _base_play(2, offense="TeamB", defense="TeamA", down=1, distance=10, yards_gained=5),
                ],
            )

            off_ranks = dict(
                conn.execute(
                    """
                    SELECT team_name, rush_yds_rank
                    FROM v_team_season_offense_ranked_current
                    WHERE season = '2025-26'
                    """
                ).fetchall()
            )
            self.assertEqual(off_ranks["TeamA"], 1)
            self.assertEqual(off_ranks["TeamB"], 2)

            def_ranks = dict(
                conn.execute(
                    """
                    SELECT team_name, opp_rush_yds_rank
                    FROM v_team_season_defense_ranked_current
                    WHERE season = '2025-26'
                    """
                ).fetchall()
            )
            # TeamB's defense allowed 80 yards (TeamA's output) -- worst in
            # the 2-team pool, so it should rank last (2nd), not 1st.
            self.assertEqual(def_ranks["TeamB"], 2)
            self.assertEqual(def_ranks["TeamA"], 1)

            conn.close()

    def test_passer_rating_team_and_player_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            self._seed_pipeline_run(conn)
            insert_rows(
                conn,
                "plays",
                [
                    # TeamA: two passers sharing snaps.
                    _base_play(
                        1, play_type="pass", passer="QB1", is_pass_attempt=True,
                        completion=True, yards_gained=20,
                    ),
                    _base_play(
                        2, play_type="pass", passer="QB1", is_pass_attempt=True,
                        completion=True, yards_gained=10,
                    ),
                    _base_play(
                        3, play_type="pass", passer="QB1", is_pass_attempt=True,
                        completion=False, yards_gained=0,
                    ),
                    _base_play(
                        4, play_type="pass", passer="QB2", is_pass_attempt=True,
                        completion=True, yards_gained=5, is_td=True,
                    ),
                    # TeamB: one ineffective passer, so TeamA should clearly
                    # out-rank TeamB on passer_rating.
                    _base_play(
                        5, offense="TeamB", defense="TeamA", play_type="pass",
                        passer="QB3", is_pass_attempt=True, completion=False, yards_gained=0,
                    ),
                ],
            )

            # Team level: pass_att=4, comp=3, yds=35, td=1, int=0
            # rating = (8.4*35 + 330*1 + 100*3 - 0) / 4 = 924 / 4 = 231.0
            team_row = conn.execute(
                """
                SELECT pass_att, pass_comp, pass_yds, pass_td, pass_int, passer_rating
                FROM v_team_game_offense_current
                WHERE season = '2025-26' AND game_id = 'g-report' AND team_name = 'TeamA'
                """
            ).fetchone()
            self.assertEqual(team_row, (4, 3, 35, 1, 0, 231.0))

            # Season-ranked view: TeamA's 231.0 clearly beats TeamB's 0.0.
            ranks = dict(
                conn.execute(
                    """
                    SELECT team_name, passer_rating_rank
                    FROM v_team_season_offense_ranked_current
                    WHERE season = '2025-26'
                    """
                ).fetchall()
            )
            self.assertEqual(ranks["TeamA"], 1)
            self.assertEqual(ranks["TeamB"], 2)

            # Player level: QB1 (3 att, 2 comp, 30 yds, 0 td) and QB2 (1 att,
            # 1 comp, 5 yds, 1 td) split out correctly, keyed on raw name.
            player_rows = dict(
                conn.execute(
                    """
                    SELECT passer, passer_rating
                    FROM v_player_season_passing_current
                    WHERE season = '2025-26' AND team_name = 'TeamA'
                    """
                ).fetchall()
            )
            # QB1: (8.4*30 + 0 + 100*2 - 0) / 3 = 452 / 3 = 150.67 -> 150.7
            self.assertEqual(player_rows["QB1"], 150.7)
            # QB2: (8.4*5 + 330*1 + 100*1 - 0) / 1 = 472.0
            self.assertEqual(player_rows["QB2"], 472.0)

            conn.close()

    def test_load_quick_hitters_ppg_and_success_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            self._seed_pipeline_run(conn)
            insert_rows(
                conn,
                "plays",
                [
                    # TeamA offense: 1 successful rush, 1 scoring rush (TD),
                    # 1 successful/explosive completed pass.
                    _base_play(1, down=1, distance=10, yards_gained=6),
                    _base_play(2, down=1, distance=10, yards_gained=0, is_td=True),
                    _base_play(
                        3, play_type="pass", is_pass_attempt=True, is_rush_attempt=False,
                        completion=True, down=1, distance=10, yards_gained=20,
                    ),
                    # TeamB offense (same game): one unsuccessful rush, no score.
                    _base_play(4, offense="TeamB", defense="TeamA", down=1, distance=10, yards_gained=1),
                ],
            )

            quick_hitters = rd.load_quick_hitters(conn, "2025-26", "TeamA")
            offense_by_label = {row["label"]: row for row in quick_hitters["offense"]}
            # TeamA scored 6 (the TD), TeamB scored 0 -- TeamA's offense
            # should lead the 2-team pool on PPG.
            self.assertEqual(offense_by_label["PPG"]["value"], 6.0)
            self.assertEqual(offense_by_label["PPG"]["rank"], 1)
            # 2 of TeamA's 3 scrimmage plays were successful (the two rushes:
            # first counts, TD rush doesn't meet the 1st-down threshold; the
            # pass does) -- exact value isn't the point here, just that the
            # combined (not pass-only/rush-only) success_rate flows through.
            self.assertIn("Success Rate", offense_by_label)
            self.assertIsNotNone(offense_by_label["Success Rate"]["value"])
            # No third-down plays exist in this fixture -- must degrade to
            # None gracefully, not raise.
            self.assertIsNone(offense_by_label["3rd Down Conversion"]["value"])

            defense_by_label = {row["label"]: row for row in quick_hitters["defense"]}
            self.assertEqual(defense_by_label["PPG"]["value"], 0.0)

            conn.close()

    def test_load_identity_rush_pass_split_and_conference_average(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            self._seed_pipeline_run(conn)
            insert_rows(
                conn,
                "plays",
                [
                    # TeamA offense: 3 rushes, 1 pass (75% run / 25% pass).
                    _base_play(1, down=1, distance=10, yards_gained=4),
                    _base_play(2, down=2, distance=6, yards_gained=3),
                    _base_play(3, down=1, distance=10, yards_gained=5),
                    _base_play(
                        4, play_type="pass", is_dropback=True, is_pass_attempt=True, is_rush_attempt=False,
                        completion=True, down=1, distance=10, yards_gained=12,
                    ),
                    # TeamB offense (same game): 1 rush only, feeds the
                    # conference-average denominator alongside TeamA.
                    _base_play(5, offense="TeamB", defense="TeamA", down=1, distance=10, yards_gained=8),
                ],
            )

            identity = rd.load_identity(conn, "2025-26", "TeamA")
            offense = identity["offense"]
            self.assertEqual(offense["rush_pct"], 75.0)
            self.assertEqual(offense["pass_pct"], 25.0)
            # TeamA's own rush_ypa: (4+3+5)/3 = 4.0
            self.assertEqual(offense["rush_ypa"], 4.0)
            # Conference average rush_ypa across TeamA (4.0) and TeamB (8.0) = 6.0
            self.assertEqual(offense["conference_avg_rush_ypa"], 6.0)
            # Structure sanity: rushing/passing/field_position/tempo lists
            # exist and situation_run_rate degrades gracefully with no
            # early/third-down plays in this fixture.
            self.assertTrue(len(offense["rushing"]) > 0)
            self.assertTrue(len(offense["passing"]) > 0)
            self.assertIsNone(offense["situation_run_rate"]["third_down_success_rate"])

            conn.close()

    def test_load_team_leaders_orders_and_caps_per_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "lineup-report",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "stage": "lineup_stats",
                    },
                ],
            )

            def player(full_name: str, position_group: str, **overrides: object) -> dict[str, object]:
                row: dict[str, object] = {
                    "run_id": "lineup-report",
                    "season": "2025-26",
                    "player_id": full_name,
                    "page_name": full_name,
                    "full_name": full_name,
                    "first_name": full_name,
                    "last_name": full_name,
                    "team": "TeamA",
                    "team_id": "t1",
                    "position": position_group.upper(),
                    "position_group": position_group,
                    "uniform": "1",
                    "year": "So.",
                    "active": True,
                    "games_played": 10.0,
                    "pass_att": None, "pass_comp": None, "pass_pct": None, "pass_yds": None,
                    "pass_ypg": None, "pass_ypa": None, "pass_td": None, "pass_int": None,
                    "pass_lg": None, "pass_rating": None,
                    "rush_att": None, "rush_yds": None, "rush_ypg": None, "rush_ypc": None,
                    "rush_td": None, "rush_lg": None, "fumbles": None, "fumbles_lost": None,
                    "rec": None, "rec_ypg": None, "rec_yds": None, "rec_ypc": None,
                    "rec_td": None, "rec_lg": None,
                    "tackles_solo": None, "tackles_ast": None, "tackles_total": None, "tackles_pg": None,
                    "sacks": None, "sack_yds": None, "tfl": None, "tfl_yds": None,
                    "forced_fumbles": None, "fumble_rec": None, "fumble_rec_yds": None,
                    "interceptions": None, "int_yds": None, "pass_breakups": None, "blocked_kicks": None,
                }
                row.update(overrides)
                return row

            insert_rows(
                conn,
                "player_lineup_stats",
                [
                    # 3 QBs -- only the top 2 by pass_yds should come back.
                    player("QB Best", "qb", pass_yds=2000.0),
                    player("QB Middle", "qb", pass_yds=1000.0),
                    player("QB Worst", "qb", pass_yds=100.0),
                    # 4 WRs -- only the top 3 by rec_yds should come back.
                    player("WR One", "wr", rec_yds=900.0),
                    player("WR Two", "wr", rec_yds=800.0),
                    player("WR Three", "wr", rec_yds=700.0),
                    player("WR Four", "wr", rec_yds=100.0),
                    # Defensive players: top 2 by tackles_total AND top 2 by
                    # sacks are independent selections from the same pool.
                    player("D High Tackles", "d", tackles_total=90.0, sacks=1.0),
                    player("D Mid Tackles", "d", tackles_total=50.0, sacks=2.0),
                    player("D High Sacks", "d", tackles_total=10.0, sacks=8.0),
                ],
            )

            leaders = rd.load_team_leaders(conn, "2025-26", "TeamA")
            self.assertEqual([p["full_name"] for p in leaders["passing"]], ["QB Best", "QB Middle"])
            self.assertEqual(
                [p["full_name"] for p in leaders["receiving"]], ["WR One", "WR Two", "WR Three"],
            )
            self.assertEqual(
                [p["full_name"] for p in leaders["tackles"]], ["D High Tackles", "D Mid Tackles"],
            )
            self.assertEqual([p["full_name"] for p in leaders["sacks"]], ["D High Sacks", "D Mid Tackles"])
            self.assertEqual(leaders["rushing"], [])

            conn.close()


if __name__ == "__main__":
    unittest.main()
