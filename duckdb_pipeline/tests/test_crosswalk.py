import unittest

from duckdb_pipeline.crosswalk import (
    build_memory_seed_rows,
    build_team_prefix_memory,
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

    def test_build_team_prefix_memory_keeps_multiple_prefixes_per_team(self) -> None:
        crosswalk_rows = [
            {"prefix": "LANEY", "canonical_team": "Laney"},
            {"prefix": "EAGLES", "canonical_team": "Laney"},
            {"prefix": "MT. SAN", "canonical_team": "Mt. San Antonio"},
            {"prefix": "MT. SAN", "canonical_team": "Mt. San Jacinto"},
        ]
        memory = build_team_prefix_memory(crosswalk_rows)
        self.assertEqual(memory["Laney"], {"LANEY", "EAGLES"})
        self.assertEqual(memory["Mt. San Antonio"], {"MT. SAN"})
        self.assertEqual(memory["Mt. San Jacinto"], {"MT. SAN"})

    def test_build_memory_seed_rows_auto_seeds_from_team_prefix_memory(self) -> None:
        prefix_rows = [
            {"game_id": "g1", "prefix": "LANEY", "team_1": "Laney", "team_2": "Butte"},
            {"game_id": "g1", "prefix": "BUTTE", "team_1": "Laney", "team_2": "Butte"},
        ]
        rows = build_memory_seed_rows(
            prefix_rows,
            {"Laney": {"LANEY"}},
            "2025-26",
            "plays-run-2",
        )
        mapping = {row["prefix"]: row["canonical_team"] for row in rows}
        self.assertEqual(mapping["LANEY"], "Laney")
        self.assertEqual(mapping["BUTTE"], "Butte")
        methods = {row["resolution_method"] for row in rows}
        self.assertEqual(methods, {"auto-memory"})

    def test_build_memory_seed_rows_skips_prefix_not_in_current_game_context(self) -> None:
        prefix_rows = [
            {"game_id": "g1", "prefix": "MER", "team_1": "Laney", "team_2": "Butte"},
            {"game_id": "g1", "prefix": "BUTTE", "team_1": "Laney", "team_2": "Butte"},
        ]
        rows = build_memory_seed_rows(
            prefix_rows,
            {"Merced": {"MER"}},
            "2025-26",
            "plays-run-2",
        )
        self.assertEqual(rows, [])

    def test_build_memory_seed_rows_allows_shared_prefix_for_different_schools(self) -> None:
        prefix_rows = [
            {"game_id": "g1", "prefix": "MT. SAN", "team_1": "Mt. San Antonio", "team_2": "San Diego Mesa"},
            {"game_id": "g1", "prefix": "SAN DIEG", "team_1": "Mt. San Antonio", "team_2": "San Diego Mesa"},
        ]
        rows = build_memory_seed_rows(
            prefix_rows,
            {
                "Mt. San Antonio": {"MT. SAN"},
                "Mt. San Jacinto": {"MT. SAN"},
            },
            "2025-26",
            "plays-run-2",
        )
        mapping = {row["prefix"]: row["canonical_team"] for row in rows}
        self.assertEqual(mapping["MT. SAN"], "Mt. San Antonio")
        self.assertEqual(mapping["SAN DIEG"], "San Diego Mesa")


if __name__ == "__main__":
    unittest.main()
