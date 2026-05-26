"""
Red Zone Report — Offense & Defense
Filter: redzone == True (opponent side, yardline_100 <= 20)
Drive-level metrics group by drive_id to find scoring outcomes.
"""

import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.helpers import load_plays, add_flags, build_rankings, ordinal, TEAM

OUT_DIR = "outputs/2025-26/report_tables"
os.makedirs(OUT_DIR, exist_ok=True)


def compute_redzone(df: pd.DataFrame, df_all: pd.DataFrame, group_col: str) -> pd.DataFrame:
    # total drives per team (all play types, scrimmage drives only via drive_id > 0)
    total_drives = (
        df_all[df_all["drive_id"].notna() & (df_all["drive_id"].astype(str) != "0")]
        .groupby([group_col, "game_id", "drive_id"])
        .size()
        .reset_index()
        .groupby(group_col)
        .size()
        .to_dict()
    )

    rows = []
    for team, g in df.groupby(group_col):
        rz = g[g["redzone"]]
        if len(rz) == 0:
            continue

        passes   = rz[rz["play_type"] == "pass"]
        pass_att = passes[~passes["is_sack"]]
        rushes   = rz[rz["play_type"] == "rush"]
        n        = len(rz)

        # Drive-level: use all play types to correctly detect FG outcomes
        rz_drive_keys = rz[["game_id", "drive_id"]].drop_duplicates()
        rz_all = df_all.merge(rz_drive_keys, on=["game_id", "drive_id"], how="inner")

        rz_fg = rz_all[rz_all["play_type"] == "field_goal"]
        fg_drives = set(
            zip(rz_fg[rz_fg["fg_result"] == "good"]["game_id"],
                rz_fg[rz_fg["fg_result"] == "good"]["drive_id"])
        )

        drive_summary = (
            rz_all.groupby(["game_id", "drive_id"])
            .agg(
                td=("is_td", "any"),
                plays=("play_id", "count"),
            )
            .reset_index()
        )
        drive_summary["fg"] = drive_summary.apply(
            lambda r: (r["game_id"], r["drive_id"]) in fg_drives, axis=1
        )
        n_drives    = len(drive_summary)
        n_td        = drive_summary["td"].sum()
        n_fg        = drive_summary["fg"].sum()
        n_score     = (drive_summary["td"] | drive_summary["fg"]).sum()
        n_stop      = n_drives - n_score
        total_drv   = total_drives.get(team, 0)

        rows.append({
            "team":          team,
            "rz_drives":     n_drives,
            "rz_drive_pct":  round(n_drives / total_drv * 100, 1) if total_drv else 0,
            "td_pct":        round(n_td   / n_drives * 100, 1) if n_drives else 0,
            "fg_pct":        round(n_fg   / n_drives * 100, 1) if n_drives else 0,
            "score_pct":     round(n_score / n_drives * 100, 1) if n_drives else 0,
            "stop_pct":      round(n_stop  / n_drives * 100, 1) if n_drives else 0,
            "rush_pct":      round(len(rushes) / n * 100, 1) if n else 0,
            "rush_ypa":      round(rushes["yards_gained"].mean(), 2) if len(rushes) else 0,
            "run_stuff_pct": round(rushes["run_stuff"].sum() / len(rushes) * 100, 1) if len(rushes) else 0,
            "rush_td":       int(rushes["is_td"].sum()),
            "pass_pct":      round(len(pass_att) / n * 100, 1) if n else 0,
            "comp_pct":      round(pass_att["completion"].sum() / len(pass_att) * 100, 1) if len(pass_att) else 0,
            "pass_td":       int(pass_att["is_td"].sum()),
            "int":           int((pass_att["pass_result"] == "int").sum()),
        })
    return pd.DataFrame(rows)


def add_ranks(df: pd.DataFrame, side: str) -> pd.DataFrame:
    if side == "offense":
        directions = {
            "rz_drive_pct":  "higher_better",
            "td_pct":        "higher_better",
            "fg_pct":        "higher_better",
            "score_pct":     "higher_better",
            "stop_pct":      "lower_better",
            "rush_pct":      "higher_better",
            "rush_ypa":      "higher_better",
            "run_stuff_pct": "lower_better",
            "rush_td":       "higher_better",
            "pass_pct":      "higher_better",
            "comp_pct":      "higher_better",
            "pass_td":       "higher_better",
            "int":           "lower_better",
        }
    else:
        directions = {
            "rz_drive_pct":  "lower_better",
            "td_pct":        "lower_better",
            "fg_pct":        "lower_better",
            "score_pct":     "lower_better",
            "stop_pct":      "higher_better",
            "rush_ypa":      "lower_better",
            "run_stuff_pct": "higher_better",
            "rush_td":       "lower_better",
            "comp_pct":      "lower_better",
            "pass_td":       "lower_better",
            "int":           "higher_better",
        }
    return build_rankings(df, directions)


METRIC_LABELS = [
    ("rz_drives",    "Drives Inside 20"),
    ("score_pct",    "Score %"),
    ("td_pct",       "TD %"),
    ("fg_pct",       "FG %"),
    ("stop_pct",     "Stop %"),
    ("rush_pct",     "% Rush Plays"),
    ("rush_ypa",     "Rush YPC"),
    ("run_stuff_pct","Run Stuff %"),
    ("rush_td",      "Rush TD"),
    ("pass_pct",     "% Pass Plays"),
    ("comp_pct",     "Comp %"),
    ("pass_td",      "Pass TD"),
    ("int",          "Interceptions"),
]


# keys where the count row should show: "38 (54.0%, rank)" using a pct backing column
COUNT_WITH_PCT = {"rz_drives": "rz_drive_pct"}


def build_report(off_ranked: pd.DataFrame, def_ranked: pd.DataFrame) -> pd.DataFrame:
    off = off_ranked[off_ranked["team"] == TEAM].iloc[0]
    dff = def_ranked[def_ranked["team"] == TEAM].iloc[0]
    rows = []
    for key, label in METRIC_LABELS:
        rank_col = f"{key}_rank"
        if key in COUNT_WITH_PCT:
            pct_col  = COUNT_WITH_PCT[key]
            pct_rank = f"{pct_col}_rank"
            off_val  = f"{int(off[key])} ({off[pct_col]}%, {ordinal(off[pct_rank])})"
            def_val  = f"{int(dff[key])} ({dff[pct_col]}%, {ordinal(dff[pct_rank])})"
        else:
            off_val = f"{off[key]} ({ordinal(off[rank_col])})" if rank_col in off_ranked.columns else str(off[key])
            def_val = f"{dff[key]} ({ordinal(dff[rank_col])})" if rank_col in def_ranked.columns else str(dff[key])
        rows.append({"Offense": off_val, "Metric": label, "Defense": def_val})
    return pd.DataFrame(rows)


def main():
    df = load_plays()
    df = add_flags(df)
    # redzone requires field_pos_side to be resolved
    df = df[df["field_pos_side"].notna() & (df["field_pos_side"] != "")].copy()

    # all play types needed to detect FG outcomes at the drive level
    df_all = pd.read_csv("outputs/2025-26/plays.csv")

    off_stats  = compute_redzone(df, df_all, "offense")
    def_stats  = compute_redzone(df, df_all, "defense")
    off_ranked = add_ranks(off_stats, "offense")
    def_ranked = add_ranks(def_stats, "defense")

    off_ranked.to_csv(f"{OUT_DIR}/redzone_offense.csv", index=False)
    def_ranked.to_csv(f"{OUT_DIR}/redzone_defense.csv", index=False)

    report = build_report(off_ranked, def_ranked)
    report.to_csv(f"{OUT_DIR}/redzone_report.csv", index=False)
    print(report.to_string(index=False))


if __name__ == "__main__":
    main()
