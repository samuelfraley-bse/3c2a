"""
Production Stats table — Offense & Defense
Metrics per team (offense role and defense role separately):
  Passing: % plays pass, total yards, YPA, TD, comp%, 10+ completions, 20+ completions, success rate
  Rushing: % plays run, total yards, YPA, TD, 10+ rushes, 20+ rushes, success rate
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import load_plays, add_flags, build_rankings, ordinal, TEAM

OUT_DIR = "outputs/2025-26/report_tables"
os.makedirs(OUT_DIR, exist_ok=True)


def compute_production(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for team, g in df.groupby(group_col):
        dropbacks  = g[g["play_type"] == "pass"]
        pass_att   = dropbacks[~dropbacks["is_sack"]]
        sacks      = dropbacks[dropbacks["is_sack"]]
        rushes     = g[g["play_type"] == "rush"]
        # NCAA convention: sacks count as rush attempts with negative yards
        rush_all   = pd.concat([rushes, sacks])
        total      = len(g)

        pass_yards = pass_att[pass_att["completion"]]["yards_gained"].sum()
        rush_yards = rush_all["yards_gained"].sum()
        n_pass_att = len(pass_att)
        n_rush_att = len(rush_all)

        rows.append({
            "team": team,
            # passing
            "pass_pct":        round(len(dropbacks) / total * 100, 1) if total else 0,
            "pass_yards":      int(pass_yards),
            "pass_ypa":        round(pass_yards / n_pass_att, 2) if n_pass_att else 0,
            "pass_td":         int(pass_att["is_td"].sum()),
            "comp_pct":        round(pass_att["completion"].sum() / n_pass_att * 100, 1) if n_pass_att else 0,
            "pass_10plus":     int((pass_att[pass_att["completion"]]["yards_gained"] >= 10).sum()),
            "pass_20plus":     int((pass_att[pass_att["completion"]]["yards_gained"] >= 20).sum()),
            "pass_success_rt": round(pass_att["success"].sum() / n_pass_att * 100, 1) if n_pass_att else 0,
            # rushing (includes sacks per NCAA convention)
            "rush_pct":        round(n_rush_att / total * 100, 1) if total else 0,
            "rush_yards":      int(rush_yards),
            "rush_ypa":        round(rush_yards / n_rush_att, 2) if n_rush_att else 0,
            "rush_td":         int(rushes["is_td"].sum()),
            "rush_10plus":     int((rushes["yards_gained"] >= 10).sum()),
            "rush_20plus":     int((rushes["yards_gained"] >= 20).sum()),
            "rush_success_rt": round(rushes["success"].sum() / len(rushes) * 100, 1) if len(rushes) else 0,
        })
    return pd.DataFrame(rows)


def add_ranks(df: pd.DataFrame, side: str) -> pd.DataFrame:
    if side == "offense":
        directions = {
            "pass_pct":        "higher_better",
            "pass_yards":      "higher_better",
            "pass_ypa":        "higher_better",
            "pass_td":         "higher_better",
            "comp_pct":        "higher_better",
            "pass_10plus":     "higher_better",
            "pass_20plus":     "higher_better",
            "pass_success_rt": "higher_better",
            "rush_pct":        "higher_better",
            "rush_yards":      "higher_better",
            "rush_ypa":        "higher_better",
            "rush_td":         "higher_better",
            "rush_10plus":     "higher_better",
            "rush_20plus":     "higher_better",
            "rush_success_rt": "higher_better",
        }
    else:  # defense — lower yards/rates allowed = better
        directions = {
            "pass_pct":        "higher_better",   # opponent passing more = bad, but neutral stat
            "pass_yards":      "lower_better",
            "pass_ypa":        "lower_better",
            "pass_td":         "lower_better",
            "comp_pct":        "lower_better",
            "pass_10plus":     "lower_better",
            "pass_20plus":     "lower_better",
            "pass_success_rt": "lower_better",
            "rush_pct":        "higher_better",   # neutral
            "rush_yards":      "lower_better",
            "rush_ypa":        "lower_better",
            "rush_td":         "lower_better",
            "rush_10plus":     "lower_better",
            "rush_20plus":     "lower_better",
            "rush_success_rt": "lower_better",
        }
    return build_rankings(df, directions)


METRIC_LABELS = [
    (None,             "Passing"),
    ("pass_pct",       "% Plays Pass"),
    ("pass_yards",     "Total Yards"),
    ("pass_ypa",       "Yards per Attempt"),
    ("pass_td",        "TD"),
    ("comp_pct",       "Comp Pct"),
    ("pass_10plus",    "10+ Yd Completions"),
    ("pass_20plus",    "20+ Yd Completions"),
    ("pass_success_rt","Success Rate"),
    (None,             "Rushing"),
    ("rush_pct",       "% Plays Run"),
    ("rush_yards",     "Total Yards"),
    ("rush_ypa",       "Yards Per Attempt"),
    ("rush_td",        "TD"),
    ("rush_10plus",    "10+ Yard Rushes"),
    ("rush_20plus",    "20+ Yard Rushes"),
    ("rush_success_rt","Success Rate"),
]


def build_side_by_side(off_ranked: pd.DataFrame, def_ranked: pd.DataFrame) -> pd.DataFrame:
    off = off_ranked[off_ranked["team"] == TEAM].iloc[0]
    dff = def_ranked[def_ranked["team"] == TEAM].iloc[0]

    rows = []
    for key, label in METRIC_LABELS:
        if key is None:
            rows.append({"Offense": "", "Metric": label, "Defense": ""})
        else:
            off_val = f"{off[key]} ({ordinal(off[key+'_rank'])})"
            def_val = f"{dff[key]} ({ordinal(dff[key+'_rank'])})"
            rows.append({"Offense": off_val, "Metric": label, "Defense": def_val})
    return pd.DataFrame(rows)


def main():
    df = load_plays()
    df = add_flags(df)

    off_stats = compute_production(df, "offense")
    def_stats = compute_production(df, "defense")

    off_ranked = add_ranks(off_stats, "offense")
    def_ranked = add_ranks(def_stats, "defense")

    off_ranked.to_csv(f"{OUT_DIR}/production_offense.csv", index=False)
    def_ranked.to_csv(f"{OUT_DIR}/production_defense.csv", index=False)

    report = build_side_by_side(off_ranked, def_ranked)
    report.to_csv(f"{OUT_DIR}/production_report.csv", index=False)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
