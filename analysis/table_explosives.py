"""
Explosive Plays Report — Offense & Defense
Filter: explosive == True (pass >= 20 yards, rush >= 10 yards)
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import load_plays, add_flags, build_rankings, ordinal, TEAM

OUT_DIR = "outputs/2025-26/report_tables"
os.makedirs(OUT_DIR, exist_ok=True)


def compute_explosives(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for team, g in df.groupby(group_col):
        n = len(g)
        if n == 0:
            continue

        exp       = g[g["explosive"]]
        passes    = g[g["play_type"] == "pass"]
        pass_att  = passes[~passes["is_sack"]]
        rushes    = g[g["play_type"] == "rush"]
        exp_pass  = exp[exp["play_type"] == "pass"]
        exp_rush  = exp[exp["play_type"] == "rush"]
        exp_ed    = exp[exp["early_down"]]
        exp_third = exp[exp["down"] == 3]

        n_pass = len(pass_att)
        n_rush = len(rushes)

        rows.append({
            "team":           team,
            "total_exp":      len(exp),
            "exp_rate":       round(len(exp) / n * 100, 1),
            "exp_pass":       len(exp_pass),
            "exp_pass_rate":  round(len(exp_pass) / n_pass * 100, 1) if n_pass else 0,
            "exp_rush":       len(exp_rush),
            "exp_rush_rate":  round(len(exp_rush) / n_rush * 100, 1) if n_rush else 0,
            "exp_early_down": len(exp_ed),
            "exp_ed_rate":    round(len(exp_ed) / g["early_down"].sum() * 100, 1) if g["early_down"].sum() else 0,
            "exp_third":      len(exp_third),
            "exp_third_rate": round(len(exp_third) / (g["down"] == 3).sum() * 100, 1) if (g["down"] == 3).sum() else 0,
        })
    return pd.DataFrame(rows)


def add_ranks(df: pd.DataFrame, side: str) -> pd.DataFrame:
    if side == "offense":
        directions = {
            "total_exp":      "higher_better",
            "exp_rate":       "higher_better",
            "exp_pass":       "higher_better",
            "exp_pass_rate":  "higher_better",
            "exp_rush":       "higher_better",
            "exp_rush_rate":  "higher_better",
            "exp_early_down": "higher_better",
            "exp_ed_rate":    "higher_better",
            "exp_third":      "higher_better",
            "exp_third_rate": "higher_better",
        }
    else:
        directions = {
            "total_exp":      "lower_better",
            "exp_rate":       "lower_better",
            "exp_pass":       "lower_better",
            "exp_pass_rate":  "lower_better",
            "exp_rush":       "lower_better",
            "exp_rush_rate":  "lower_better",
            "exp_early_down": "lower_better",
            "exp_ed_rate":    "lower_better",
            "exp_third":      "lower_better",
            "exp_third_rate": "lower_better",
        }
    return build_rankings(df, directions)


METRIC_LABELS = [
    ("total_exp",      "Total Explosives"),
    ("exp_rate",       "Explosive Rate %"),
    ("exp_pass",       "Explosive Passes"),
    ("exp_pass_rate",  "Explosive Pass Rate %"),
    ("exp_rush",       "Explosive Runs"),
    ("exp_rush_rate",  "Explosive Run Rate %"),
    ("exp_early_down", "Explosive Early Downs"),
    ("exp_ed_rate",    "Early Down Exp Rate %"),
    ("exp_third",      "Explosive 3rd Downs"),
    ("exp_third_rate", "3rd Down Exp Rate %"),
]


def build_report(off_ranked: pd.DataFrame, def_ranked: pd.DataFrame) -> pd.DataFrame:
    off = off_ranked[off_ranked["team"] == TEAM].iloc[0]
    dff = def_ranked[def_ranked["team"] == TEAM].iloc[0]
    rows = []
    for key, label in METRIC_LABELS:
        rank_col = f"{key}_rank"
        off_val = f"{off[key]} ({ordinal(off[rank_col])})" if rank_col in off_ranked.columns else str(off[key])
        def_val = f"{dff[key]} ({ordinal(dff[rank_col])})" if rank_col in def_ranked.columns else str(dff[key])
        rows.append({"Offense": off_val, "Metric": label, "Defense": def_val})
    return pd.DataFrame(rows)


def main():
    df = load_plays()
    df = add_flags(df)

    off_stats  = compute_explosives(df, "offense")
    def_stats  = compute_explosives(df, "defense")
    off_ranked = add_ranks(off_stats, "offense")
    def_ranked = add_ranks(def_stats, "defense")

    off_ranked.to_csv(f"{OUT_DIR}/explosives_offense.csv", index=False)
    def_ranked.to_csv(f"{OUT_DIR}/explosives_defense.csv", index=False)

    report = build_report(off_ranked, def_ranked)
    report.to_csv(f"{OUT_DIR}/explosives_report.csv", index=False)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
