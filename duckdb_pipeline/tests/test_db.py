import importlib.util
import tempfile
import unittest

from duckdb_pipeline.db import connect, init_db, insert_rows


@unittest.skipUnless(importlib.util.find_spec("duckdb"), "duckdb not installed")
class DbTests(unittest.TestCase):
    def test_init_db_and_insert(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "run-1",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "standings_count": 66,
                        "schedule_count": 650,
                        "games_count": 325,
                        "notes": None,
                    }
                ],
            )
            value = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
            self.assertEqual(value, 1)
            tables = {
                row[0]
                for row in conn.execute("SELECT table_name FROM information_schema.tables").fetchall()
            }
            self.assertIn("raw_pbp_html", tables)
            self.assertIn("plays", tables)
            self.assertIn("failed_game_fetches", tables)
            self.assertIn("field_position_prefixes", tables)
            self.assertIn("field_position_crosswalk", tables)
            self.assertIn("play_field_positions", tables)
            play_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info('plays')").fetchall()
            }
            self.assertIn("is_pass_attempt", play_columns)
            self.assertIn("is_rush_attempt", play_columns)
            conn.close()

    def test_pipeline_run_stage_backfilled_for_legacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "legacy-structure",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "standings_count": 66,
                        "schedule_count": 694,
                        "games_count": 347,
                        "notes": None,
                    },
                    {
                        "run_id": "legacy-plays",
                        "season": "2025-26",
                        "started_at": "2026-01-02 00:00:00",
                        "finished_at": "2026-01-02 00:01:00",
                        "status": "completed",
                        "standings_count": None,
                        "schedule_count": None,
                        "games_count": None,
                        "notes": '{"plays_count": 10, "raw_pbp_count": 5, "source_run_id": "legacy-structure"}',
                    },
                    {
                        "run_id": "legacy-fieldpos",
                        "season": "2025-26",
                        "started_at": "2026-01-03 00:00:00",
                        "finished_at": "2026-01-03 00:01:00",
                        "status": "completed",
                        "standings_count": None,
                        "schedule_count": None,
                        "games_count": None,
                        "notes": (
                            '{"field_position_rows": 5, "resolved_count": 5, '
                            '"source_plays_run_id": "legacy-plays", "unresolved_count": 0}'
                        ),
                    },
                ],
            )
            # None of these rows set `stage` explicitly (they predate the column).
            # Re-running init_db must backfill it from the same signals the
            # v_current_*_runs views used to sniff stage from before this column existed.
            init_db(conn)
            rows = dict(conn.execute("SELECT run_id, stage FROM pipeline_runs").fetchall())
            self.assertEqual(
                rows,
                {
                    "legacy-structure": "structure",
                    "legacy-plays": "plays",
                    "legacy-fieldpos": "field_position",
                },
            )
            conn.close()

    def test_current_run_views_and_current_offense_rollups(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "structure-old",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "standings_count": 66,
                        "schedule_count": 694,
                        "games_count": 347,
                        "notes": None,
                    },
                    {
                        "run_id": "structure-new",
                        "season": "2025-26",
                        "started_at": "2026-01-02 00:00:00",
                        "finished_at": "2026-01-02 00:01:00",
                        "status": "completed",
                        "standings_count": 66,
                        "schedule_count": 694,
                        "games_count": 347,
                        "notes": None,
                    },
                    {
                        "run_id": "plays-old",
                        "season": "2025-26",
                        "started_at": "2026-01-03 00:00:00",
                        "finished_at": "2026-01-03 00:01:00",
                        "status": "completed",
                        "standings_count": None,
                        "schedule_count": None,
                        "games_count": None,
                        "notes": '{"plays_count": 1, "raw_pbp_count": 1, "source_run_id": "structure-old"}',
                    },
                    {
                        "run_id": "plays-new",
                        "season": "2025-26",
                        "started_at": "2026-01-04 00:00:00",
                        "finished_at": "2026-01-04 00:01:00",
                        "status": "completed",
                        "standings_count": None,
                        "schedule_count": None,
                        "games_count": None,
                        "notes": (
                            '{"plays_count": 3, "raw_pbp_count": 1, '
                            '"source_run_id": "structure-new", '
                            '"reparsed_from_plays_run_id": "plays-old"}'
                        ),
                    },
                    {
                        "run_id": "fieldpos-new",
                        "season": "2025-26",
                        "started_at": "2026-01-05 00:00:00",
                        "finished_at": "2026-01-05 00:01:00",
                        "status": "completed",
                        "standings_count": None,
                        "schedule_count": None,
                        "games_count": None,
                        "notes": (
                            '{"field_position_rows": 3, '
                            '"resolved_count": 3, '
                            '"source_plays_run_id": "plays-new", '
                            '"unresolved_count": 0}'
                        ),
                    },
                ],
            )
            insert_rows(
                conn,
                "games",
                [
                    {
                        "run_id": "structure-old",
                        "season": "2025-26",
                        "game_id": "g-old",
                        "game_date": "20250901",
                        "pbp_url": "old",
                        "schedule_home": "Old Home",
                        "schedule_away": "Old Away",
                        "home_team_canonical": "Old Home",
                        "away_team_canonical": "Old Away",
                        "team_1": "Old Home",
                        "team_2": "Old Away",
                        "schedule_row_count": 2,
                        "unique_team_count": 2,
                        "pairing_status": "paired",
                    },
                    {
                        "run_id": "structure-new",
                        "season": "2025-26",
                        "game_id": "g-new",
                        "game_date": "20250902",
                        "pbp_url": "new",
                        "schedule_home": "Foothill",
                        "schedule_away": "Monterey Peninsula",
                        "home_team_canonical": "Foothill",
                        "away_team_canonical": "Monterey Peninsula",
                        "team_1": "Foothill",
                        "team_2": "Monterey Peninsula",
                        "schedule_row_count": 2,
                        "unique_team_count": 2,
                        "pairing_status": "paired",
                    },
                ],
            )
            insert_rows(
                conn,
                "schedule",
                [
                    {
                        "run_id": "structure-new",
                        "season": "2025-26",
                        "team_name": "Foothill",
                        "team_id": "t1",
                        "game_id": "g-new",
                        "game_date": "20250902",
                        "home_away": "home",
                        "opponent": "Monterey Peninsula",
                        "result": "W",
                        "pbp_url": "new",
                        "schedule_home": "Foothill",
                        "schedule_away": "Monterey Peninsula",
                    },
                    {
                        "run_id": "structure-new",
                        "season": "2025-26",
                        "team_name": "Monterey Peninsula",
                        "team_id": "t2",
                        "game_id": "g-new",
                        "game_date": "20250902",
                        "home_away": "away",
                        "opponent": "Foothill",
                        "result": "L",
                        "pbp_url": "new",
                        "schedule_home": "Foothill",
                        "schedule_away": "Monterey Peninsula",
                    },
                ],
            )
            insert_rows(
                conn,
                "standings",
                [
                    {
                        "run_id": "structure-old",
                        "season": "2025-26",
                        "conference": "Conference",
                        "team_name": "Old Home",
                        "team_id": "old-home",
                        "schedule_url": "old-home-url",
                        "conf_gp": "5",
                        "conf_w": "3",
                        "conf_l": "2",
                        "conf_t": "0",
                        "conf_pct": "0.600",
                        "overall_gp": "10",
                        "overall_w": "6",
                        "overall_l": "4",
                        "overall_t": "0",
                        "overall_pct": "0.600",
                    },
                    {
                        "run_id": "structure-new",
                        "season": "2025-26",
                        "conference": "Conference",
                        "team_name": "Foothill",
                        "team_id": "t1",
                        "schedule_url": "foothill-url",
                        "conf_gp": "6",
                        "conf_w": "4",
                        "conf_l": "2",
                        "conf_t": "0",
                        "conf_pct": "0.667",
                        "overall_gp": "11",
                        "overall_w": "7",
                        "overall_l": "4",
                        "overall_t": "0",
                        "overall_pct": "0.636",
                    },
                    {
                        "run_id": "structure-new",
                        "season": "2025-26",
                        "conference": "Conference",
                        "team_name": "Monterey Peninsula",
                        "team_id": "t2",
                        "schedule_url": "mpc-url",
                        "conf_gp": "6",
                        "conf_w": "2",
                        "conf_l": "4",
                        "conf_t": "0",
                        "conf_pct": "0.333",
                        "overall_gp": "11",
                        "overall_w": "3",
                        "overall_l": "8",
                        "overall_t": "0",
                        "overall_pct": "0.273",
                    },
                ],
            )
            insert_rows(
                conn,
                "plays",
                [
                    {
                        "run_id": "plays-old",
                        "season": "2025-26",
                        "game_id": "g-old",
                        "home_team": "Old Home",
                        "away_team": "Old Away",
                        "schedule_home": "Old Home",
                        "schedule_away": "Old Away",
                        "play_id": 1,
                        "drive_id": 1,
                        "drive_start_time": "15:00",
                        "quarter": 1,
                        "down": 1,
                        "distance": 10,
                        "field_position": "OLD25",
                        "yardline_raw": 25,
                        "offense": "Old Home",
                        "defense": "Old Away",
                        "play_type": "pass",
                        "passer": "Old QB",
                        "rusher": None,
                        "receiver": "Old WR",
                        "pass_result": "complete",
                        "yards_gained": 5,
                        "is_dropback": True,
                        "is_attempt": True,
                        "is_conversion": False,
                        "is_pass_attempt": True,
                        "is_rush_attempt": False,
                        "completion": True,
                        "is_interception": False,
                        "is_td": False,
                        "is_sack": False,
                        "is_fumble": False,
                        "fumble_recovered_by": None,
                        "is_penalty": False,
                        "penalty_team": None,
                        "penalty_type": None,
                        "penalty_player": None,
                        "penalty_yards": None,
                        "fg_result": None,
                        "tackler_1": None,
                        "tackler_2": None,
                        "raw_text": "old play",
                    },
                    {
                        "run_id": "plays-new",
                        "season": "2025-26",
                        "game_id": "g-new",
                        "home_team": "Foothill",
                        "away_team": "Monterey Peninsula",
                        "schedule_home": "Foothill",
                        "schedule_away": "Monterey Peninsula",
                        "play_id": 1,
                        "drive_id": 1,
                        "drive_start_time": "15:00",
                        "quarter": 1,
                        "down": 1,
                        "distance": 10,
                        "field_position": "FOOTHILL25",
                        "yardline_raw": 25,
                        "offense": "Foothill",
                        "defense": "Monterey Peninsula",
                        "play_type": "pass",
                        "passer": "Foothill QB",
                        "rusher": None,
                        "receiver": "Foothill WR",
                        "pass_result": "complete",
                        "yards_gained": 12,
                        "is_dropback": True,
                        "is_attempt": True,
                        "is_conversion": False,
                        "is_pass_attempt": True,
                        "is_rush_attempt": False,
                        "completion": True,
                        "is_interception": False,
                        "is_td": True,
                        "is_sack": False,
                        "is_fumble": False,
                        "fumble_recovered_by": None,
                        "is_penalty": False,
                        "penalty_team": None,
                        "penalty_type": None,
                        "penalty_player": None,
                        "penalty_yards": None,
                        "fg_result": None,
                        "tackler_1": None,
                        "tackler_2": None,
                        "raw_text": "new pass",
                    },
                    {
                        "run_id": "plays-new",
                        "season": "2025-26",
                        "game_id": "g-new",
                        "home_team": "Foothill",
                        "away_team": "Monterey Peninsula",
                        "schedule_home": "Foothill",
                        "schedule_away": "Monterey Peninsula",
                        "play_id": 2,
                        "drive_id": 1,
                        "drive_start_time": "14:22",
                        "quarter": 1,
                        "down": 2,
                        "distance": 8,
                        "field_position": "FOOTHILL37",
                        "yardline_raw": 37,
                        "offense": "Foothill",
                        "defense": "Monterey Peninsula",
                        "play_type": "rush",
                        "passer": None,
                        "rusher": "Foothill RB",
                        "receiver": None,
                        "pass_result": None,
                        "yards_gained": 7,
                        "is_dropback": False,
                        "is_attempt": True,
                        "is_conversion": False,
                        "is_pass_attempt": False,
                        "is_rush_attempt": True,
                        "completion": False,
                        "is_interception": False,
                        "is_td": False,
                        "is_sack": False,
                        "is_fumble": False,
                        "fumble_recovered_by": None,
                        "is_penalty": False,
                        "penalty_team": None,
                        "penalty_type": None,
                        "penalty_player": None,
                        "penalty_yards": None,
                        "fg_result": None,
                        "tackler_1": None,
                        "tackler_2": None,
                        "raw_text": "new rush",
                    },
                    {
                        "run_id": "plays-new",
                        "season": "2025-26",
                        "game_id": "g-new",
                        "home_team": "Foothill",
                        "away_team": "Monterey Peninsula",
                        "schedule_home": "Foothill",
                        "schedule_away": "Monterey Peninsula",
                        "play_id": 3,
                        "drive_id": 1,
                        "drive_start_time": "13:40",
                        "quarter": 1,
                        "down": 3,
                        "distance": 1,
                        "field_position": "FOOTHILL44",
                        "yardline_raw": 44,
                        "offense": "Foothill",
                        "defense": "Monterey Peninsula",
                        "play_type": "pass",
                        "passer": "Foothill QB",
                        "rusher": None,
                        "receiver": None,
                        "pass_result": None,
                        "yards_gained": -6,
                        "is_dropback": True,
                        "is_attempt": False,
                        "is_conversion": False,
                        "is_pass_attempt": False,
                        "is_rush_attempt": True,
                        "completion": False,
                        "is_interception": False,
                        "is_td": False,
                        "is_sack": True,
                        "is_fumble": False,
                        "fumble_recovered_by": None,
                        "is_penalty": False,
                        "penalty_team": None,
                        "penalty_type": None,
                        "penalty_player": None,
                        "penalty_yards": None,
                        "fg_result": None,
                        "tackler_1": None,
                        "tackler_2": None,
                        "raw_text": "new sack",
                    },
                ],
            )
            insert_rows(
                conn,
                "play_field_positions",
                [
                    {
                        "run_id": "fieldpos-new",
                        "season": "2025-26",
                        "source_plays_run_id": "plays-new",
                        "game_id": "g-new",
                        "play_id": 1,
                        "field_position": "FOOTHILL25",
                        "field_pos_prefix": "FOOTHILL",
                        "yardline_raw": 25,
                        "offense": "Foothill",
                        "prefix_owner": "Foothill",
                        "field_pos_side": "own",
                        "yardline_100": 25,
                        "resolution_status": "resolved",
                        "created_at": "2026-01-05 00:00:00",
                    },
                    {
                        "run_id": "fieldpos-new",
                        "season": "2025-26",
                        "source_plays_run_id": "plays-new",
                        "game_id": "g-new",
                        "play_id": 2,
                        "field_position": "FOOTHILL37",
                        "field_pos_prefix": "FOOTHILL",
                        "yardline_raw": 37,
                        "offense": "Foothill",
                        "prefix_owner": "Foothill",
                        "field_pos_side": "own",
                        "yardline_100": 37,
                        "resolution_status": "resolved",
                        "created_at": "2026-01-05 00:00:00",
                    },
                    {
                        "run_id": "fieldpos-new",
                        "season": "2025-26",
                        "source_plays_run_id": "plays-new",
                        "game_id": "g-new",
                        "play_id": 3,
                        "field_position": "FOOTHILL44",
                        "field_pos_prefix": "FOOTHILL",
                        "yardline_raw": 44,
                        "offense": "Foothill",
                        "prefix_owner": "Foothill",
                        "field_pos_side": "own",
                        "yardline_100": 44,
                        "resolution_status": "resolved",
                        "created_at": "2026-01-05 00:00:00",
                    },
                ],
            )
            init_db(conn)

            current_runs = conn.execute(
                """
                SELECT season, structure_run_id, plays_run_id, plays_source_structure_run_id, reparsed_from_plays_run_id
                FROM v_current_runs
                WHERE season = '2025-26'
                """
            ).fetchone()
            self.assertEqual(
                current_runs,
                ("2025-26", "structure-new", "plays-new", "structure-new", "plays-old"),
            )

            current_games = conn.execute(
                "SELECT game_id FROM v_games_current WHERE season = '2025-26'"
            ).fetchall()
            self.assertEqual(current_games, [("g-new",)])

            standings_row = conn.execute(
                """
                SELECT
                    season,
                    run_id,
                    conference,
                    team_name,
                    team_id,
                    schedule_url,
                    games,
                    wins,
                    losses,
                    ties,
                    win_pct,
                    conference_games,
                    conference_wins,
                    conference_losses,
                    conference_ties,
                    conference_win_pct
                FROM v_standings_current
                WHERE season = '2025-26' AND team_name = 'Foothill'
                """
            ).fetchone()
            self.assertEqual(
                standings_row,
                (
                    "2025-26",
                    "structure-new",
                    "Conference",
                    "Foothill",
                    "t1",
                    "foothill-url",
                    11,
                    7,
                    4,
                    0,
                    0.636,
                    6,
                    4,
                    2,
                    0,
                    0.667,
                ),
            )

            current_play_ids = conn.execute(
                "SELECT play_id FROM v_plays_current WHERE season = '2025-26' ORDER BY play_id"
            ).fetchall()
            self.assertEqual(current_play_ids, [(1,), (2,), (3,)])

            offense_row = conn.execute(
                """
                SELECT
                    team_name,
                    opponent,
                    home_away,
                    week,
                    pass_att,
                    pass_comp,
                    pass_yds,
                    pass_int,
                    pass_td,
                    pass_successes,
                    pass_comp_10_plus,
                    pass_comp_20_plus,
                    rush_att,
                    rush_yds,
                    rush_td,
                    rush_successes,
                    rush_10_plus,
                    rush_20_plus,
                    stuffed_runs,
                    sacks,
                    dropbacks,
                    play_count
                FROM v_team_game_offense_current
                WHERE season = '2025-26' AND game_id = 'g-new' AND team_name = 'Foothill'
                """
            ).fetchone()
            self.assertEqual(
                offense_row,
                (
                    "Foothill",
                    "Monterey Peninsula",
                    "home",
                    1,
                    1,
                    1,
                    12,
                    0,
                    1,
                    1,
                    1,
                    0,
                    2,
                    1,
                    0,
                    1,
                    0,
                    0,
                    1,
                    1,
                    2,
                    3,
                ),
            )

            play_context_row = conn.execute(
                """
                SELECT
                    week,
                    distance_bucket,
                    yardline_100,
                    field_zone,
                    is_success,
                    explosive_pass,
                    explosive_rush,
                    is_explosive,
                    is_stuffed
                FROM v_play_context_current
                WHERE season = '2025-26' AND game_id = 'g-new' AND play_id = 1
                """
            ).fetchone()
            self.assertEqual(
                play_context_row,
                (1, "long", 25, "opponent_territory", True, False, False, False, False),
            )

            score_state_rows = conn.execute(
                """
                SELECT play_id, home_score, away_score, score_margin, score_margin_bucket
                FROM v_play_context_current
                WHERE season = '2025-26' AND game_id = 'g-new'
                ORDER BY play_id
                """
            ).fetchall()
            self.assertEqual(
                score_state_rows,
                [
                    # Play 1 scores Foothill's TD, so its own pre-play state is
                    # still scoreless.
                    (1, 0, 0, 0, "tied"),
                    # Plays 2 and 3 come after that TD, so Foothill (home,
                    # offense on both) now leads 6-0 entering each of them.
                    (2, 6, 0, 6, "one_score_lead"),
                    (3, 6, 0, 6, "one_score_lead"),
                ],
            )

            defense_row = conn.execute(
                """
                SELECT
                    team_name,
                    opponent,
                    home_away,
                    opp_pass_att,
                    opp_pass_comp,
                    opp_pass_yds,
                    interceptions_forced,
                    opp_pass_td,
                    opp_dropbacks,
                    sacks_forced,
                    opp_rush_att,
                    opp_rush_yds,
                    opp_rush_td,
                    stuffed_runs_forced
                FROM v_team_game_defense_current
                WHERE season = '2025-26' AND game_id = 'g-new' AND team_name = 'Monterey Peninsula'
                """
            ).fetchone()
            self.assertEqual(
                defense_row,
                (
                    "Monterey Peninsula",
                    "Foothill",
                    "away",
                    1,
                    1,
                    12,
                    0,
                    1,
                    2,
                    1,
                    2,
                    1,
                    0,
                    1,
                ),
            )

            coverage_row = conn.execute(
                """
                SELECT team_name, scheduled_games, pbp_games, missing_pbp_games
                FROM v_pbp_coverage_by_team_current
                WHERE season = '2025-26' AND team_name = 'Foothill'
                """
            ).fetchone()
            self.assertEqual(coverage_row, ("Foothill", 1, 1, 0))
            conn.close()

    def test_score_margin_credits_safety_and_defensive_touchdowns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            # v_play_context_current only needs a completed `plays` stage run
            # for the season -- no games/schedule/standings fixtures required.
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "plays-score",
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
                    "run_id": "plays-score",
                    "season": "2025-26",
                    "game_id": "g-score",
                    "home_team": "Home",
                    "away_team": "Away",
                    "schedule_home": "Home",
                    "schedule_away": "Away",
                    "play_id": play_id,
                    "quarter": 1,
                    "play_type": "rush",
                    "yards_gained": 5,
                    "is_rush_attempt": True,
                    "is_td": False,
                    "is_conversion": False,
                    "is_interception": False,
                    "is_fumble": False,
                    "fumble_recovered_by": None,
                    "is_safety": False,
                    "is_defensive_td": False,
                    "fg_result": None,
                    "raw_text": "placeholder",
                }
                row.update(overrides)
                return row

            insert_rows(
                conn,
                "plays",
                [
                    # 1: ordinary non-scoring play, Home on offense.
                    base_play(1, offense="Home", defense="Away"),
                    # 2: safety -- Home is tackled in its own end zone, so
                    # Away (the defense on this play) scores 2.
                    base_play(
                        2,
                        offense="Home",
                        defense="Away",
                        yards_gained=-5,
                        is_safety=True,
                        raw_text="Home rush for loss of 5 yards to the HOME00, Home safety, clock 10:00.",
                    ),
                    # 3: pick-six -- Away throws, Home's defense returns it
                    # for a touchdown. Unambiguous at parse time.
                    base_play(
                        3,
                        offense="Away",
                        defense="Home",
                        play_type="pass",
                        yards_gained=0,
                        is_interception=True,
                        is_defensive_td=True,
                        raw_text=(
                            "Away QB pass intercepted by Home DB, "
                            "return 30 yards, TOUCHDOWN, clock 08:00."
                        ),
                    ),
                    # 4: fumble-recovery touchdown by Home's defense, but
                    # stored `is_td` is (incorrectly) True -- simulating the
                    # real RE_FUMBLE name-pollution bug, where the polluted
                    # `fumble_recovered_by` value fails simple team-name
                    # matching. The field-position crosswalk below should
                    # still resolve it correctly via a prefix match and
                    # suppress the offensive credit.
                    base_play(
                        4,
                        offense="Away",
                        defense="Home",
                        yards_gained=-2,
                        is_fumble=True,
                        fumble_recovered_by="HOMEPRE JOHN",
                        is_td=True,
                        raw_text=(
                            "Away RB rush for loss of 2 yards, fumble recovered by "
                            "HOMEPRE John Smith, return 20 yards, TOUCHDOWN, clock 05:00."
                        ),
                    ),
                    # 5: trailing non-scoring play. Its pre-play state proves
                    # play 4's fumble-return touchdown was NOT also credited
                    # to the offense (Away) despite the misleading is_td=True.
                    base_play(5, offense="Home", defense="Away"),
                ],
            )
            insert_rows(
                conn,
                "field_position_crosswalk",
                [
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-score",
                        "game_id": "g-score",
                        "prefix": "HOMEPRE",
                        "canonical_team": "Home",
                        "resolution_method": "manual",
                        "note": "test fixture",
                        "resolved_at": "2026-01-01 00:00:00",
                    },
                ],
            )

            rows = conn.execute(
                """
                SELECT play_id, is_safety, is_defensive_td, home_score, away_score,
                       score_margin, score_margin_bucket
                FROM v_play_context_current
                WHERE season = '2025-26' AND game_id = 'g-score'
                ORDER BY play_id
                """
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    # Pre-play state before anything has scored.
                    (1, False, False, 0, 0, 0, "tied"),
                    # Still 0-0 entering the safety itself.
                    (2, True, False, 0, 0, 0, "tied"),
                    # Entering the pick-six: Away's safety concession is now
                    # reflected (Away offense here, so margin = away - home).
                    (3, False, True, 0, 2, 2, "one_score_lead"),
                    # This row IS the fumble-return touchdown: is_defensive_td
                    # resolves True via the crosswalk despite the misleading
                    # stored is_td=True. Entering it, only the pick-six from
                    # play 3 has landed (Away offense, margin = away - home).
                    (4, False, True, 6, 2, -4, "one_score_deficit"),
                    # Entering the trailing play: Home's fumble-return TD is
                    # reflected as +6 to Home (not to Away), proving the
                    # crosswalk suppressed the misleading is_td=True on play 4.
                    (5, False, False, 12, 2, 10, "two_score_lead"),
                ],
            )
            conn.close()

    def test_points_and_explosive_success_stuff_rate_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "plays-pts",
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
                    "run_id": "plays-pts",
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
                conn,
                "plays",
                [
                    # g1: Team A offense vs Team B defense.
                    base_play("g1", 1, "Team A", "Team B", yards_gained=15),  # success + explosive rush
                    base_play(
                        "g1", 2, "Team A", "Team B",
                        play_type="pass", is_pass_attempt=True, is_rush_attempt=False,
                        completion=True, yards_gained=25,
                    ),  # success + explosive pass
                    base_play("g1", 3, "Team A", "Team B", down=2, distance=5, yards_gained=-3),  # stuffed, not success
                    base_play("g1", 4, "Team A", "Team B", yards_gained=0, is_td=True),  # TD, also stuffed (yards<=0)
                    # g2: Team C offense vs Team A defense.
                    base_play("g2", 1, "Team C", "Team A", yards_gained=20),  # success + explosive rush
                    base_play(
                        "g2", 2, "Team C", "Team A",
                        play_type="pass", is_pass_attempt=True, is_rush_attempt=False,
                        completion=False, yards_gained=0,
                    ),  # not success
                    base_play("g2", 3, "Team C", "Team A", down=2, distance=8, yards_gained=0, is_td=True),  # TD, stuffed
                ],
            )

            points = {
                row[0]: row[1:]
                for row in conn.execute(
                    """
                    SELECT team_name, games, points_scored, points_allowed, ppg, ppg_allowed, ppg_rank, ppg_allowed_rank
                    FROM v_team_season_points_ranked_current
                    WHERE season = '2025-26'
                    """
                ).fetchall()
            }
            self.assertEqual(
                points,
                {
                    "Team A": (2, 6, 6, 3.0, 3.0, 2, 2),
                    "Team B": (1, 0, 6, 0.0, 6.0, 3, 3),
                    "Team C": (1, 6, 0, 6.0, 0.0, 1, 1),
                },
            )

            offense = {
                row[0]: row[1:]
                for row in conn.execute(
                    """
                    SELECT team_name, success_rate, explosive_rate, rush_explosive_rate,
                           pass_explosive_rate, run_stuff_rate, success_rate_rank,
                           explosive_rate_rank, rush_explosive_rate_rank,
                           pass_explosive_rate_rank, run_stuff_rate_rank
                    FROM v_team_season_offense_ranked_current
                    WHERE season = '2025-26'
                    """
                ).fetchall()
            }
            self.assertEqual(
                offense,
                {
                    "Team A": (50.0, 50.0, 33.3, 100.0, 66.7, 1, 1, 2, 1, 2),
                    "Team C": (33.3, 33.3, 50.0, 0.0, 50.0, 2, 2, 1, 2, 1),
                },
            )

            defense = {
                row[0]: row[1:]
                for row in conn.execute(
                    """
                    SELECT team_name, opp_success_rate, opp_explosive_rate, opp_rush_explosive_rate,
                           opp_pass_explosive_rate, opp_run_stuff_rate, opp_success_rate_rank,
                           opp_explosive_rate_rank, opp_rush_explosive_rate_rank,
                           opp_pass_explosive_rate_rank, opp_run_stuff_rate_rank
                    FROM v_team_season_defense_ranked_current
                    WHERE season = '2025-26'
                    """
                ).fetchall()
            }
            self.assertEqual(
                defense,
                {
                    "Team A": (33.3, 33.3, 50.0, 0.0, 50.0, 1, 1, 2, 1, 2),
                    "Team B": (50.0, 50.0, 33.3, 100.0, 66.7, 2, 2, 1, 2, 1),
                },
            )
            conn.close()

    def test_drives_view_scoring_and_three_and_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "plays-drv",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "stage": "plays",
                    },
                    {
                        "run_id": "fieldpos-drv",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:02:00",
                        "finished_at": "2026-01-01 00:03:00",
                        "status": "completed",
                        "stage": "field_position",
                        "notes": '{"field_position_rows": 13, "resolved_count": 13, "source_plays_run_id": "plays-drv", "unresolved_count": 0}',
                    },
                ],
            )

            def base_play(play_id: int, drive_id: int, **overrides: object) -> dict[str, object]:
                row: dict[str, object] = {
                    "run_id": "plays-drv",
                    "season": "2025-26",
                    "game_id": "g-drv",
                    "home_team": "Drive Team",
                    "away_team": "Drive Opp",
                    "schedule_home": "Drive Team",
                    "schedule_away": "Drive Opp",
                    "play_id": play_id,
                    "drive_id": drive_id,
                    "quarter": 1,
                    "down": 1,
                    "distance": 10,
                    "offense": "Drive Team",
                    "defense": "Drive Opp",
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

            plays = [
                # Drive 1 (start yardline_100=30): 2 plays, ends in a TD -- a
                # scoring drive, not a 3-and-out (it scored).
                base_play(1, 1, down=1, distance=10, yards_gained=5),
                base_play(2, 1, down=2, distance=5, yards_gained=5, is_td=True),
                # Drive 2 (start=45): 3 scrimmage plays then a punt --
                # 3-and-out via punt.
                base_play(3, 2, down=1, distance=10, yards_gained=2),
                base_play(
                    4, 2, down=2, distance=8, yards_gained=0,
                    play_type="pass", is_pass_attempt=True, is_rush_attempt=False, completion=False,
                ),
                base_play(5, 2, down=3, distance=8, yards_gained=1),
                base_play(6, 2, play_type="punt", is_pass_attempt=False, is_rush_attempt=False),
                # Drive 3 (start=60): 3 scrimmage plays, no punt (turnover on
                # downs) -- still a 3-and-out per the chosen definition
                # (<=3 scrimmage plays, non-scoring end).
                base_play(7, 3, down=1, distance=10, yards_gained=2),
                base_play(8, 3, down=2, distance=8, yards_gained=1),
                base_play(9, 3, down=3, distance=7, yards_gained=0),
                # Drive 4 (start=25): 4 scrimmage plays, non-scoring -- NOT a
                # 3-and-out (more than 3 plays).
                base_play(10, 4, down=1, distance=10, yards_gained=3),
                base_play(11, 4, down=2, distance=7, yards_gained=2),
                base_play(12, 4, down=3, distance=5, yards_gained=1),
                base_play(13, 4, down=4, distance=4, yards_gained=1),
            ]
            insert_rows(conn, "plays", plays)

            start_yardline_by_drive = {1: 30, 2: 45, 3: 60, 4: 25}
            insert_rows(
                conn,
                "play_field_positions",
                [
                    {
                        "run_id": "fieldpos-drv",
                        "season": "2025-26",
                        "source_plays_run_id": "plays-drv",
                        "game_id": "g-drv",
                        "play_id": p["play_id"],
                        "field_position": "TEST00",
                        "field_pos_prefix": "TEST",
                        "yardline_raw": 0,
                        "offense": "Drive Team",
                        "prefix_owner": "Drive Team",
                        "field_pos_side": "own",
                        "yardline_100": start_yardline_by_drive[p["drive_id"]],
                        "resolution_status": "resolved",
                        "created_at": "2026-01-01 00:02:00",
                    }
                    for p in plays
                ],
            )

            drive_rows = conn.execute(
                """
                SELECT drive_id, start_yardline_100, scrimmage_plays, drive_points,
                       is_scoring_drive, is_three_and_out
                FROM v_drives_current
                WHERE season = '2025-26' AND game_id = 'g-drv'
                ORDER BY drive_id
                """
            ).fetchall()
            self.assertEqual(
                drive_rows,
                [
                    (1, 30, 2, 6, True, False),
                    (2, 45, 3, 0, False, True),
                    (3, 60, 3, 0, False, True),
                    (4, 25, 4, 0, False, False),
                ],
            )

            offense_ranked = conn.execute(
                """
                SELECT drives, total_scrimmage_plays, total_start_yardline_100,
                       drives_scored, drives_three_and_out, avg_plays_per_drive,
                       avg_start_yardline_100, pct_drives_scored, pct_drives_three_and_out,
                       plays_per_game
                FROM v_team_season_drives_offense_ranked_current
                WHERE season = '2025-26' AND team_name = 'Drive Team'
                """
            ).fetchone()
            self.assertEqual(
                offense_ranked,
                (4, 12, 160, 1, 2, 3.0, 40.0, 25.0, 50.0, 12.0),
            )

            defense_ranked = conn.execute(
                """
                SELECT drives, total_scrimmage_plays, total_start_yardline_100,
                       drives_scored, drives_three_and_out, avg_plays_per_drive,
                       avg_start_yardline_100, pct_drives_scored, pct_drives_three_and_out,
                       plays_per_game
                FROM v_team_season_drives_defense_ranked_current
                WHERE season = '2025-26' AND team_name = 'Drive Opp'
                """
            ).fetchone()
            self.assertEqual(
                defense_ranked,
                (4, 12, 160, 1, 2, 3.0, 40.0, 25.0, 50.0, 12.0),
            )
            conn.close()

    def test_schedule_running_record_entering_game(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "structure-sched",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "stage": "structure",
                    },
                ],
            )
            insert_rows(
                conn,
                "schedule",
                [
                    {
                        "run_id": "structure-sched",
                        "season": "2025-26",
                        "team_name": "Streak Team",
                        "team_id": "st1",
                        "game_id": "gs1",
                        "game_date": "20250901",
                        "home_away": "home",
                        "opponent": "Opp1",
                        "result": "W, 20-0",
                        "pbp_url": None,
                        "schedule_home": "Streak Team",
                        "schedule_away": "Opp1",
                    },
                    {
                        "run_id": "structure-sched",
                        "season": "2025-26",
                        "team_name": "Streak Team",
                        "team_id": "st1",
                        "game_id": "gs2",
                        "game_date": "20250908",
                        "home_away": "home",
                        "opponent": "Opp2",
                        "result": "W, 30-10",
                        "pbp_url": None,
                        "schedule_home": "Streak Team",
                        "schedule_away": "Opp2",
                    },
                    {
                        "run_id": "structure-sched",
                        "season": "2025-26",
                        "team_name": "Streak Team",
                        "team_id": "st1",
                        "game_id": "gs3",
                        "game_date": "20250915",
                        "home_away": "home",
                        "opponent": "Opp3",
                        "result": "L, 10-40",
                        "pbp_url": None,
                        "schedule_home": "Streak Team",
                        "schedule_away": "Opp3",
                    },
                ],
            )

            rows = conn.execute(
                """
                SELECT game_id, wins_entering_game, losses_entering_game, ties_entering_game
                FROM v_schedule_current
                WHERE season = '2025-26' AND team_name = 'Streak Team'
                ORDER BY game_date
                """
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    ("gs1", 0, 0, 0),
                    ("gs2", 1, 0, 0),
                    ("gs3", 2, 0, 0),
                ],
            )
            conn.close()

    def test_fumble_recovery_defensive_td_excluded_from_pass_td_and_sack_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
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
                conn,
                "plays",
                [
                    # 1: ordinary completion, not a score.
                    base_play(1, completion=True, yards_gained=20),
                    # 2: a sack -- play_type stays 'pass' but flips to a rush
                    # attempt per this project's convention (README.md).
                    base_play(
                        2, is_pass_attempt=False, is_rush_attempt=True, is_sack=True, yards_gained=-7,
                    ),
                    # 3: Away fumbles on a pass play; Home's defense recovers
                    # and returns it for a score. Raw is_td=True is
                    # misleading (simulating the real RE_FUMBLE pollution
                    # bug) -- the crosswalk below resolves is_defensive_td
                    # correctly. This should NOT count as Away's pass_td, and
                    # should NOT count as Home allowing an opponent pass TD.
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
                conn,
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

            offense_row = conn.execute(
                """
                SELECT pass_att, pass_td, sacks, dropbacks, sack_rate, sack_rate_rank
                FROM v_team_season_offense_ranked_current
                WHERE season = '2025-26' AND team_name = 'Away'
                """
            ).fetchone()
            # pass_td must be 0 -- NOT 1 -- proving play 3's misleading
            # is_td=True did not leak into Away's own passing-TD count.
            self.assertEqual(offense_row, (2, 0, 1, 3, 33.3, 1))

            defense_row = conn.execute(
                """
                SELECT opp_pass_att, opp_pass_td, sacks_forced, opp_dropbacks, opp_sack_rate, opp_sack_rate_rank
                FROM v_team_season_defense_ranked_current
                WHERE season = '2025-26' AND team_name = 'Home'
                """
            ).fetchone()
            # opp_pass_td must be 0 -- Home's own defensive score should not
            # be recorded as a touchdown Home's defense "allowed."
            self.assertEqual(defense_row, (2, 0, 1, 3, 33.3, 1))
            conn.close()

    def test_field_position_is_stale_flips_when_plays_run_moves_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "plays-1",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "stage": "plays",
                        "notes": None,
                    },
                    {
                        "run_id": "fieldpos-1",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:02:00",
                        "finished_at": "2026-01-01 00:03:00",
                        "status": "completed",
                        "stage": "field_position",
                        "notes": '{"source_plays_run_id": "plays-1", "field_position_rows": 5, "resolved_count": 5, "unresolved_count": 0}',
                    },
                ],
            )

            # Only plays-1 exists so far, and field_position was built from
            # it -- not stale.
            row = conn.execute(
                "SELECT plays_run_id, field_position_source_plays_run_id, field_position_is_stale FROM v_current_runs WHERE season = '2025-26'"
            ).fetchone()
            self.assertEqual(row, ("plays-1", "plays-1", False))

            # A new plays run lands (e.g. a reparse) with no matching
            # field_position run yet -- now stale, even though a
            # field_position run still exists (it's just built from the
            # OLD plays run).
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "plays-2",
                        "season": "2025-26",
                        "started_at": "2026-01-02 00:00:00",
                        "finished_at": "2026-01-02 00:01:00",
                        "status": "completed",
                        "stage": "plays",
                    },
                ],
            )
            row = conn.execute(
                "SELECT plays_run_id, field_position_source_plays_run_id, field_position_is_stale FROM v_current_runs WHERE season = '2025-26'"
            ).fetchone()
            self.assertEqual(row, ("plays-2", "plays-1", True))

            conn.close()

    def test_field_position_is_stale_true_when_no_field_position_run_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "plays-only",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "stage": "plays",
                    },
                ],
            )
            row = conn.execute(
                "SELECT field_position_source_plays_run_id, field_position_is_stale FROM v_current_runs WHERE season = '2025-26'"
            ).fetchone()
            self.assertEqual(row, (None, True))
            conn.close()


if __name__ == "__main__":
    unittest.main()
