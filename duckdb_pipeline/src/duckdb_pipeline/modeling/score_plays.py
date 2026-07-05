"""Scores plays with the trained xPass / xYards models to compute
``pass_over_expected`` / ``yards_over_expected`` for a season.

Not a pipeline CLI stage -- a small utility for inspecting model output
before deciding whether to wire it into the database as a gold table.

Usage:
    uv run --active python -m duckdb_pipeline.modeling.score_plays --season 2025-26
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import joblib
import pandas as pd

from duckdb_pipeline.modeling.dataset import load_training_rows
from duckdb_pipeline.modeling.features import build_features

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

DISPLAY_COLUMNS = [
    "season",
    "game_id",
    "play_id",
    "offense",
    "down",
    "distance",
    "yardline_100",
    "is_dropback",
    "xpass",
    "pass_over_expected",
    "yards_gained",
    "expected_yards",
    "yards_over_expected",
]


def score_plays(conn: duckdb.DuckDBPyConnection, season: str) -> pd.DataFrame:
    df = load_training_rows(conn, seasons=[season]).copy()
    X = build_features(df)

    xpass_model = joblib.load(ARTIFACTS_DIR / "xpass.joblib")
    xrush_model = joblib.load(ARTIFACTS_DIR / "xyards_rush.joblib")
    xpass_yards_model = joblib.load(ARTIFACTS_DIR / "xyards_pass.joblib")

    df["xpass"] = xpass_model.predict_proba(X)[:, 1]
    df["pass_over_expected"] = df["is_dropback"].astype(int) - df["xpass"]

    df["xrush_yards"] = xrush_model.predict(X)
    df["xpass_yards"] = xpass_yards_model.predict(X)
    df["expected_yards"] = df["xrush_yards"].where(df["is_rush_attempt"], df["xpass_yards"])
    df["yards_over_expected"] = df["yards_gained"] - df["expected_yards"]

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True)
    parser.add_argument("--db-path", default="data/foothill.duckdb")
    parser.add_argument("--out-csv", default=None)
    args = parser.parse_args()

    conn = duckdb.connect(args.db_path, read_only=True)
    scored = score_plays(conn, args.season)
    conn.close()

    print(scored[DISPLAY_COLUMNS].head(20).to_string(index=False))

    if args.out_csv:
        scored.to_csv(args.out_csv, index=False)
        print(f"\nWrote {len(scored)} rows to {args.out_csv}")


if __name__ == "__main__":
    main()
