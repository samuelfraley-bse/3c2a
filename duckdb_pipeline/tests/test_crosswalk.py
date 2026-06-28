import unittest

from duckdb_pipeline.crosswalk import (
    build_crosswalk_resolution_rows,
    build_field_position_prefix_rows,
    build_field_position_rows,
    extract_field_position_prefix,
)


class CrosswalkTests(unittest.TestCase):
    def test_extract_field_position_prefix(self) -> None:
        self.assertEqual(extract_field_position_prefix("FOOTHILL25"), "FOOTHILL")
        self.assertEqual(extract_field_position_prefix("MT. SAN31"), "MT. SAN")
        self.assertIsNone(extract_field_position_prefix(""))

    def test_build_field_position_prefix_rows(self) -> None:
        plays_rows = [
            {"game_id": "g1", "play_id": 1, "field_position": "FOOTHILL25"},
            {"game_id": "g1", "play_id": 2, "field_position": "MONTEREY40"},
            {"game_id": "g1", "play_id": 3, "field_position": "FOOTHILL30"},
        ]
        games_by_id = {
            "g1": {
                "team_1": "Foothill",
                "team_2": "Monterey Peninsula",
                "schedule_home": "Foothill",
                "schedule_away": "Monterey Peninsula",
            }
        }
        rows = build_field_position_prefix_rows(plays_rows, games_by_id, "2025-26", "plays-run-1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["game_id"], "g1")
        self.assertEqual(rows[0]["team_1"], "Foothill")
        self.assertEqual(rows[0]["team_2"], "Monterey Peninsula")

    def test_build_crosswalk_resolution_rows_auto_assigns_other_prefix(self) -> None:
        prefix_rows = [
            {"game_id": "g1", "prefix": "FOOTHILL", "team_1": "Foothill", "team_2": "Monterey Peninsula"},
            {"game_id": "g1", "prefix": "MPC", "team_1": "Foothill", "team_2": "Monterey Peninsula"},
        ]
        rows = build_crosswalk_resolution_rows(
            prefix_rows,
            "2025-26",
            "plays-run-1",
            "g1",
            "MPC",
            "Monterey Peninsula",
        )
        mapping = {row["prefix"]: row["canonical_team"] for row in rows}
        self.assertEqual(mapping["MPC"], "Monterey Peninsula")
        self.assertEqual(mapping["FOOTHILL"], "Foothill")

    def test_build_field_position_rows(self) -> None:
        plays_rows = [
            {
                "game_id": "g1",
                "play_id": 1,
                "field_position": "FOOTHILL25",
                "yardline_raw": 25,
                "offense": "Foothill",
            },
            {
                "game_id": "g1",
                "play_id": 2,
                "field_position": "MPC40",
                "yardline_raw": 40,
                "offense": "Foothill",
            },
        ]
        crosswalk = {("g1", "FOOTHILL"): "Foothill", ("g1", "MPC"): "Monterey Peninsula"}
        rows = build_field_position_rows(plays_rows, crosswalk, "2025-26", "plays-run-1", "field-run-1")
        self.assertEqual(rows[0]["field_pos_side"], "own")
        self.assertEqual(rows[0]["yardline_100"], 75)
        self.assertEqual(rows[1]["field_pos_side"], "opponent")
        self.assertEqual(rows[1]["yardline_100"], 40)


if __name__ == "__main__":
    unittest.main()
