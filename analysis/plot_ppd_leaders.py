"""
Points per Drive Leaders — top 15 / bottom 15, side by side.

Pulls drive-level points straight from duckdb_pipeline's v_drives_current
(offense side). Writes: analysis/showcase/ppd_leaders.png

Usage: python analysis/plot_ppd_leaders.py [season] [min_games]
"""

import sys

import duckdb
import matplotlib.pyplot as plt

DB_PATH = "duckdb_pipeline/data/foothill.duckdb"
OUT_PNG = "analysis/showcase/ppd_leaders.png"

SEASON = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
MIN_GAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 6
HIGHLIGHT_TEAM = "Foothill"
TOP_N = 15

con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute(
    """
    select offense as team_name, count(distinct game_id) as games, count(*) as drives,
           sum(drive_points) as total_points, avg(drive_points) as ppd
    from v_drives_current
    where season = ? and offense is not null and offense != '' and drive_points <= 8
    group by offense
    having count(distinct game_id) >= ?
    order by ppd desc
    """,
    [SEASON, MIN_GAMES],
).fetchdf()

print(f"{SEASON}: n={len(df)} teams (min {MIN_GAMES} games)")
print(f"League avg PPD: {df['ppd'].mean():.2f}")

top15 = df.head(TOP_N).sort_values("ppd", ascending=True)   # ascending for barh (best at top)
bot15 = df.tail(TOP_N).sort_values("ppd", ascending=False)  # descending for barh (worst at top)

fh_rank_top = df[df["team_name"] == HIGHLIGHT_TEAM]
if not fh_rank_top.empty:
    idx = df.index[df["team_name"] == HIGHLIGHT_TEAM][0]
    print(f"\n{HIGHLIGHT_TEAM}: {df.loc[idx, 'ppd']:.2f} PPD, rank {idx + 1} of {len(df)}")

# ── plot ──────────────────────────────────────────────────────────────────

fig, (ax_top, ax_bot) = plt.subplots(1, 2, figsize=(13, 7.5), sharex=True)

league_avg = df["ppd"].mean()

def _panel(ax, data, title, base_color):
    colors = ["#eda100" if t == HIGHLIGHT_TEAM else base_color for t in data["team_name"]]
    ax.barh(data["team_name"], data["ppd"], color=colors, edgecolor="none", height=0.72)
    for i, (_, row) in enumerate(data.iterrows()):
        ax.text(row["ppd"] + 0.03, i, f"{row['ppd']:.2f}", va="center", fontsize=9,
                fontweight="bold" if row["team_name"] == HIGHLIGHT_TEAM else "normal")
    ax.axvline(league_avg, color="#898781", lw=1.2, ls="--", zorder=1, label=f"League avg ({league_avg:.2f})")
    ax.set_title(title, fontsize=11.5, fontweight="bold")
    ax.set_xlabel("Points per Drive", fontsize=10)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.legend(fontsize=8, loc="lower right")

_panel(ax_top, top15, f"Top {TOP_N}", "#2a78d6")
_panel(ax_bot, bot15, f"Bottom {TOP_N}", "#e34948")

fig.suptitle(f"Points per Drive Leaders  |  {SEASON} CA JC Football (Offense)", fontsize=14, fontweight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig(OUT_PNG, bbox_inches="tight", dpi=150)
print(f"\nSaved {OUT_PNG}")
