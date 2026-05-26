"""
Finishing Drives Report — Offense & Defense
Drive-level aggregation: scoring rate, TD rate, three-and-out rate, avg starting pos.
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import build_rankings, ordinal, TEAM

OUT_DIR = "outputs/2025-26/report_tables"
os.makedirs(OUT_DIR, exist_ok=True)

DATA_PATH = "outputs/2025-26/plays.csv"


def build_drive_summary(df_all: pd.DataFrame) -> pd.DataFrame:
    """One row per (game_id, drive_id, offense). Requires all play types."""
    valid = df_all[df_all["drive_id"].notna() & (df_all["drive_id"].astype(str) != "0")].copy()

    fg_drives = set(
        zip(
            valid[(valid["play_type"] == "field_goal") & (valid["fg_result"] == "good")]["game_id"],
            valid[(valid["play_type"] == "field_goal") & (valid["fg_result"] == "good")]["drive_id"],
        )
    )

    scrimmage = valid[valid["play_type"].isin(["rush", "pass"])]

    agg = (
        scrimmage.groupby(["game_id", "drive_id", "offense", "defense"])
        .agg(
            plays=("play_id", "count"),
            td=("is_td", "any"),
            start_yardline=("yardline_100", "first"),
        )
        .reset_index()
    )

    agg["fg"] = agg.apply(lambda r: (r["game_id"], r["drive_id"]) in fg_drives, axis=1)
    agg["score"] = agg["td"] | agg["fg"]
    agg["three_out"] = (agg["plays"] <= 3) & ~agg["score"]
    agg["points"] = agg["td"].apply(lambda x: 7 if x else 0) + agg["fg"].apply(lambda x: 3 if x else 0)

    return agg


def compute_finishing_drives(drives: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for team, g in drives.groupby(group_col):
        n = len(g)
        if n == 0:
            continue
        n_score    = g["score"].sum()
        n_td       = g["td"].sum()
        n_fg       = g["fg"].sum()
        n_three    = g["three_out"].sum()
        start_pos  = g["start_yardline"].dropna()
        avg_plays  = g["plays"].mean()
        pts_drive  = g["points"].mean()

        rows.append({
            "team":          team,
            "drives":        n,
            "scoring_rate":  round(n_score / n * 100, 1),
            "td_rate":       round(n_td / n * 100, 1),
            "fg_rate":       round(n_fg / n * 100, 1),
            "three_out_rate":round(n_three / n * 100, 1),
            "avg_start_pos": round(start_pos.mean(), 1) if len(start_pos) else 0,
            "avg_plays":     round(avg_plays, 2),
            "pts_per_drive": round(pts_drive, 2),
        })
    return pd.DataFrame(rows)


def add_ranks(df: pd.DataFrame, side: str) -> pd.DataFrame:
    if side == "offense":
        directions = {
            "scoring_rate":   "higher_better",
            "td_rate":        "higher_better",
            "fg_rate":        "higher_better",
            "three_out_rate": "lower_better",
            "avg_start_pos":  "lower_better",
            "avg_plays":      "higher_better",
            "pts_per_drive":  "higher_better",
        }
    else:
        directions = {
            "scoring_rate":   "lower_better",
            "td_rate":        "lower_better",
            "fg_rate":        "lower_better",
            "three_out_rate": "higher_better",
            "avg_start_pos":  "higher_better",
            "avg_plays":      "lower_better",
            "pts_per_drive":  "lower_better",
        }
    return build_rankings(df, directions)


METRIC_LABELS = [
    ("drives",        "Total Drives"),
    ("pts_per_drive", "Points per Drive"),
    ("scoring_rate",  "Scoring Rate %"),
    ("td_rate",       "TD Rate %"),
    ("fg_rate",       "FG Rate %"),
    ("three_out_rate","Three-and-Out %"),
    ("avg_start_pos", "Avg Starting Position"),
    ("avg_plays",     "Avg Plays per Drive"),
]


def format_field_pos(yardline_100: float) -> str:
    y = round(yardline_100)
    if y > 50:
        return f"OWN {100 - y}"
    elif y < 50:
        return f"OPP {y}"
    else:
        return "50"


def build_report(off_ranked: pd.DataFrame, def_ranked: pd.DataFrame) -> pd.DataFrame:
    off = off_ranked[off_ranked["team"] == TEAM].iloc[0]
    dff = def_ranked[def_ranked["team"] == TEAM].iloc[0]
    rows = []
    for key, label in METRIC_LABELS:
        rank_col = f"{key}_rank"
        if key == "avg_start_pos":
            off_fp = format_field_pos(off[key])
            def_fp = format_field_pos(100 - dff[key])  # defense perspective: flip to Foothill's field
            off_val = f"{off_fp} ({ordinal(off[rank_col])})" if rank_col in off_ranked.columns else off_fp
            def_val = f"{def_fp} ({ordinal(dff[rank_col])})" if rank_col in def_ranked.columns else def_fp
        else:
            off_val = f"{off[key]} ({ordinal(off[rank_col])})" if rank_col in off_ranked.columns else str(off[key])
            def_val = f"{dff[key]} ({ordinal(dff[rank_col])})" if rank_col in def_ranked.columns else str(dff[key])
        rows.append({"Offense": off_val, "Metric": label, "Defense": def_val})
    return pd.DataFrame(rows)


def main():
    df_all = pd.read_csv(DATA_PATH)
    drives = build_drive_summary(df_all)

    off_stats  = compute_finishing_drives(drives, "offense")
    def_stats  = compute_finishing_drives(drives, "defense")
    off_ranked = add_ranks(off_stats, "offense")
    def_ranked = add_ranks(def_stats, "defense")

    off_ranked.to_csv(f"{OUT_DIR}/finishing_drives_offense.csv", index=False)
    def_ranked.to_csv(f"{OUT_DIR}/finishing_drives_defense.csv", index=False)

    report = build_report(off_ranked, def_ranked)
    report.to_csv(f"{OUT_DIR}/finishing_drives_report.csv", index=False)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
