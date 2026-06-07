"""
Export chart-ready CSVs for Foothill 2025-26 season report.

Game-by-game trends (Foothill only, one row per game):
  chart_game_success_rate.csv       - success rate O/D by game
  chart_game_explosive_rate.csv     - explosive play rate by game
  chart_game_stuff_rate.csv         - run stuff rate by game
  chart_game_third_down.csv         - 3rd down conversion rate by game
  chart_game_early_down_rush.csv    - early down rush rate by game
  chart_game_passing_down_pass.csv  - passing down pass rate by game
  chart_game_avg_start_pos.csv      - avg drive starting position by game
  chart_game_penalty_yards.csv      - penalty yards by game
  chart_game_half_success.csv       - 1st vs 2nd half success rate O/D by game

Other charts:
  chart_success_by_down.csv         - success rate by down (1-4)
  chart_conv_by_distance.csv        - 3rd/4th down conv rate by yards-to-go bucket
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import load_plays, add_flags, TEAM
from analysis.table_hidden_yards import build_drive_summary

OUT_DIR = "outputs/2025-26/chart_data"
os.makedirs(OUT_DIR, exist_ok=True)


def game_order(df: pd.DataFrame) -> list:
    """Return game_ids in chronological order for Foothill games."""
    foothill = df[(df["offense"] == TEAM) | (df["defense"] == TEAM)]
    gids = foothill["game_id"].unique()
    return sorted(gids, key=lambda g: g[:8])


def opponent(df: pd.DataFrame, gid: str) -> str:
    g = df[df["game_id"] == gid]
    opp = g[g["offense"] != TEAM]["offense"].dropna().unique()
    if len(opp):
        return opp[0]
    opp = g[g["defense"] != TEAM]["defense"].dropna().unique()
    return opp[0] if len(opp) else "Unknown"


def rate(num, den):
    return round(num / den * 100, 1) if den else None


# ---------------------------------------------------------------------------

def chart_game_success_rate(df):
    games = game_order(df)
    rows = []
    for gid in games:
        g = df[df["game_id"] == gid]
        off = g[g["offense"] == TEAM]
        dff = g[g["defense"] == TEAM]
        rows.append({
            "game_id":      gid,
            "opponent":     opponent(df, gid),
            "off_success":  rate(off["success"].sum(), len(off)),
            "def_success":  rate(dff["success"].sum(), len(dff)),
        })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_success_rate.csv", index=False)
    print(f"  chart_game_success_rate.csv ({len(rows)} games)")


def chart_game_explosive_rate(df):
    games = game_order(df)
    rows = []
    for gid in games:
        g = df[df["game_id"] == gid]
        off = g[g["offense"] == TEAM]
        dff = g[g["defense"] == TEAM]
        rows.append({
            "game_id":     gid,
            "opponent":    opponent(df, gid),
            "off_exp_pct": rate(off["explosive"].sum(), len(off)),
            "def_exp_pct": rate(dff["explosive"].sum(), len(dff)),
        })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_explosive_rate.csv", index=False)
    print(f"  chart_game_explosive_rate.csv ({len(rows)} games)")


def chart_game_stuff_rate(df):
    games = game_order(df)
    rows = []
    for gid in games:
        g = df[df["game_id"] == gid]
        off_rush = g[(g["offense"] == TEAM) & (g["play_type"] == "rush")]
        def_rush = g[(g["defense"] == TEAM) & (g["play_type"] == "rush")]
        rows.append({
            "game_id":        gid,
            "opponent":       opponent(df, gid),
            "off_stuff_pct":  rate(off_rush["run_stuff"].sum(), len(off_rush)),
            "def_stuff_pct":  rate(def_rush["run_stuff"].sum(), len(def_rush)),
        })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_stuff_rate.csv", index=False)
    print(f"  chart_game_stuff_rate.csv ({len(rows)} games)")


def chart_game_third_down(df):
    games = game_order(df)
    rows = []
    for gid in games:
        g = df[(df["game_id"] == gid) & df["has_down_distance"] & (df["down"] == 3)]
        off = g[g["offense"] == TEAM]
        dff = g[g["defense"] == TEAM]
        rows.append({
            "game_id":      gid,
            "opponent":     opponent(df, gid),
            "off_conv_pct": rate(off["success"].sum(), len(off)),
            "def_conv_pct": rate(dff["success"].sum(), len(dff)),
            "off_attempts": len(off),
            "def_attempts": len(dff),
        })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_third_down.csv", index=False)
    print(f"  chart_game_third_down.csv ({len(rows)} games)")


def chart_game_early_down_rush(df):
    games = game_order(df)
    rows = []
    for gid in games:
        g = df[(df["game_id"] == gid) & df["early_down"]]
        off = g[g["offense"] == TEAM]
        dff = g[g["defense"] == TEAM]
        rows.append({
            "game_id":        gid,
            "opponent":       opponent(df, gid),
            "off_rush_pct":   rate((off["play_type"] == "rush").sum(), len(off)),
            "def_rush_pct":   rate((dff["play_type"] == "rush").sum(), len(dff)),
        })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_early_down_rush.csv", index=False)
    print(f"  chart_game_early_down_rush.csv ({len(rows)} games)")


def chart_game_passing_down_pass(df):
    games = game_order(df)
    rows = []
    for gid in games:
        g = df[(df["game_id"] == gid) & df["passing_down"]]
        off = g[g["offense"] == TEAM]
        dff = g[g["defense"] == TEAM]
        off_pass = off[~off["is_sack"]] if "is_sack" in off.columns else off[off["play_type"] == "pass"]
        def_pass = dff[~dff["is_sack"]] if "is_sack" in dff.columns else dff[dff["play_type"] == "pass"]
        rows.append({
            "game_id":        gid,
            "opponent":       opponent(df, gid),
            "off_pass_pct":   rate(len(off[off["play_type"] == "pass"]), len(off)),
            "def_pass_pct":   rate(len(dff[dff["play_type"] == "pass"]), len(dff)),
        })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_passing_down_pass.csv", index=False)
    print(f"  chart_game_passing_down_pass.csv ({len(rows)} games)")


ABB_MAP = {
    "20250830_8cjh": "MPC",   "20250906_tjag": "COR",  "20250913_0tz1": "REED",
    "20250920_47d4": "SIER",  "20250927_h3ae": "SAC",  "20251010_e15n": "LANEY",
    "20251018_4eui": "CSM",   "20251024_zu0m": "DVC",  "20251101_ck1p": "CCSF",
    "20251108_o06f": "SJCC",  "20251122_7wb6": "COS",
}


def chart_game_avg_start_pos(df_all):
    drives = build_drive_summary(df_all)
    foothill_gids = drives[(drives["offense"] == TEAM) | (drives["defense"] == TEAM)]["game_id"].unique()
    games = sorted(foothill_gids, key=lambda g: g[:8])

    rows = []
    for i, gid in enumerate(games, 1):
        g = drives[drives["game_id"] == gid]
        off = g[g["offense"] == TEAM]["start_yardline"].dropna()
        dff = g[g["defense"] == TEAM]["start_yardline"].dropna()
        rows.append({
            "game_id":         gid,
            "opponent":        opponent(df_all, gid),
            "opp_abbr":        ABB_MAP.get(gid, gid),
            "game_order":      i,
            "off_avg_start":   round(100 - off.mean(), 1) if len(off) else None,
            "def_avg_start":   round(100 - dff.mean(), 1) if len(dff) else None,
        })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_avg_start_pos.csv", index=False)
    print(f"  chart_game_avg_start_pos.csv ({len(rows)} games)")


def chart_game_penalty_yards(df):
    games = game_order(df)
    rows = []
    for gid in games:
        g = df[df["game_id"] == gid]
        off = g[g["offense"] == TEAM]
        dff = g[g["defense"] == TEAM]
        rows.append({
            "game_id":         gid,
            "opponent":        opponent(df, gid),
            "off_penalty_yds": int(off["penalty_yards"].fillna(0).sum()),
            "def_penalty_yds": int(dff["penalty_yards"].fillna(0).sum()),
        })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_penalty_yards.csv", index=False)
    print(f"  chart_game_penalty_yards.csv ({len(rows)} games)")


def chart_game_half_success(df):
    games = game_order(df)
    rows = []
    for gid in games:
        g = df[df["game_id"] == gid]
        for side, col in [("off", "offense"), ("def", "defense")]:
            sg = g[g[col] == TEAM]
            first  = sg[sg["quarter"] <= 2]
            second = sg[sg["quarter"] > 2]
            rows.append({
                "game_id":          gid,
                "opponent":         opponent(df, gid),
                "side":             side,
                "first_half_succ":  rate(first["success"].sum(), len(first)),
                "second_half_succ": rate(second["success"].sum(), len(second)),
            })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_game_half_success.csv", index=False)
    print(f"  chart_game_half_success.csv ({len(rows)} rows)")


def chart_success_by_down(df):
    rows = []
    for side, col in [("offense", "offense"), ("defense", "defense")]:
        sg = df[df[col] == TEAM]
        for down in [1, 2, 3, 4]:
            dg = sg[sg["down"] == down]
            rows.append({
                "side":        side,
                "down":        down,
                "attempts":    len(dg),
                "success_pct": rate(dg["success"].sum(), len(dg)),
            })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_success_by_down.csv", index=False)
    print(f"  chart_success_by_down.csv")


def chart_conv_by_distance(df):
    buckets = [(1, 1, "1"), (2, 3, "2-3"), (4, 6, "4-6"), (7, 10, "7-10"), (11, 99, "11+")]
    rows = []
    for side, col in [("offense", "offense"), ("defense", "defense")]:
        sg = df[(df[col] == TEAM) & df["down"].isin([3, 4]) & df["has_down_distance"]]
        for lo, hi, label in buckets:
            bg = sg[(sg["distance"] >= lo) & (sg["distance"] <= hi)]
            rows.append({
                "side":        side,
                "distance":    label,
                "attempts":    len(bg),
                "conv_pct":    rate(bg["success"].sum(), len(bg)),
            })
    pd.DataFrame(rows).to_csv(f"{OUT_DIR}/chart_conv_by_distance.csv", index=False)
    print(f"  chart_conv_by_distance.csv")


def main():
    df = load_plays()
    df = add_flags(df)
    df_all = pd.read_csv("outputs/2025-26/plays.csv")

    print(f"Exporting chart CSVs to {OUT_DIR}/")
    chart_game_success_rate(df)
    chart_game_explosive_rate(df)
    chart_game_stuff_rate(df)
    chart_game_third_down(df)
    chart_game_early_down_rush(df)
    chart_game_passing_down_pass(df)
    chart_game_avg_start_pos(df_all)
    chart_game_penalty_yards(df)
    chart_game_half_success(df)
    chart_success_by_down(df)
    chart_conv_by_distance(df)
    print("Done.")


if __name__ == "__main__":
    main()
