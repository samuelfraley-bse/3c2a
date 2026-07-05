"""Loads training rows for the xPass / xYards models from
``v_play_context_current`` -- the sole data source for this modeling layer.
"""

from __future__ import annotations

import duckdb
import pandas as pd

REQUIRED_COLUMNS = [
    "season",
    "game_id",
    "play_id",
    "offense",
    "down",
    "distance",
    "yardline_100",
    "score_margin",
    "quarter",
    "home_away",
    "week",
    "is_dropback",
    "is_rush_attempt",
    "is_sack",
    "yards_gained",
]


def load_training_rows(
    conn: duckdb.DuckDBPyConnection, seasons: list[str] | None = None
) -> pd.DataFrame:
    """Returns one row per scrimmage play (pass or run), with every column
    the xPass/xYards models need.

    Drops any row with a NULL in a required column. This also naturally
    removes downless plays (2-point conversion tries have no ``down``)
    without a special-case filter -- those are a different strategic
    context and shouldn't be in this population anyway.
    """
    where_clauses = ["(is_dropback OR is_rush_attempt)"]
    params: list[str] = []
    if seasons:
        placeholders = ", ".join("?" for _ in seasons)
        where_clauses.append(f"season IN ({placeholders})")
        params.extend(seasons)

    query = f"""
        SELECT {", ".join(REQUIRED_COLUMNS)}
        FROM v_play_context_current
        WHERE {" AND ".join(where_clauses)}
    """
    df = conn.execute(query, params).df()
    return df.dropna(subset=REQUIRED_COLUMNS).reset_index(drop=True)
