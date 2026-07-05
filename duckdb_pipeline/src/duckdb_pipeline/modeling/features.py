"""Feature definitions shared by training and inference.

Pre-snap only -- never add a column here that isn't known before the ball
is snapped, and never add team/opponent identity. These models exist to
measure deviation from a team-agnostic baseline (pass/run-over-expected,
yards-over-expected); adding team identity as a feature would let the
model partially memorize each team's own tendency, quietly deflating the
over-expected signal these models exist to produce.

``field_zone`` / ``is_passing_down`` / ``is_early_down`` are deliberately
excluded too -- each is a bucketed function of columns already below
(``yardline_100``; ``down`` + ``distance``), and a tree ensemble finds
equivalent, often better, data-driven split points on its own.
"""

from __future__ import annotations

import pandas as pd

FEATURE_COLUMNS = [
    "down",
    "distance",
    "yardline_100",
    "score_margin",
    "quarter",
    "is_home",
    "week",
]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Returns the model-ready feature matrix from a dataframe produced by
    ``dataset.load_training_rows``."""
    features = df[["down", "distance", "yardline_100", "score_margin", "quarter", "week"]].copy()
    features["is_home"] = (df["home_away"] == "home").astype(int)
    return features[FEATURE_COLUMNS]
