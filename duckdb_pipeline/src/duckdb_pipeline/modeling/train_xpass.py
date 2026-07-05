"""Trains the xPass model: P(offense calls a pass), including sacks.

Target is ``is_dropback`` (pass-play context, including sacks), not
``is_pass_attempt`` (official forward pass attempts only) -- a
play-calling model needs to predict the call, not the official outcome.
A sack is a called pass that went wrong; training on ``is_pass_attempt``
would miscode every sack as a "run".

The classifier's ``predict_proba`` covers both directions: P(pass), and by
complement P(run) = 1 - P(pass). No separate "run" model is needed.

Usage:
    uv run --active python -m duckdb_pipeline.modeling.train_xpass
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from duckdb_pipeline.modeling.dataset import load_training_rows
from duckdb_pipeline.modeling.features import build_features
from duckdb_pipeline.modeling.splits import leave_one_season_out, team_group_kfold

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

TARGET_COLUMN = "is_dropback"


def _fit(X_train, y_train) -> HistGradientBoostingClassifier:
    model = HistGradientBoostingClassifier(random_state=0)
    model.fit(X_train, y_train)
    return model


def _score(model, X, y) -> dict[str, float]:
    proba = model.predict_proba(X)[:, 1]
    return {
        "auc": roc_auc_score(y, proba),
        "log_loss": log_loss(y, proba, labels=[0, 1]),
        "brier": brier_score_loss(y, proba),
    }


def evaluate_unseen_team(df, n_splits: int = 5) -> dict[str, float]:
    """Team-grouped CV within seasons the model has already seen -- does
    it generalize to a team it hasn't seen?"""
    X = build_features(df)
    y = df[TARGET_COLUMN].astype(int)
    groups = df["offense"]
    fold_metrics = []
    for train_idx, val_idx in team_group_kfold(X, y, groups, n_splits=n_splits, stratify=True):
        model = _fit(X.iloc[train_idx], y.iloc[train_idx])
        fold_metrics.append(_score(model, X.iloc[val_idx], y.iloc[val_idx]))
    return {key: float(np.mean([m[key] for m in fold_metrics])) for key in fold_metrics[0]}


def evaluate_unseen_season(df) -> dict[str, dict[str, float]]:
    """Leave-one-season-out -- does it generalize to a year it hasn't
    seen?"""
    results: dict[str, dict[str, float]] = {}
    for train_idx, test_idx, held_out_season in leave_one_season_out(df):
        train_df, test_df = df.iloc[train_idx], df.iloc[test_idx]
        model = _fit(build_features(train_df), train_df[TARGET_COLUMN].astype(int))
        results[held_out_season] = _score(
            model, build_features(test_df), test_df[TARGET_COLUMN].astype(int)
        )
    return results


def train_final_model(df) -> HistGradientBoostingClassifier:
    return _fit(build_features(df), df[TARGET_COLUMN].astype(int))


def _print_metrics(label: str, metrics: dict[str, float]) -> None:
    print("  " + label + ": " + ", ".join(f"{k}={v:.4f}" for k, v in metrics.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="data/foothill.duckdb")
    args = parser.parse_args()

    conn = duckdb.connect(args.db_path, read_only=True)
    df = load_training_rows(conn)
    conn.close()

    print(f"Loaded {len(df)} scrimmage plays across seasons: {sorted(df['season'].unique())}")

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
    out_path = ARTIFACTS_DIR / "xpass.joblib"
    joblib.dump(model, out_path)
    print(f"\nSaved final model (trained on all seasons) to {out_path}")


if __name__ == "__main__":
    main()
