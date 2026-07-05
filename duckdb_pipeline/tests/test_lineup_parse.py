import json
import tempfile
import unittest

from duckdb_pipeline.db import connect, init_db, insert_rows
from duckdb_pipeline.lineup_parse import parse_players_json

# A small, hand-built players_json fixture covering the three cases that
# matter: a QB (passing + some incidental rushing), a defender (tackles/
# sacks/etc.), and an offensive lineman -- a real, common position with no
# individual stat category at all, exercising the "other" fallback rather
# than crashing.
SAMPLE_PLAYERS_JSON = json.dumps(
    {
        "individuals": [
            {
                "playerId": "pid1",
                "pageName": "testqb1",
                "fullName": "Test QB",
                "firstName": "Test",
                "lastName": "QB",
                "team": "TeamA",
                "teamId": "tid1",
                "position": "QB",
                "positionAbbreviation": "QB",
                "uniform": "12",
                "year": "So",
                "active": True,
                "stats": {
                    "gp": "5",
                    "pa": "50",
                    "pc": "30",
                    "ppt": "60.0%",
                    "pyd": "400",
                    "pyg": "80.0",
                    "pya": "8.0",
                    "ptd": "4",
                    "pin": "1",
                    "plg": "45",
                    "peff": "150.5",
                    "rat": "10",
                    "ryd": "20",
                    "fum": "1",
                    "fuml": "0",
                },
            },
            {
                "playerId": "pid2",
                "pageName": "testlb1",
                "fullName": "Test LB",
                "firstName": "Test",
                "lastName": "LB",
                "team": "TeamA",
                "teamId": "tid1",
                "position": "LB",
                "positionAbbreviation": "LB",
                "uniform": "45",
                "year": "Jr",
                "active": True,
                "stats": {
                    "gp": "5",
                    "dtu": "20",
                    "dta": "10",
                    "dtt": "30.0",
                    "dtpg": "6.0",
                    "dst": "3",
                    "dsyd": "15",
                    "tfl": "5.0",
                    "tfly": "12",
                    "dff": "1",
                    "dfr": "0",
                    "di": "1",
                    "diyd": "10",
                    "dbru": "2",
                    "dblk": "0",
                },
            },
            {
                "playerId": "pid3",
                "pageName": "testol1",
                "fullName": "Test OL",
                "firstName": "Test",
                "lastName": "OL",
                "team": "TeamA",
                "teamId": "tid1",
                "position": "OL",
                "positionAbbreviation": "OL",
                "uniform": "70",
                "year": "Fr",
                "active": True,
                "stats": {"gp": "5"},
            },
        ]
    }
)


class LineupParseTests(unittest.TestCase):
    def test_parse_players_json_qb_row(self) -> None:
        rows = parse_players_json(SAMPLE_PLAYERS_JSON, "2025-26", "run-lineup-1")
        qb = next(r for r in rows if r["page_name"] == "testqb1")
        self.assertEqual(qb["position_group"], "qb")
        self.assertEqual(qb["team"], "TeamA")
        self.assertEqual(qb["pass_att"], 50.0)
        self.assertEqual(qb["pass_comp"], 30.0)
        self.assertEqual(qb["pass_pct"], 60.0)  # trailing "%" stripped
        self.assertEqual(qb["pass_yds"], 400.0)
        self.assertEqual(qb["pass_td"], 4.0)
        self.assertEqual(qb["pass_int"], 1.0)
        self.assertEqual(qb["pass_rating"], 150.5)
        # A QB's incidental rushing still lands in rush_*, not gated by
        # position_group.
        self.assertEqual(qb["rush_att"], 10.0)
        self.assertEqual(qb["rush_yds"], 20.0)
        # Never-recorded categories (e.g. receiving) are None, not 0 or an error.
        self.assertIsNone(qb["rec"])
        self.assertIsNone(qb["tackles_total"])

    def test_parse_players_json_defender_row(self) -> None:
        rows = parse_players_json(SAMPLE_PLAYERS_JSON, "2025-26", "run-lineup-1")
        lb = next(r for r in rows if r["page_name"] == "testlb1")
        self.assertEqual(lb["position_group"], "d")
        self.assertEqual(lb["tackles_solo"], 20.0)
        self.assertEqual(lb["tackles_ast"], 10.0)
        self.assertEqual(lb["tackles_total"], 30.0)
        self.assertEqual(lb["sacks"], 3.0)
        self.assertEqual(lb["tfl"], 5.0)
        self.assertEqual(lb["interceptions"], 1.0)

    def test_parse_players_json_unmapped_position_falls_back_to_other(self) -> None:
        rows = parse_players_json(SAMPLE_PLAYERS_JSON, "2025-26", "run-lineup-1")
        ol = next(r for r in rows if r["page_name"] == "testol1")
        self.assertEqual(ol["position_group"], "other")
        self.assertEqual(ol["position"], "OL")
        # No stat categories recorded for this lineman -- everything else
        # should be None, not a crash.
        self.assertIsNone(ol["pass_att"])
        self.assertIsNone(ol["tackles_total"])
        self.assertEqual(ol["games_played"], 5.0)


class LineupStatsDbTests(unittest.TestCase):
    def test_player_lineup_stats_current_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect(f"{tmpdir}/test.duckdb")
            init_db(conn)
            insert_rows(
                conn,
                "pipeline_runs",
                [
                    {
                        "run_id": "run-lineup-stats-1",
                        "season": "2025-26",
                        "started_at": "2026-01-01 00:00:00",
                        "finished_at": "2026-01-01 00:01:00",
                        "status": "completed",
                        "stage": "lineup_stats",
                    },
                ],
            )
            rows = parse_players_json(SAMPLE_PLAYERS_JSON, "2025-26", "run-lineup-stats-1")
            insert_rows(conn, "player_lineup_stats", rows)

            qb_row = conn.execute(
                """
                SELECT full_name, position_group, pass_att, pass_yds, pass_rating
                FROM v_player_lineup_stats_current
                WHERE season = '2025-26' AND team = 'TeamA' AND position_group = 'qb'
                """
            ).fetchone()
            self.assertEqual(qb_row, ("Test QB", "qb", 50.0, 400.0, 150.5))

            defense_leader = conn.execute(
                """
                SELECT full_name, tackles_total, sacks
                FROM v_player_lineup_stats_current
                WHERE season = '2025-26' AND team = 'TeamA' AND position_group = 'd'
                ORDER BY tackles_total DESC
                LIMIT 1
                """
            ).fetchone()
            self.assertEqual(defense_leader, ("Test LB", 30.0, 3.0))

            conn.close()


if __name__ == "__main__":
    unittest.main()
