"""
Shared helpers for Foothill 2025-26 season report analysis.

Definitions:
  Success rate  — 1st down: yards_gained >= 0.4 * distance
                  2nd down: yards_gained >= 0.6 * distance
                  3rd/4th down: first down or TD (yards_gained >= distance)
  Explosive     — pass >= 20 yards, rush >= 10 yards
  Passing down  — 2nd & 8+, or 3rd/4th & 5+
  Early down    — 1st and 2nd down (that are NOT passing downs)
"""

import pandas as pd

DATA_PATH = "outputs/2025-26/plays.csv"
TEAM = "Foothill"
N_TEAMS = 66  # all CA JC teams in dataset


def load_plays() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    # scrimmage plays only
    df = df[df["play_type"].isin(["rush", "pass"])].copy()
    df["down"] = pd.to_numeric(df["down"], errors="coerce")
    df["distance"] = pd.to_numeric(df["distance"], errors="coerce")
    # down/distance may be null for some plays (e.g. goal-to-go, parse gaps)
    # keep all plays for yardage totals; flag which have down/distance for rate metrics
    df["has_down_distance"] = df["down"].notna() & df["distance"].notna()
    return df


def add_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # success (only meaningful where down/distance are known)
    hdd = df["has_down_distance"]
    first = hdd & (df["down"] == 1)
    second = hdd & (df["down"] == 2)
    third_fourth = hdd & df["down"].isin([3, 4])
    df["success"] = (
        (first & (df["yards_gained"] >= 0.4 * df["distance"]))
        | (second & (df["yards_gained"] >= 0.6 * df["distance"]))
        | (third_fourth & (df["yards_gained"] >= df["distance"]))
    )

    # explosive
    df["explosive"] = (
        ((df["play_type"] == "pass") & (df["yards_gained"] >= 20))
        | ((df["play_type"] == "rush") & (df["yards_gained"] >= 10))
    )

    # passing down: 2nd & 8+, 3rd/4th & 5+
    df["passing_down"] = (
        (hdd & (df["down"] == 2) & (df["distance"] >= 8))
        | (hdd & df["down"].isin([3, 4]) & (df["distance"] >= 5))
    )

    # early down: 1st & 2nd that are not passing downs
    df["early_down"] = hdd & df["down"].isin([1, 2]) & ~df["passing_down"]

    # red zone: opponent side, yardline_100 <= 20
    df["redzone"] = (df["field_pos_side"] == "opponent") & (df["yardline_100"] <= 20)

    # dropback: any play_type='pass' row (pass attempts + sacks)
    # pass attempts = dropbacks where is_sack=False
    # scrambles are indistinguishable from designed runs (both are play_type='rush')
    df["is_dropback"] = df["play_type"] == "pass"

    # completion (pass result)
    df["completion"] = df["pass_result"].isin(["complete", "td"])

    # rush stuff: rush for <= 0 yards
    df["run_stuff"] = (df["play_type"] == "rush") & (df["yards_gained"] <= 0)

    return df


def ordinal(n: int) -> str:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10 if n % 100 not in (11, 12, 13) else 0, "th")
    return f"{n}{suffix}"


def rank_col(series: pd.Series, ascending: bool = True) -> pd.Series:
    """Rank where ascending=True means higher value = better rank (rank 1 = highest value)."""
    return series.rank(ascending=not ascending, method="min").astype(int)


def build_rankings(team_stats: pd.DataFrame, metric_directions: dict) -> pd.DataFrame:
    """
    Add rank columns for each metric.

    metric_directions: {col_name: 'higher_better' | 'lower_better'}
    """
    result = team_stats.copy()
    for col, direction in metric_directions.items():
        if col not in result.columns:
            continue
        ascending_rank = direction == "lower_better"
        result[f"{col}_rank"] = rank_col(result[col], ascending=not ascending_rank)
    return result


def foothill_row(df: pd.DataFrame) -> pd.Series:
    return df[df["team"] == TEAM].iloc[0]
