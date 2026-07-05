"""Deterministic unit tests for duckdb_pipeline.modeling.splits.

Training scripts themselves aren't unit-tested here (slow/stochastic
against real data) -- these tests cover the pure, deterministic split
logic that every training script depends on for honest evaluation.
"""

import unittest

import pandas as pd

from duckdb_pipeline.modeling.splits import leave_one_season_out, team_group_kfold


class LeaveOneSeasonOutTests(unittest.TestCase):
    def test_partitions_each_season_as_the_held_out_test_set(self):
        df = pd.DataFrame(
            {
                "season": [
                    "2023-24",
                    "2023-24",
                    "2024-25",
                    "2024-25",
                    "2025-26",
                    "2025-26",
                ],
            }
        )

        seen_seasons = set()
        for train_idx, test_idx, held_out_season in leave_one_season_out(df):
            seen_seasons.add(held_out_season)
            test_seasons = set(df.iloc[test_idx]["season"])
            train_seasons = set(df.iloc[train_idx]["season"])

            self.assertEqual(test_seasons, {held_out_season})
            self.assertNotIn(held_out_season, train_seasons)
            self.assertEqual(len(train_idx) + len(test_idx), len(df))

        self.assertEqual(seen_seasons, {"2023-24", "2024-25", "2025-26"})


class TeamGroupKFoldTests(unittest.TestCase):
    @staticmethod
    def _make_frame():
        # 4 teams, 10 rows each, alternating a binary target so
        # StratifiedGroupKFold has something to balance across folds.
        rows = [
            {"team": f"team_{team_idx}", "y": row_idx % 2}
            for team_idx in range(4)
            for row_idx in range(10)
        ]
        return pd.DataFrame(rows)

    def test_group_kfold_never_splits_a_team_across_train_and_validation(self):
        df = self._make_frame()
        X = df[["y"]]
        y = df["y"]
        groups = df["team"]

        fold_count = 0
        for train_idx, val_idx in team_group_kfold(X, y, groups, n_splits=4, stratify=False):
            fold_count += 1
            train_teams = set(groups.iloc[train_idx])
            val_teams = set(groups.iloc[val_idx])
            self.assertEqual(train_teams & val_teams, set())
        self.assertEqual(fold_count, 4)

    def test_stratified_group_kfold_also_respects_team_boundaries(self):
        df = self._make_frame()
        X = df[["y"]]
        y = df["y"]
        groups = df["team"]

        fold_count = 0
        for train_idx, val_idx in team_group_kfold(X, y, groups, n_splits=4, stratify=True):
            fold_count += 1
            train_teams = set(groups.iloc[train_idx])
            val_teams = set(groups.iloc[val_idx])
            self.assertEqual(train_teams & val_teams, set())
        self.assertEqual(fold_count, 4)


if __name__ == "__main__":
    unittest.main()
