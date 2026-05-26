"""
Third Down Report — Offense & Defense
Filter: down == 3, scrimmage plays only
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import load_plays, add_flags, build_rankings, ordinal, TEAM

OUT_DIR = "outputs/2025-26/report_tables"
os.makedirs(OUT_DIR, exist_ok=True)


def compute_third_down(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for team, g in df.groupby(group_col):
        third = g[g["down"] == 3]
        if len(third) == 0:
            continue

        passes    = third[third["play_type"] == "pass"]
        pass_att  = passes[~passes["is_sack"]]
        sacks     = passes[passes["is_sack"]]
        rushes    = third[third["play_type"] == "rush"]
        convs     = third[third["success"]]

        n         = len(third)
        n_conv    = len(convs)
        n_pass    = len(pass_att)
        n_sack    = len(sacks)
        n_rush    = len(rushes)

        rows.append({
            "team":          team,
            "attempts":      n,
            "conversions":   n_conv,
            "conv_pct":      round(n_conv / n * 100, 1) if n else 0,
            "avg_distance":  round(third["distance"].mean(), 1),
            "pct_long":      round((third["distance"] >= 7).sum() / n * 100, 1) if n else 0,
            "pct_short":     round((third["distance"] < 3).sum() / n * 100, 1) if n else 0,
            "yards_per_play":round(third["yards_gained"].mean(), 2),
            "explosives":    int(third["explosive"].sum()),
            "rush_plays":    n_rush,
            "pass_plays":    n_pass,
            "rush_pct":      round(n_rush / n * 100, 1) if n else 0,
            "pass_pct":      round(n_pass / n * 100, 1) if n else 0,
            "rush_conv_pct": round(rushes["success"].sum() / n_rush * 100, 1) if n_rush else 0,
            "pass_conv_pct": round(pass_att["success"].sum() / n_pass * 100, 1) if n_pass else 0,
            "sack_pct":      round(n_sack / (n_pass + n_sack) * 100, 1) if (n_pass + n_sack) else 0,
            "turnovers":     int((third["pass_result"] == "int").sum() + (third["is_fumble"] & (third["fumble_recovered_by"] != third[group_col])).sum()),
            "penalty_yards": int(third["penalty_yards"].fillna(0).sum()),
        })
    return pd.DataFrame(rows)


def add_ranks(df: pd.DataFrame, side: str) -> pd.DataFrame:
    if side == "offense":
        directions = {
            "conv_pct":       "higher_better",
            "avg_distance":   "lower_better",
            "pct_long":       "lower_better",
            "pct_short":      "higher_better",
            "yards_per_play": "higher_better",
            "explosives":     "higher_better",
            "rush_pct":       "higher_better",
            "pass_pct":       "higher_better",
            "rush_conv_pct":  "higher_better",
            "pass_conv_pct":  "higher_better",
            "sack_pct":       "lower_better",
            "turnovers":      "lower_better",
            "penalty_yards":  "lower_better",
        }
    else:
        directions = {
            "conv_pct":       "lower_better",
            "avg_distance":   "higher_better",
            "pct_long":       "higher_better",
            "pct_short":      "lower_better",
            "yards_per_play": "lower_better",
            "explosives":     "lower_better",
            "rush_pct":       "lower_better",
            "pass_pct":       "higher_better",
            "rush_conv_pct":  "lower_better",
            "pass_conv_pct":  "lower_better",
            "sack_pct":       "higher_better",
            "turnovers":      "higher_better",
            "penalty_yards":  "higher_better",
        }
    return build_rankings(df, directions)


METRIC_LABELS = [
    ("attempts",      "Attempts"),
    ("conversions",   "Conversions"),
    ("conv_pct",      "Conversion %"),
    ("avg_distance",  "Avg Yards to Go"),
    ("pct_long",      "% 3rd & Long (7+)"),
    ("pct_short",     "% 3rd & Short (<3)"),
    ("yards_per_play","Yards per Play"),
    ("explosives",    "Explosive Plays"),
    ("rush_pct",      "% Rush Plays"),
    ("pass_pct",      "% Pass Plays"),
    ("rush_conv_pct", "Rush Conversion %"),
    ("pass_conv_pct", "Pass Conversion %"),
    ("sack_pct",      "Sack %"),
    ("turnovers",     "Turnovers"),
    ("penalty_yards", "Penalty Yards"),
]


COUNT_BACKING = {"rush_pct": "rush_plays", "pass_pct": "pass_plays"}


def build_report(off_ranked: pd.DataFrame, def_ranked: pd.DataFrame) -> pd.DataFrame:
    off = off_ranked[off_ranked["team"] == TEAM].iloc[0]
    dff = def_ranked[def_ranked["team"] == TEAM].iloc[0]
    rows = []
    for key, label in METRIC_LABELS:
        rank_col = f"{key}_rank"
        if rank_col in off_ranked.columns:
            if key in COUNT_BACKING:
                cnt_col = COUNT_BACKING[key]
                off_val = f"{int(off[cnt_col])} ({off[key]}%, {ordinal(off[rank_col])})"
                def_val = f"{int(dff[cnt_col])} ({dff[key]}%, {ordinal(dff[rank_col])})"
            else:
                off_val = f"{off[key]} ({ordinal(off[rank_col])})"
                def_val = f"{dff[key]} ({ordinal(dff[rank_col])})"
        else:
            off_val = str(off[key])
            def_val = str(dff[key])
        rows.append({"Offense": off_val, "Metric": label, "Defense": def_val})
    return pd.DataFrame(rows)


def main():
    df = load_plays()
    df = add_flags(df)
    # third down requires known down/distance
    df = df[df["has_down_distance"]].copy()

    off_stats  = compute_third_down(df, "offense")
    def_stats  = compute_third_down(df, "defense")
    off_ranked = add_ranks(off_stats, "offense")
    def_ranked = add_ranks(def_stats, "defense")

    off_ranked.to_csv(f"{OUT_DIR}/third_down_offense.csv", index=False)
    def_ranked.to_csv(f"{OUT_DIR}/third_down_defense.csv", index=False)

    report = build_report(off_ranked, def_ranked)
    report.to_csv(f"{OUT_DIR}/third_down_report.csv", index=False)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
