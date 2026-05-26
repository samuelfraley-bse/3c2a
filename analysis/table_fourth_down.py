"""
4th Down Decision Report — Offense & Defense
Filter: down == 4, scrimmage plays only
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import load_plays, add_flags, build_rankings, ordinal, TEAM

OUT_DIR = "outputs/2025-26/report_tables"
os.makedirs(OUT_DIR, exist_ok=True)


def compute_fourth_down(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for team, g in df.groupby(group_col):
        fourth = g[g["down"] == 4]
        if len(fourth) == 0:
            continue

        passes   = fourth[fourth["play_type"] == "pass"]
        pass_att = passes[~passes["is_sack"]]
        rushes   = fourth[fourth["play_type"] == "rush"]
        n        = len(fourth)
        n_pass   = len(pass_att)
        n_rush   = len(rushes)
        n_conv   = int(fourth["success"].sum())

        rows.append({
            "team":           team,
            "attempts":       n,
            "conv_pct":       round(n_conv / n * 100, 1) if n else 0,
            "rush_plays":     n_rush,
            "rush_pct":       round(n_rush / n * 100, 1) if n else 0,
            "rush_conv_pct":  round(rushes["success"].sum() / n_rush * 100, 1) if n_rush else 0,
            "pass_plays":     n_pass,
            "pass_pct":       round(n_pass / n * 100, 1) if n else 0,
            "pass_conv_pct":  round(pass_att["success"].sum() / n_pass * 100, 1) if n_pass else 0,
            "explosives":     int(fourth["explosive"].sum()),
            "yards_per_play": round(fourth["yards_gained"].mean(), 2),
        })
    return pd.DataFrame(rows)


def add_ranks(df: pd.DataFrame, side: str) -> pd.DataFrame:
    if side == "offense":
        directions = {
            "conv_pct":       "higher_better",
            "rush_pct":       "higher_better",
            "rush_conv_pct":  "higher_better",
            "pass_pct":       "higher_better",
            "pass_conv_pct":  "higher_better",
            "explosives":     "higher_better",
            "yards_per_play": "higher_better",
        }
    else:
        directions = {
            "conv_pct":       "lower_better",
            "rush_conv_pct":  "lower_better",
            "pass_conv_pct":  "lower_better",
            "explosives":     "lower_better",
            "yards_per_play": "lower_better",
        }
    return build_rankings(df, directions)


METRIC_LABELS = [
    ("attempts",      "Attempts"),
    ("conv_pct",      "Conversion %"),
    ("yards_per_play","Yards per Play"),
    ("explosives",    "Explosive Plays"),
    ("rush_pct",      "% Rush Plays"),
    ("rush_conv_pct", "Rush Conversion %"),
    ("pass_pct",      "% Pass Plays"),
    ("pass_conv_pct", "Pass Conversion %"),
]

COUNT_BACKING = {"rush_pct": "rush_plays", "pass_pct": "pass_plays"}


def build_report(off_ranked: pd.DataFrame, def_ranked: pd.DataFrame) -> pd.DataFrame:
    off = off_ranked[off_ranked["team"] == TEAM].iloc[0]
    dff = def_ranked[def_ranked["team"] == TEAM].iloc[0]
    rows = []
    for key, label in METRIC_LABELS:
        rank_col = f"{key}_rank"
        if key in COUNT_BACKING:
            cnt = COUNT_BACKING[key]
            off_val = f"{int(off[cnt])} ({off[key]}%, {ordinal(off[rank_col])})" if rank_col in off_ranked.columns else f"{int(off[cnt])} ({off[key]}%)"
            def_val = f"{int(dff[cnt])} ({dff[key]}%, {ordinal(dff[rank_col])})" if rank_col in def_ranked.columns else f"{int(dff[cnt])} ({dff[key]}%)"
        elif rank_col in off_ranked.columns or rank_col in def_ranked.columns:
            off_val = f"{off[key]} ({ordinal(off[rank_col])})" if rank_col in off_ranked.columns else str(off[key])
            def_val = f"{dff[key]} ({ordinal(dff[rank_col])})" if rank_col in def_ranked.columns else str(dff[key])
        else:
            off_val = str(off[key])
            def_val = str(dff[key])
        rows.append({"Offense": off_val, "Metric": label, "Defense": def_val})
    return pd.DataFrame(rows)


def main():
    df = load_plays()
    df = add_flags(df)
    df = df[df["has_down_distance"]].copy()

    off_stats  = compute_fourth_down(df, "offense")
    def_stats  = compute_fourth_down(df, "defense")
    off_ranked = add_ranks(off_stats, "offense")
    def_ranked = add_ranks(def_stats, "defense")

    off_ranked.to_csv(f"{OUT_DIR}/fourth_down_offense.csv", index=False)
    def_ranked.to_csv(f"{OUT_DIR}/fourth_down_defense.csv", index=False)

    report = build_report(off_ranked, def_ranked)
    report.to_csv(f"{OUT_DIR}/fourth_down_report.csv", index=False)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
