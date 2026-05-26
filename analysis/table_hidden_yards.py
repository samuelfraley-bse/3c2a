"""
Hidden Yards Report — Offense & Defense
Points per drive segmented by starting field position zone.

Zones (yardline_100 = yards to opponent end zone):
  Backed Up : yardline_100 >= 75  (own 25 or worse)
  Normal    : 51 <= yardline_100 < 75  (own 26 to own 49)
  Plus      : 21 <= yardline_100 <= 50  (opponent territory outside RZ)
  Redzone   : yardline_100 <= 20
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import build_rankings, ordinal, TEAM

OUT_DIR = "outputs/2025-26/report_tables"
os.makedirs(OUT_DIR, exist_ok=True)

DATA_PATH = "outputs/2025-26/plays.csv"

ZONES = [
    ("backed_up", "Backed Up",  "OWN 25-",   "OPP 75+"),
    ("normal",    "Normal",     "OWN 26-49", "OPP 26-49"),
    ("plus",      "Plus",       "OPP 26-49", "OWN 26-49"),
    ("redzone",   "Red Zone",   "OPP 20-",   "OWN 20-"),
]


def zone_label(y: float) -> str:
    if pd.isna(y):
        return None
    if y >= 75:
        return "backed_up"
    if y >= 51:
        return "normal"
    if y >= 21:
        return "plus"
    return "redzone"


def build_drive_summary(df_all: pd.DataFrame) -> pd.DataFrame:
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
            td=("is_td", "any"),
            start_yardline=("yardline_100", "first"),
        )
        .reset_index()
    )

    agg["fg"] = agg.apply(lambda r: (r["game_id"], r["drive_id"]) in fg_drives, axis=1)
    agg["points"] = agg["td"].apply(lambda x: 7 if x else 0) + agg["fg"].apply(lambda x: 3 if x else 0)
    agg["zone"] = agg["start_yardline"].apply(zone_label)

    return agg[agg["zone"].notna()]


def compute_hidden_yards(drives: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for team, g in drives.groupby(group_col):
        row = {"team": team}
        for zone_key, *_ in ZONES:
            zg = g[g["zone"] == zone_key]
            row[f"{zone_key}_drives"] = len(zg)
            row[f"{zone_key}_pts"]    = round(zg["points"].mean(), 2) if len(zg) else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def add_ranks(df: pd.DataFrame, side: str) -> pd.DataFrame:
    direction = "higher_better" if side == "offense" else "lower_better"
    directions = {f"{z}_pts": direction for z, *_ in ZONES}
    return build_rankings(df, directions)


def build_report(off_ranked: pd.DataFrame, def_ranked: pd.DataFrame) -> pd.DataFrame:
    off = off_ranked[off_ranked["team"] == TEAM].iloc[0]
    dff = def_ranked[def_ranked["team"] == TEAM].iloc[0]
    rows = []
    for zone_key, zone_name, off_label, def_label in ZONES:
        pts_col  = f"{zone_key}_pts"
        drv_col  = f"{zone_key}_drives"
        rank_col = f"{pts_col}_rank"
        off_drives = int(off[drv_col])
        def_drives = int(dff[drv_col])
        metric = f"{zone_name} | OFF: {off_label} / DEF: {def_label}"
        off_val = f"{off[pts_col]} pts ({off_drives} drives, {ordinal(off[rank_col])})" if rank_col in off_ranked.columns else f"{off[pts_col]} pts ({off_drives} drives)"
        def_val = f"{dff[pts_col]} pts ({def_drives} drives, {ordinal(dff[rank_col])})" if rank_col in def_ranked.columns else f"{dff[pts_col]} pts ({def_drives} drives)"
        rows.append({"Offense": off_val, "Metric": metric, "Defense": def_val})
    return pd.DataFrame(rows)


def main():
    df_all = pd.read_csv(DATA_PATH)
    drives = build_drive_summary(df_all)

    off_stats  = compute_hidden_yards(drives, "offense")
    def_stats  = compute_hidden_yards(drives, "defense")
    off_ranked = add_ranks(off_stats, "offense")
    def_ranked = add_ranks(def_stats, "defense")

    off_ranked.to_csv(f"{OUT_DIR}/hidden_yards_offense.csv", index=False)
    def_ranked.to_csv(f"{OUT_DIR}/hidden_yards_defense.csv", index=False)

    report = build_report(off_ranked, def_ranked)
    report.to_csv(f"{OUT_DIR}/hidden_yards_report.csv", index=False)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
