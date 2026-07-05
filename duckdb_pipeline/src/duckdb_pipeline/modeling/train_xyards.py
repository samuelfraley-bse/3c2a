"""Trains the xYards model: expected ``yards_gained`` for a given play
type, evaluated separately for rush and pass.

The pass-type population is deliberately the same ``is_dropback`` rows
used as xPass's positive class -- sacks (negative yards_gained) and
incompletions (0) stay in, not filtered out. Excluding sacks would make
this model operate over a different population than xPass's positive
class, breaking composability if these are ever combined into one
"expected yards this play" number. A team that gets sacked more should
show a lower expected passing value; that's the model being honest about
the real cost of calling a pass, not noise to strip out.

Usage:
    uv run --active python -m duckdb_pipeline.modeling.train_xyards --play-type rush
    uv run --active python -m duckdb_pipeline.modeling.train_xyards --play-type pass
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from duckdb_pipeline.modeling.dataset import load_training_rows
from duckdb_pipeline.modeling.features import build_features
from duckdb_pipeline.modeling.splits import leave_one_season_out, team_group_kfold

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

TARGET_COLUMN = "yards_gained"

PLAY_TYPES = ("rush", "pass")


def rows_for_play_type(df, play_type: str):
    if play_type == "rush":
        # is_rush_attempt deliberately includes sacks elsewhere in this
        # project (the dashboard's pass_pct/rush_pct scrimmage-play
        # denominator convention -- see METRICS.md). That convention
        # doesn't belong here: a sack is a pass-blocking/pass-rush
        # outcome, not a designed-run outcome, so it must be excluded from
        # the rush-yards training population or it silently understates
        # expected rushing yards for teams sacked more often.
        return df[df["is_rush_attempt"] & ~df["is_sack"]].reset_index(drop=True)
    return df[df["is_dropback"]].reset_index(drop=True)


def _fit(X_train, y_train) -> HistGradientBoostingRegressor:
    model = HistGradientBoostingRegressor(random_state=0)
    model.fit(X_train, y_train)
    return model


def _score(model, X, y) -> dict[str, float]:
    preds = model.predict(X)
    return {
        "mae": mean_absolute_error(y, preds),
        "rmse": mean_squared_error(y, preds) ** 0.5,
    }


def evaluate_unseen_team(df, n_splits: int = 5) -> dict[str, float]:
    """Team-grouped CV within seasons the model has already seen -- does
    it generalize to a team it hasn't seen?"""
    X = build_features(df)
    y = df[TARGET_COLUMN].astype(float)
    groups = df["offense"]
    fold_metrics = []
    for train_idx, val_idx in team_group_kfold(X, y, groups, n_splits=n_splits, stratify=False):
        model = _fit(X.iloc[train_idx], y.iloc[train_idx])
        fold_metrics.append(_score(model, X.iloc[val_idx], y.iloc[val_idx]))
    return {key: float(np.mean([m[key] for m in fold_metrics])) for key in fold_metrics[0]}


def evaluate_unseen_season(df) -> dict[str, dict[str, float]]:
    """Leave-one-season-out -- does it generalize to a year it hasn't
    seen?"""
    results: dict[str, dict[str, float]] = {}
    for train_idx, test_idx, held_out_season in leave_one_season_out(df):
        train_df, test_df = df.iloc[train_idx], df.iloc[test_idx]
        model = _fit(build_features(train_df), train_df[TARGET_COLUMN].astype(float))
        results[held_out_season] = _score(
            model, build_features(test_df), test_df[TARGET_COLUMN].astype(float)
        )
    return results


def train_final_model(df) -> HistGradientBoostingRegressor:
    return _fit(build_features(df), df[TARGET_COLUMN].astype(float))


def _print_metrics(label: str, metrics: dict[str, float]) -> None:
    print("  " + label + ": " + ", ".join(f"{k}={v:.4f}" for k, v in metrics.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--play-type", choices=sorted(PLAY_TYPES), required=True)
    parser.add_argument("--db-path", default="data/foothill.duckdb")
    args = parser.parse_args()

    conn = duckdb.connect(args.db_path, read_only=True)
    df = load_training_rows(conn)
    conn.close()

    df = rows_for_play_type(df, args.play_type)
    print(f"Loaded {len(df)} {args.play_type} plays across seasons: {sorted(df['season'].unique())}")

    print("\n=== Unseen-team check (team-grouped CV within seasons) ===")
    _print_metrics("average across team folds", evaluate_unseen_team(df))

    print("\n=== Unseen-season check (leave-one-season-out) ===")
    season_metrics = evaluate_unseen_season(df)
    for season, metrics in season_metrics.items():
        _print_metrics(f"held out {season}", metrics)
    avg = {
        key: float(np.mean([m[key] for m in season_metrics.values()]))
        for key in next(iter(season_metrics.values()))
    }
    _print_metrics("average across seasons", avg)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    model = train_final_model(df)
    out_path = ARTIFACTS_DIR / f"xyards_{args.play_type}.joblib"
    joblib.dump(model, out_path)
    print(f"\nSaved final model (trained on all seasons) to {out_path}")


if __name__ == "__main__":
    main()
