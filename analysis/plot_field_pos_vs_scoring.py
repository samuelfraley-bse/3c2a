"""
Field Position vs. Scoring Rate — offense scatter with regression line.

Pulls straight from the duckdb_pipeline gold layer (v_team_season_drives_offense_current),
so it stays in sync with whatever fixes have landed in the DB. Writes:
  analysis/showcase/field_pos_vs_scoring.png

Usage: python analysis/plot_field_pos_vs_scoring.py [season] [min_games]
"""

import sys

import duckdb
import numpy as np
import matplotlib.pyplot as plt

DB_PATH = "duckdb_pipeline/data/foothill.duckdb"
OUT_PNG = "analysis/showcase/field_pos_vs_scoring.png"

SEASON = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
MIN_GAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 6
HIGHLIGHT_TEAM = "Foothill"

con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute(
    """
    select team_name, games, drives, drives_scored,
           100.0 - total_start_yardline_100 / drives as start_from_own,
           100.0 * drives_scored / drives as score_rate
    from v_team_season_drives_offense_current
    where season = ? and games >= ? and team_name is not null and team_name != ''
    """,
    [SEASON, MIN_GAMES],
).fetchdf()

# guard against the occasional broken field-position row (unresolved crosswalk entries
# can push total_start_yardline_100 wildly negative/positive)
df = df[df["start_from_own"].between(0, 100)].reset_index(drop=True)

x = df["start_from_own"].values
y = df["score_rate"].values
slope, intercept = np.polyfit(x, y, 1)
df["pred"] = slope * x + intercept
df["resid"] = y - df["pred"]
r = np.corrcoef(x, y)[0, 1]

print(f"{SEASON}: n={len(df)} teams, r={r:.3f}, slope={slope:.3f}, intercept={intercept:.2f}")
print("\nTop 5 overperforming trend:")
print(df.nlargest(5, "resid")[["team_name", "games", "start_from_own", "score_rate", "resid"]].to_string(index=False))
print("\nBottom 5 underperforming trend:")
print(df.nsmallest(5, "resid")[["team_name", "games", "start_from_own", "score_rate", "resid"]].to_string(index=False))

fh = df[df["team_name"] == HIGHLIGHT_TEAM]
if not fh.empty:
    row = fh.iloc[0]
    print(f"\n{HIGHLIGHT_TEAM}: started own {row.start_from_own:.1f}, scored {row.score_rate:.1f}% of drives, {row.resid:+.1f} pts vs. trend")

# ── plot ──────────────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(10, 7.5))

hl = df[df["team_name"] == HIGHLIGHT_TEAM]
bg = df[df["team_name"] != HIGHLIGHT_TEAM]

colors = np.where(bg["resid"] >= 0, "#2a78d6", "#e34948")
ax.scatter(bg["start_from_own"], bg["score_rate"], s=55, c=colors, alpha=0.75,
           edgecolors="white", linewidths=0.6, zorder=3)

if not hl.empty:
    row = hl.iloc[0]
    ax.scatter(row["start_from_own"], row["score_rate"], s=170,
               facecolors="white", edgecolors="#eda100", linewidths=2.5, zorder=5)
    ax.annotate(HIGHLIGHT_TEAM, (row["start_from_own"], row["score_rate"]),
                textcoords="offset points", xytext=(8, 6), fontsize=9.5, fontweight="bold",
                color="#c98500")

xr = np.linspace(x.min(), x.max(), 100)
ax.plot(xr, slope * xr + intercept, color="#898781", lw=1.8, ls="--", zorder=2, label="League trend")

for _, row in df.reindex(df["resid"].abs().sort_values(ascending=False).index[:6]).iterrows():
    if row["team_name"] == HIGHLIGHT_TEAM:
        continue
    ax.annotate(row["team_name"], (row["start_from_own"], row["score_rate"]),
                textcoords="offset points", xytext=(6, 4), fontsize=8, color="#52514e")

ax.set_xlabel("Average Starting Field Position (own-yard line)", fontsize=11)
ax.set_ylabel("% of Drives That Score", fontsize=11)
ax.set_title(f"Field Position vs. Scoring Rate  |  {SEASON} CA JC Football (offense)\nr = {r:.2f}",
             fontsize=13, fontweight="bold")
ax.legend(fontsize=9, loc="upper left")
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))

plt.tight_layout()
plt.savefig(OUT_PNG, bbox_inches="tight", dpi=150)
print(f"\nSaved {OUT_PNG}")
