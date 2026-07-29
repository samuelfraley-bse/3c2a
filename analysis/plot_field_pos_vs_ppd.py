"""
Field Position vs. Points per Drive — offense scatter with regression line.

Same shape as plot_field_pos_vs_scoring.py, but points/drive instead of the
binary "did this drive score" rate — weights TDs above FGs.

Usage: python analysis/plot_field_pos_vs_ppd.py [season] [min_games]
"""

import sys

import duckdb
import numpy as np
import matplotlib.pyplot as plt

DB_PATH = "duckdb_pipeline/data/foothill.duckdb"
OUT_PNG = "analysis/showcase/field_pos_vs_ppd.png"

SEASON = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
MIN_GAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 6
HIGHLIGHT_TEAM = "Foothill"

con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute(
    """
    select offense as team_name, count(distinct game_id) as games, count(*) as drives,
           avg(100 - start_yardline_100) as start_from_own,
           avg(drive_points) as ppd
    from v_drives_current
    where season = ? and offense is not null and offense != '' and drive_points <= 8
    group by offense
    having count(distinct game_id) >= ?
    """,
    [SEASON, MIN_GAMES],
).fetchdf()

df = df[df["start_from_own"].between(0, 100)].reset_index(drop=True)

x = df["start_from_own"].values
y = df["ppd"].values
slope, intercept = np.polyfit(x, y, 1)
df["pred"] = slope * x + intercept
df["resid"] = y - df["pred"]
r2 = np.corrcoef(x, y)[0, 1] ** 2

print(f"{SEASON}: n={len(df)} teams, r2={r2:.3f}, slope={slope:.3f}, intercept={intercept:.2f}")
print("\nTop 5 overperforming trend:")
print(df.nlargest(5, "resid")[["team_name", "games", "start_from_own", "ppd", "resid"]].to_string(index=False))
print("\nBottom 5 underperforming trend:")
print(df.nsmallest(5, "resid")[["team_name", "games", "start_from_own", "ppd", "resid"]].to_string(index=False))

fh = df[df["team_name"] == HIGHLIGHT_TEAM]
if not fh.empty:
    row = fh.iloc[0]
    print(f"\n{HIGHLIGHT_TEAM}: started own {row.start_from_own:.1f}, {row.ppd:.2f} PPD, {row.resid:+.2f} vs. trend")

# ── plot ──────────────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(10, 7.5))

hl = df[df["team_name"] == HIGHLIGHT_TEAM]
bg = df[df["team_name"] != HIGHLIGHT_TEAM]

colors = np.where(bg["resid"] >= 0, "#2a78d6", "#e34948")
ax.scatter(bg["start_from_own"], bg["ppd"], s=55, c=colors, alpha=0.75,
           edgecolors="white", linewidths=0.6, zorder=3)

if not hl.empty:
    row = hl.iloc[0]
    ax.scatter(row["start_from_own"], row["ppd"], s=170,
               facecolors="white", edgecolors="#eda100", linewidths=2.5, zorder=5)
    ax.annotate(HIGHLIGHT_TEAM, (row["start_from_own"], row["ppd"]),
                textcoords="offset points", xytext=(8, 6), fontsize=9.5, fontweight="bold",
                color="#c98500")

xr = np.linspace(x.min(), x.max(), 100)
ax.plot(xr, slope * xr + intercept, color="#898781", lw=1.8, ls="--", zorder=2, label="League trend")

for _, row in df.reindex(df["resid"].abs().sort_values(ascending=False).index[:6]).iterrows():
    if row["team_name"] == HIGHLIGHT_TEAM:
        continue
    ax.annotate(row["team_name"], (row["start_from_own"], row["ppd"]),
                textcoords="offset points", xytext=(6, 4), fontsize=8, color="#52514e")

ax.set_xlabel("Average Starting Field Position (own-yard line)", fontsize=11)
ax.set_ylabel("Points per Drive", fontsize=11)
ax.set_title(f"Field Position vs. Points per Drive  |  {SEASON} CA JC Football (offense)\nR² = {r2:.2f}",
             fontsize=13, fontweight="bold")
ax.legend(fontsize=9, loc="upper left")

plt.tight_layout()
plt.savefig(OUT_PNG, bbox_inches="tight", dpi=150)
print(f"\nSaved {OUT_PNG}")
