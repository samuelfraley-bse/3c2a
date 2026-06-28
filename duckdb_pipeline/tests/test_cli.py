import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone

from duckdb_pipeline.cli import _load_field_position_review_queue, _preseed_memory_crosswalk_rows
from duckdb_pipeline.db import connect, init_db, insert_rows


@unittest.skipUnless(importlib.util.find_spec("duckdb"), "duckdb not installed")
class CliTests(unittest.TestCase):
    def test_load_field_position_review_queue_filters_resolved_and_reindexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            detected_at = datetime.now(timezone.utc)
            resolved_at = datetime.now(timezone.utc)

            insert_rows(
                conn,
                "field_position_prefixes",
                [
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g1",
                        "prefix": "FOOTHILL",
                        "team_1": "Foothill",
                        "team_2": "Monterey Peninsula",
                        "schedule_home": "Foothill",
                        "schedule_away": "Monterey Peninsula",
                        "play_count": 10,
                        "first_play_id": 1,
                        "last_play_id": 10,
                        "detected_at": detected_at,
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g1",
                        "prefix": "MONTEREY",
                        "team_1": "Foothill",
                        "team_2": "Monterey Peninsula",
                        "schedule_home": "Foothill",
                        "schedule_away": "Monterey Peninsula",
                        "play_count": 8,
                        "first_play_id": 11,
                        "last_play_id": 18,
                        "detected_at": detected_at,
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g2",
                        "prefix": "LONG BEA",
                        "team_1": "Long Beach",
                        "team_2": "Riverside",
                        "schedule_home": "Riverside",
                        "schedule_away": "Long Beach",
                        "play_count": 12,
                        "first_play_id": 1,
                        "last_play_id": 12,
                        "detected_at": detected_at,
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g2",
                        "prefix": "RIVERSID",
                        "team_1": "Long Beach",
                        "team_2": "Riverside",
                        "schedule_home": "Riverside",
                        "schedule_away": "Long Beach",
                        "play_count": 14,
                        "first_play_id": 13,
                        "last_play_id": 26,
                        "detected_at": detected_at,
                    },
                ],
            )
            insert_rows(
                conn,
                "field_position_crosswalk",
                [
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g1",
                        "prefix": "FOOTHILL",
                        "canonical_team": "Foothill",
                        "resolution_method": "manual",
                        "note": "",
                        "resolved_at": resolved_at,
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g1",
                        "prefix": "MONTEREY",
                        "canonical_team": "Monterey Peninsula",
                        "resolution_method": "manual",
                        "note": "",
                        "resolved_at": resolved_at,
                    },
                ],
            )

            unresolved = _load_field_position_review_queue(conn, "2025-26", "plays-run-1")
            self.assertEqual(len(unresolved), 1)
            self.assertEqual(unresolved[0]["queue_index"], 1)
            self.assertEqual(unresolved[0]["game_id"], "g2")

            all_rows = _load_field_position_review_queue(
                conn,
                "2025-26",
                "plays-run-1",
                include_resolved=True,
            )
            self.assertEqual(len(all_rows), 2)
            self.assertEqual(all_rows[0]["queue_index"], 1)
            self.assertEqual(all_rows[1]["queue_index"], 2)
            conn.close()

    def test_preseed_memory_uses_confirmed_team_prefix_rows_from_same_run_for_later_games(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            detected_at = datetime.now(timezone.utc)
            resolved_at = datetime.now(timezone.utc)

            insert_rows(
                conn,
                "field_position_prefixes",
                [
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g1",
                        "prefix": "LANEY",
                        "team_1": "Laney",
                        "team_2": "Butte",
                        "schedule_home": "Laney",
                        "schedule_away": "Butte",
                        "play_count": 10,
                        "first_play_id": 1,
                        "last_play_id": 10,
                        "detected_at": detected_at,
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g1",
                        "prefix": "BUTTE",
                        "team_1": "Laney",
                        "team_2": "Butte",
                        "schedule_home": "Laney",
                        "schedule_away": "Butte",
                        "play_count": 10,
                        "first_play_id": 11,
                        "last_play_id": 20,
                        "detected_at": detected_at,
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g2",
                        "prefix": "LANEY",
                        "team_1": "Laney",
                        "team_2": "Modesto",
                        "schedule_home": "Modesto",
                        "schedule_away": "Laney",
                        "play_count": 12,
                        "first_play_id": 1,
                        "last_play_id": 12,
                        "detected_at": detected_at,
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g2",
                        "prefix": "MODESTO",
                        "team_1": "Laney",
                        "team_2": "Modesto",
                        "schedule_home": "Modesto",
                        "schedule_away": "Laney",
                        "play_count": 14,
                        "first_play_id": 13,
                        "last_play_id": 26,
                        "detected_at": detected_at,
                    },
                ],
            )
            insert_rows(
                conn,
                "field_position_crosswalk",
                [
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g1",
                        "prefix": "LANEY",
                        "canonical_team": "Laney",
                        "resolution_method": "manual",
                        "note": "",
                        "resolved_at": resolved_at,
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "plays-run-1",
                        "game_id": "g1",
                        "prefix": "BUTTE",
                        "canonical_team": "Butte",
                        "resolution_method": "manual",
                        "note": "",
                        "resolved_at": resolved_at,
                    },
                ],
            )

            prefix_rows = [
                {
                    "season": "2025-26",
                    "source_plays_run_id": "plays-run-1",
                    "game_id": "g1",
                    "prefix": "LANEY",
                    "team_1": "Laney",
                    "team_2": "Butte",
                },
                {
                    "season": "2025-26",
                    "source_plays_run_id": "plays-run-1",
                    "game_id": "g1",
                    "prefix": "BUTTE",
                    "team_1": "Laney",
                    "team_2": "Butte",
                },
                {
                    "season": "2025-26",
                    "source_plays_run_id": "plays-run-1",
                    "game_id": "g2",
                    "prefix": "LANEY",
                    "team_1": "Laney",
                    "team_2": "Modesto",
                },
                {
                    "season": "2025-26",
                    "source_plays_run_id": "plays-run-1",
                    "game_id": "g2",
                    "prefix": "MODESTO",
                    "team_1": "Laney",
                    "team_2": "Modesto",
                },
            ]

            seeded_games = _preseed_memory_crosswalk_rows(conn, prefix_rows, "2025-26", "plays-run-1")
            self.assertEqual(seeded_games, 1)
            rows = conn.execute(
                """
                select game_id, prefix, canonical_team
                from field_position_crosswalk
                where season = '2025-26' and source_plays_run_id = 'plays-run-1'
                order by game_id, prefix
                """
            ).fetchall()
            self.assertIn(("g2", "LANEY", "Laney"), rows)
            self.assertIn(("g2", "MODESTO", "Modesto"), rows)
            conn.close()


if __name__ == "__main__":
    unittest.main()
