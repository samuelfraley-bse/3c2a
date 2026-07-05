import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone

from duckdb_pipeline.cli import (
    _load_field_position_review_queue,
    _preseed_memory_crosswalk_rows,
    main_rebuild_structure_from_raw,
)
from duckdb_pipeline.db import connect, init_db, insert_rows


STANDINGS_HTML = """
<html>
  <body>
    <h3>Bay 6</h3>
    <table class="table bg-white">
      <thead>
        <tr>
          <td aria-hidden="true">&nbsp;</td>
          <th colspan="3">Conference</th>
          <th colspan="5">Overall</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><a href="/sports/fball/2025-26/schedule?teamId=101"><span class="team-name">Foothill</span></a></td>
          <td class="stats-col">5</td>
          <td class="stats-col">4-1</td>
          <td class="stats-col">.800</td>
          <td class="stats-col">10</td>
          <td class="stats-col">8-2</td>
          <td class="stats-col">.800</td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""

SCHEDULE_HOME_HTML = """
<html>
  <body>
    <table>
      <tr class="event-row home">
        <td><a href="/sports/fball/2025-26/boxscores/20250906_abcd.xml">Box</a></td>
        <td class="team opponent"><span class="team-name">San Mateo</span></td>
        <td class="result">W, 42-7</td>
      </tr>
    </table>
  </body>
</html>
"""


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

    def test_rebuild_structure_from_raw_reparses_without_rescraping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "raw_standings_html",
                [
                    {
                        "run_id": "structure-raw-1",
                        "season": "2025-26",
                        "fetched_at": datetime.now(timezone.utc),
                        "source_url": "https://example.test/standings",
                        "html_text": STANDINGS_HTML,
                    }
                ],
            )
            insert_rows(
                conn,
                "raw_schedule_html",
                [
                    {
                        "run_id": "structure-raw-1",
                        "season": "2025-26",
                        "team_id": "101",
                        "team_name": "Foothill",
                        "fetched_at": datetime.now(timezone.utc),
                        "source_url": "https://example.test/foothill-schedule",
                        "html_text": SCHEDULE_HOME_HTML,
                    }
                ],
            )
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "structure-raw-1",
                        "season": "2025-26",
                        "stage": "structure",
                        "started_at": datetime.now(timezone.utc),
                        "finished_at": datetime.now(timezone.utc),
                        "status": "completed",
                        "standings_count": 1,
                        "schedule_count": 1,
                        "games_count": 1,
                        "notes": None,
                    }
                ],
            )
            conn.close()

            exit_code = main_rebuild_structure_from_raw(
                [
                    "--season",
                    "2025-26",
                    "--db-path",
                    db_path,
                    "--source-structure-run-id",
                    "structure-raw-1",
                ]
            )
            self.assertEqual(exit_code, 0)

            conn = connect(db_path)
            standings = conn.execute(
                "SELECT team_name FROM v_standings_current WHERE season = '2025-26'"
            ).fetchall()
            self.assertEqual(standings, [("Foothill",)])
            games = conn.execute(
                "SELECT game_id FROM v_games_current WHERE season = '2025-26'"
            ).fetchall()
            self.assertEqual(games, [("20250906_abcd",)])
            latest_stage = conn.execute(
                """
                SELECT stage FROM pipeline_runs
                WHERE season = '2025-26' AND status = 'completed'
                ORDER BY finished_at DESC LIMIT 1
                """
            ).fetchone()[0]
            self.assertEqual(latest_stage, "structure")
            conn.close()


if __name__ == "__main__":
    unittest.main()
