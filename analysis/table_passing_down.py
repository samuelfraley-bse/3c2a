"""
Passing Down Report — Offense & Defense
Filter: passing_down == True (2nd & 8+, or 3rd/4th & 5+)
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import load_plays, add_flags, build_rankings, ordinal, TEAM

OUT_DIR = "outputs/2025-26/report_tables"
os.makedirs(OUT_DIR, exist_ok=True)


def compute_passing_down(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for team, g in df.groupby(group_col):
        pd_ = g[g["passing_down"]]
        if len(pd_) == 0:
            continue

        passes   = pd_[pd_["play_type"] == "pass"]
        pass_att = passes[~passes["is_sack"]]
        sacks    = passes[passes["is_sack"]]
        rushes   = pd_[pd_["play_type"] == "rush"]
        n        = len(pd_)
        n_pass   = len(pass_att)
        n_rush   = len(rushes)

        rows.append({
            "team":          team,
            "yards_per_play":round(pd_["yards_gained"].mean(), 2),
            "success_rt":    round(pd_["success"].sum() / n * 100, 1) if n else 0,
            "explosive_pct": round(pd_["explosive"].sum() / n * 100, 1) if n else 0,
            "rush_plays":    n_rush,
            "rush_pct":      round(n_rush / n * 100, 1) if n else 0,
            "rush_ypa":      round(rushes["yards_gained"].mean(), 2) if n_rush else 0,
            "run_stuff_pct": round(rushes["run_stuff"].sum() / n_rush * 100, 1) if n_rush else 0,
            "explosive_runs":int(rushes["explosive"].sum()),
            "pass_plays":    n_pass,
            "pass_pct":      round(n_pass / n * 100, 1) if n else 0,
            "pass_ypa":      round(pass_att[pass_att["completion"]]["yards_gained"].sum() / n_pass, 2) if n_pass else 0,
            "comp_pct":      round(pass_att["completion"].sum() / n_pass * 100, 1) if n_pass else 0,
            "sack_pct":      round(len(sacks) / (n_pass + len(sacks)) * 100, 1) if (n_pass + len(sacks)) else 0,
            "turnovers":     int((pass_att["pass_result"] == "int").sum() + pd_["is_fumble"].sum()),
            "penalty_yards": int(pd_["penalty_yards"].fillna(0).sum()),
        })
    return pd.DataFrame(rows)


def add_ranks(df: pd.DataFrame, side: str) -> pd.DataFrame:
    if side == "offense":
        directions = {
            "yards_per_play": "higher_better",
            "success_rt":     "higher_better",
            "explosive_pct":  "higher_better",
            "rush_pct":       "higher_better",
            "rush_ypa":       "higher_better",
            "run_stuff_pct":  "lower_better",
            "explosive_runs": "higher_better",
            "pass_pct":       "higher_better",
            "pass_ypa":       "higher_better",
            "comp_pct":       "higher_better",
            "sack_pct":       "lower_better",
            "turnovers":      "lower_better",
            "penalty_yards":  "lower_better",
        }
    else:
        directions = {
            "yards_per_play": "lower_better",
            "success_rt":     "lower_better",
            "explosive_pct":  "lower_better",
            "rush_pct":       "higher_better",
            "rush_ypa":       "lower_better",
            "run_stuff_pct":  "higher_better",
            "explosive_runs": "lower_better",
            "pass_pct":       "higher_better",
            "pass_ypa":       "lower_better",
            "comp_pct":       "lower_better",
            "sack_pct":       "higher_better",
            "turnovers":      "higher_better",
            "penalty_yards":  "higher_better",
        }
    return build_rankings(df, directions)


METRIC_LABELS = [
    ("yards_per_play", "Yards per Play"),
    ("success_rt",     "Success Rate"),
    ("explosive_pct",  "Explosive %"),
    ("rush_pct",       "% Rush Plays"),
    ("rush_ypa",       "Rush YPA"),
    ("run_stuff_pct",  "Run Stuff %"),
    ("explosive_runs", "Explosive Runs"),
    ("pass_pct",       "% Pass Plays"),
    ("pass_ypa",       "Pass YPA"),
    ("comp_pct",       "Comp %"),
    ("sack_pct",       "Sack %"),
    ("turnovers",      "Turnovers"),
    ("penalty_yards",  "Penalty Yards"),
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
                cnt = COUNT_BACKING[key]
                off_val = f"{int(off[cnt])} ({off[key]}%, {ordinal(off[rank_col])})"
                def_val = f"{int(dff[cnt])} ({dff[key]}%, {ordinal(dff[rank_col])})"
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

    off_stats  = compute_passing_down(df, "offense")
    def_stats  = compute_passing_down(df, "defense")
    off_ranked = add_ranks(off_stats, "offense")
    def_ranked = add_ranks(def_stats, "defense")

    off_ranked.to_csv(f"{OUT_DIR}/passing_down_offense.csv", index=False)
    def_ranked.to_csv(f"{OUT_DIR}/passing_down_defense.csv", index=False)

    report = build_report(off_ranked, def_ranked)
    report.to_csv(f"{OUT_DIR}/passing_down_report.csv", index=False)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
