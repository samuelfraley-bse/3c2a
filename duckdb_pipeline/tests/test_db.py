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

            current_play_ids = conn.execute(
                "SELECT play_id FROM v_plays_current WHERE season = '2025-26' ORDER BY play_id"
            ).fetchall()
            self.assertEqual(current_play_ids, [(1,), (2,), (3,)])

            offense_row = conn.execute(
                """
                SELECT
                    team_name,
                    pass_att,
                    pass_comp,
                    pass_yds,
                    pass_int,
                    pass_td,
                    rush_att,
                    rush_yds,
                    rush_td,
                    sacks,
                    dropbacks,
                    play_count
                FROM v_team_game_offense_current
                WHERE season = '2025-26' AND game_id = 'g-new' AND team_name = 'Foothill'
                """
            ).fetchone()
            self.assertEqual(
                offense_row,
                ("Foothill", 1, 1, 12, 0, 1, 2, 1, 0, 1, 2, 3),
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


if __name__ == "__main__":
    unittest.main()
