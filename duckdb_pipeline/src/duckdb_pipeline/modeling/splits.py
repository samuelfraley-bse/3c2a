"""CV splitting helpers shared by both training scripts.

Two distinct diagnostics, kept separate rather than blended into one CV
loop -- this mirrors the two-part question "does this generalize to a team
or a year it hasn't seen":

- ``leave_one_season_out``: does the model generalize to a season it has
  never seen?
- ``team_group_kfold``: does the model generalize to a team it has never
  seen, within seasons it has already seen?
"""

from __future__ import annotations

from typing import Iterator

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, StratifiedGroupKFold


def leave_one_season_out(
    df: pd.DataFrame,
) -> Iterator[tuple[np.ndarray, np.ndarray, str]]:
    """Yields (train_idx, test_idx, held_out_season) for each unique value
    of ``df["season"]``, training on every other season."""
    seasons = sorted(df["season"].unique())
    for held_out in seasons:
        is_held_out = (df["season"] == held_out).to_numpy()
        test_idx = np.flatnonzero(is_held_out)
        train_idx = np.flatnonzero(~is_held_out)
        yield train_idx, test_idx, held_out


def team_group_kfold(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    n_splits: int = 5,
    stratify: bool = False,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Wraps GroupKFold / StratifiedGroupKFold so a team's rows are never
    split across train/validation within a fold.

    ``stratify=True`` also balances class distribution across folds --
    classification only. Pass ``stratify=False`` for regression targets,
    where stratification doesn't apply.
    """
    if stratify:
        splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=0)
    else:
        splitter = GroupKFold(n_splits=n_splits)
    yield from splitter.split(X, y, groups=groups)
