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
            conn.close()


if __name__ == "__main__":
    unittest.main()
