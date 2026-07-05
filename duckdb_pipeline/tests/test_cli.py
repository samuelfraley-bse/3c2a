import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone

from duckdb_pipeline.cli import (
    _auto_refresh_field_positions,
    _load_field_position_review_queue,
    _preseed_memory_crosswalk_rows,
    main_rebuild_plays_from_raw,
    main_rebuild_structure_from_raw,
)
from duckdb_pipeline.db import connect, init_db, insert_rows

PBP_HTML_TWO_TEAMS = """
<html>
  <head>
    <meta property="og:title" content="Foothill vs. San Mateo - Box Score - 9/6/2025" />
  </head>
  <body>
    <table>
      <tr><td id="qtr1">1st Quarter</td></tr>
      <tr><th colspan="2">Foothill at 15:00</th></tr>
      <tr>
        <td>1st and 10 at FOOTHILL25</td>
        <td>John Smith rush for 5 yards to the FOOTHILL30 (Mike Jones).</td>
      </tr>
      <tr>
        <td>2nd and 5 at FOOTHILL30</td>
        <td>John Smith pass complete to Alex Ray for 12 yards to the SAN MATE48 (Ty Lee).</td>
      </tr>
      <tr>
        <td>1st and 10 at SAN MATE48</td>
        <td>PENALTY SAN MATE holding (Ty Lee) 10 yards</td>
      </tr>
    </table>
  </body>
</html>
"""


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

    def test_rebuild_plays_from_raw_auto_applies_field_position_when_memory_resolves_everything(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "structure-1",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "stage": "structure",
                        "notes": None,
                    },
                    {
                        "run_id": "plays-old",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:02:00",
                        "finished_at": "2026-01-01 00:03:00",
                        "status": "completed",
                        "stage": "plays",
                        "notes": '{"source_run_id": "structure-1"}',
                    },
                ],
            )
            insert_rows(
                conn,
                "games",
                [
                    {
                        "run_id": "structure-1",
                        "season": "2025-26",
                        "game_id": "20250906_abcd",
                        "game_date": "20250906",
                        "pbp_url": "https://example.test/pbp",
                        "schedule_home": "Foothill",
                        "schedule_away": "San Mateo",
                        "home_team_canonical": "Foothill",
                        "away_team_canonical": "San Mateo",
                        "team_1": "Foothill",
                        "team_2": "San Mateo",
                        "schedule_row_count": 2,
                        "unique_team_count": 2,
                        "pairing_status": "paired",
                    }
                ],
            )
            insert_rows(
                conn,
                "raw_pbp_html",
                [
                    {
                        "run_id": "plays-old",
                        "season": "2025-26",
                        "source_run_id": "structure-1",
                        "game_id": "20250906_abcd",
                        "fetched_at": datetime.now(timezone.utc),
                        "source_url": "https://example.test/pbp",
                        "html_text": PBP_HTML_TWO_TEAMS,
                    }
                ],
            )
            # _resolve_plays_run_id validates the source run_id against the
            # actual `plays` table (not just the pipeline_runs audit row) --
            # a minimal placeholder row is enough to satisfy that check.
            insert_rows(
                conn,
                "plays",
                [
                    {
                        "run_id": "plays-old",
                        "season": "2025-26",
                        "game_id": "20250906_abcd",
                        "play_id": 1,
                    }
                ],
            )
            # Prior confirmed crosswalk memory from an earlier week/run --
            # same prefixes this reparse will detect, so nothing here should
            # need manual review.
            insert_rows(
                conn,
                "field_position_crosswalk",
                [
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "some-other-earlier-run",
                        "game_id": "g-earlier",
                        "prefix": "FOOTHILL",
                        "canonical_team": "Foothill",
                        "resolution_method": "manual",
                        "note": "",
                        "resolved_at": datetime.now(timezone.utc),
                    },
                    {
                        "season": "2025-26",
                        "source_plays_run_id": "some-other-earlier-run",
                        "game_id": "g-earlier",
                        "prefix": "SAN MATE",
                        "canonical_team": "San Mateo",
                        "resolution_method": "manual",
                        "note": "",
                        "resolved_at": datetime.now(timezone.utc),
                    },
                ],
            )
            conn.close()

            exit_code = main_rebuild_plays_from_raw(
                ["--season", "2025-26", "--db-path", db_path, "--source-plays-run-id", "plays-old"]
            )
            self.assertEqual(exit_code, 0)

            conn = connect(db_path)
            # Field position should be auto-applied -- not stale -- with no
            # separate apply_field_positions call.
            stale = conn.execute(
                "SELECT field_position_is_stale FROM v_current_runs WHERE season = '2025-26'"
            ).fetchone()[0]
            self.assertFalse(stale)

            resolved = conn.execute(
                """
                SELECT DISTINCT prefix_owner
                FROM v_play_field_positions_current
                WHERE season = '2025-26' AND game_id = '20250906_abcd'
                ORDER BY prefix_owner
                """
            ).fetchall()
            self.assertEqual(resolved, [("Foothill",), ("San Mateo",)])
            conn.close()

    def test_auto_refresh_field_positions_does_not_apply_when_prefix_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.duckdb"
            conn = connect(db_path)
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "plays-new",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "stage": "plays",
                        "notes": '{"source_run_id": "structure-1"}',
                    },
                    {
                        "run_id": "structure-1",
                        "season": "2025-26",
                        "started_at": "2025-12-31 00:00:00",
                        "finished_at": "2025-12-31 00:01:00",
                        "status": "completed",
                        "stage": "structure",
                        "notes": None,
                    },
                ],
            )
            insert_rows(
                conn,
                "games",
                [
                    {
                        "run_id": "structure-1",
                        "season": "2025-26",
                        "game_id": "g-new",
                        "game_date": "20250913",
                        "pbp_url": "https://example.test/pbp2",
                        "schedule_home": "Brand New Team",
                        "schedule_away": "Another New Team",
                        "home_team_canonical": "Brand New Team",
                        "away_team_canonical": "Another New Team",
                        "team_1": "Brand New Team",
                        "team_2": "Another New Team",
                        "schedule_row_count": 2,
                        "unique_team_count": 2,
                        "pairing_status": "paired",
                    }
                ],
            )
            insert_rows(
                conn,
                "plays",
                [
                    {
                        "run_id": "plays-new",
                        "season": "2025-26",
                        "game_id": "g-new",
                        "home_team": "Brand New Team",
                        "away_team": "Another New Team",
                        "schedule_home": "Brand New Team",
                        "schedule_away": "Another New Team",
                        "play_id": 1,
                        "quarter": 1,
                        "down": 1,
                        "distance": 10,
                        "field_position": "BRANDNEW25",
                        "yardline_raw": 25,
                        "offense": "Brand New Team",
                        "defense": "Another New Team",
                        "play_type": "rush",
                        "yards_gained": 5,
                        "is_dropback": False,
                        "is_pass_attempt": False,
                        "is_rush_attempt": True,
                        "completion": False,
                        "is_interception": False,
                        "is_td": False,
                        "is_sack": False,
                        "is_fumble": False,
                        "is_penalty": False,
                        "raw_text": "placeholder",
                    },
                ],
            )
            # No prior crosswalk memory exists for "BRANDNEW" -- genuinely
            # new, unresolvable without a human.

            _auto_refresh_field_positions(conn, "2025-26", "plays-new")

            # Must NOT have auto-applied: no field_position stage run exists,
            # and the season stays flagged as stale.
            field_position_run = conn.execute(
                "SELECT COUNT(*) FROM pipeline_runs WHERE season = '2025-26' AND stage = 'field_position' AND status = 'completed'"
            ).fetchone()[0]
            self.assertEqual(field_position_run, 0)
            stale = conn.execute(
                "SELECT field_position_is_stale FROM v_current_runs WHERE season = '2025-26'"
            ).fetchone()[0]
            self.assertTrue(stale)
            conn.close()


if __name__ == "__main__":
    unittest.main()
