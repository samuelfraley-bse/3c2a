"""
Ranking bar charts and scatter plots for Foothill 2025-26 season report.
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import os

# --- Fonts ---
FONT_PATHS = {
    "heavy":  r"C:\Users\sffra\Downloads\united-serif-font\United Serif Reg Heavy\United Serif Reg Heavy.otf",
    "medium": r"C:\Users\sffra\Downloads\united-serif-reg-medium_6KssY\United Serif Reg Medium\United Serif Reg Medium.otf",
}
for path in FONT_PATHS.values():
    if os.path.exists(path):
        fm.fontManager.addfont(path)

FONT_HEAVY  = fm.FontProperties(fname=FONT_PATHS["heavy"])
FONT_MEDIUM = fm.FontProperties(fname=FONT_PATHS["medium"])
FONT_NAME   = FONT_MEDIUM.get_name()

# --- Colors ---
RED   = "#A61E2F"
BLACK = "#000000"
GOLD  = "#FFC82E"
GRAY  = "#D0D1CE"
LIGHT = "#F2E7D1"

TABLES = "outputs/2025-26/report_tables"
OUT    = "outputs/2025-26/charts"
os.makedirs(OUT, exist_ok=True)


def load(table, side):
    return pd.read_csv(f"{TABLES}/{table}_{side}.csv")


def style_ax(ax, title, xlabel="", ylabel=""):
    ax.set_title(title, fontproperties=FONT_HEAVY, fontsize=13, color=BLACK, pad=10)
    ax.set_xlabel(xlabel, fontfamily=FONT_NAME, fontsize=10, color=BLACK)
    ax.set_ylabel(ylabel, fontfamily=FONT_NAME, fontsize=10, color=BLACK)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(FONT_NAME)
        label.set_fontsize(9)
    ax.tick_params(colors=BLACK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRAY)
    ax.spines["bottom"].set_color(GRAY)
    ax.set_facecolor("white")
    ax.yaxis.grid(True, color=GRAY, linewidth=0.5, linestyle="--")
    ax.set_axisbelow(True)


def save(fig, name):
    path = f"{OUT}/{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {name}.png")


def bar_chart(ax, df, metric, rank_col, n=15, lower_better=False):
    """Plot top-n teams as horizontal bars, Foothill highlighted in red."""
    ranked = df.sort_values(rank_col).head(n).copy()
    ranked = ranked.sort_values(metric, ascending=lower_better)
    colors = [RED if t == "Foothill" else GRAY for t in ranked["team"]]
    bars = ax.barh(ranked["team"], ranked[metric], color=colors, edgecolor="white", height=0.7)
    # label Foothill bar
    for bar, team, val in zip(bars, ranked["team"], ranked[metric]):
        if team == "Foothill":
            ax.text(bar.get_width() + ax.get_xlim()[1] * 0.01, bar.get_y() + bar.get_height() / 2,
                    f"{val}", va="center", fontfamily=FONT_NAME, fontsize=9, color=RED, fontweight="bold")
    for label in ax.get_yticklabels():
        label.set_fontfamily(FONT_NAME)
        label.set_fontsize(9)
        if label.get_text() == "Foothill":
            label.set_color(RED)
            label.set_fontweight("bold")


def save(fig, name):
    path = f"{OUT}/{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {name}.png")


# ---------------------------------------------------------------------------
# GROUP 1 — Early Down Defense
# ---------------------------------------------------------------------------

def plot_early_down_defense():
    df = load("early_down", "defense")
    metrics = [
        ("success_rt",    "Success Rate %",    True,  "Success Rate Allowed",      "12a"),
        ("yards_per_play","Yards per Play",     True,  "Yards per Play Allowed",    "12b"),
        ("run_stuff_pct", "Run Stuff %",        False, "Run Stuff %",               "12c"),
        ("sack_pct",      "Sack %",             False, "Sack %",                    "12d"),
        ("explosive_pct", "Explosive %",        True,  "Explosive % Allowed",       "12e"),
    ]
    for metric, label, lower_better, title, num in metrics:
        fig, ax = plt.subplots(figsize=(8, 6))
        bar_chart(ax, df, metric, f"{metric}_rank", n=15, lower_better=lower_better)
        style_ax(ax, f"Early Down Defense — {title} (Top 15)", xlabel=label)
        ax.set_ylabel("")
        fig.tight_layout()
        save(fig, f"{num}_early_down_def_{metric}")


# ---------------------------------------------------------------------------
# GROUP 2 — Finishing Drives Defense
# ---------------------------------------------------------------------------

def plot_finishing_drives_defense():
    df = load("finishing_drives", "defense")
    metrics = [
        ("pts_per_drive", "Pts / Drive",      True,  "Points per Drive Allowed",        "13a"),
        ("scoring_rate",  "Scoring Rate %",   True,  "Scoring Rate Allowed",            "13b"),
        ("td_rate",       "TD Rate %",        True,  "TD Rate Allowed",                 "13c"),
        ("avg_start_pos", "Yardline 100",     False, "Avg Opponent Start (yds to go)",  "13d"),
    ]
    for metric, label, lower_better, title, num in metrics:
        fig, ax = plt.subplots(figsize=(8, 6))
        bar_chart(ax, df, metric, f"{metric}_rank", n=15, lower_better=lower_better)
        style_ax(ax, f"Finishing Drives Defense — {title} (Top 15)", xlabel=label)
        ax.set_ylabel("")
        fig.tight_layout()
        save(fig, f"{num}_finishing_drives_def_{metric}")


# ---------------------------------------------------------------------------
# GROUP 3 — 4th Down Offense
# ---------------------------------------------------------------------------

def plot_fourth_down_offense():
    df = load("fourth_down", "offense")
    metrics = [
        ("conv_pct",      "Conversion %",  False, "Conversion %",       "14a"),
        ("rush_conv_pct", "Rush Conv %",   False, "Rush Conversion %",  "14b"),
        ("pass_pct",      "Pass %",        False, "% Pass Plays",       "14c"),
        ("explosives",    "Explosives",    False, "Explosive Plays",    "14d"),
    ]
    for metric, label, lower_better, title, num in metrics:
        fig, ax = plt.subplots(figsize=(8, 6))
        bar_chart(ax, df, metric, f"{metric}_rank", n=15, lower_better=lower_better)
        style_ax(ax, f"4th Down Offense — {title} (Top 15)", xlabel=label)
        ax.set_ylabel("")
        fig.tight_layout()
        save(fig, f"{num}_fourth_down_off_{metric}")


# ---------------------------------------------------------------------------
# GROUP 4 — Turnovers
# ---------------------------------------------------------------------------

def plot_turnovers_group():
    ed_off = load("early_down", "offense")
    td_def = load("third_down", "defense")

    fig, ax = plt.subplots(figsize=(8, 6))
    bar_chart(ax, ed_off, "turnovers", "turnovers_rank", n=15, lower_better=True)
    style_ax(ax, "Fewest Early Down Turnovers — Offense (Top 15)", xlabel="Turnovers")
    ax.set_ylabel("")
    fig.tight_layout()
    save(fig, "15a_turnovers_off")

    fig, ax = plt.subplots(figsize=(8, 6))
    bar_chart(ax, td_def, "turnovers", "turnovers_rank", n=15, lower_better=False)
    style_ax(ax, "Most 3rd Down Turnovers Forced — Defense (Top 15)", xlabel="Turnovers Forced")
    ax.set_ylabel("")
    fig.tight_layout()
    save(fig, "15b_turnovers_def")


# ---------------------------------------------------------------------------
# SCATTER PLOTS
# ---------------------------------------------------------------------------

def scatter(ax, x_vals, y_vals, teams, title, xlabel, ylabel, annotate_all=False):
    for x, y, team in zip(x_vals, y_vals, teams):
        color = RED if team == "Foothill" else GRAY
        size  = 120 if team == "Foothill" else 40
        zorder = 5 if team == "Foothill" else 2
        ax.scatter(x, y, color=color, s=size, zorder=zorder, edgecolors="white", linewidth=0.5)

    # Always label Foothill
    for x, y, team in zip(x_vals, y_vals, teams):
        if team == "Foothill" or annotate_all:
            ax.annotate(
                team, (x, y),
                xytext=(6, 4), textcoords="offset points",
                fontfamily=FONT_NAME, fontsize=8,
                color=RED if team == "Foothill" else BLACK,
                fontweight="bold" if team == "Foothill" else "normal",
            )
    style_ax(ax, title, xlabel=xlabel, ylabel=ylabel)


def plot_scatter_early_down_vs_scoring():
    off_ed   = load("early_down",       "offense")[["team","success_rt"]]
    off_fin  = load("finishing_drives", "offense")[["team","scoring_rate"]]
    df = off_ed.merge(off_fin, on="team")
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter(ax, df["success_rt"], df["scoring_rate"], df["team"],
            "Early Down Success Rate vs Drive Scoring Rate (Offense)",
            "Early Down Success Rate %", "Drive Scoring Rate %")
    save(fig, "16_scatter_early_down_vs_scoring")


def plot_scatter_field_pos_vs_pts():
    def_fin = load("finishing_drives", "defense")[["team","avg_start_pos","pts_per_drive"]]
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter(ax, def_fin["avg_start_pos"], def_fin["pts_per_drive"], def_fin["team"],
            "Avg Opponent Start Position vs Points per Drive Allowed (Defense)",
            "Avg Opponent Start (yds to go — higher = pinned deeper)",
            "Points per Drive Allowed")
    save(fig, "17_scatter_field_pos_vs_pts")


def plot_scatter_third_down_vs_scoring():
    off_td  = load("third_down",       "offense")[["team","conv_pct"]]
    off_fin = load("finishing_drives", "offense")[["team","scoring_rate"]]
    df = off_td.merge(off_fin, on="team")
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter(ax, df["conv_pct"], df["scoring_rate"], df["team"],
            "3rd Down Conversion % vs Drive Scoring Rate (Offense)",
            "3rd Down Conversion %", "Drive Scoring Rate %")
    save(fig, "18_scatter_third_down_vs_scoring")


def plot_scatter_sack_vs_third_down():
    def_pd = load("passing_down", "defense")[["team","sack_pct"]]
    def_td = load("third_down",   "defense")[["team","conv_pct"]]
    df = def_pd.merge(def_td, on="team")
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter(ax, df["sack_pct"], df["conv_pct"], df["team"],
            "Passing Down Sack % vs 3rd Down Conversion % Allowed (Defense)",
            "Sack % on Passing Downs", "3rd Down Conversion % Allowed")
    save(fig, "19_scatter_sack_vs_third_down")


def plot_scatter_run_stuff_vs_early_down():
    def_ed = load("early_down", "defense")[["team","run_stuff_pct","success_rt"]]
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter(ax, def_ed["run_stuff_pct"], def_ed["success_rt"], def_ed["team"],
            "Run Stuff % vs Early Down Success Rate Allowed (Defense)",
            "Run Stuff %", "Early Down Success Rate Allowed %")
    save(fig, "20_scatter_run_stuff_vs_early_down")


def plot_scatter_turnovers_vs_pts():
    def_to  = load("third_down",       "defense")[["team","turnovers"]]
    def_fin = load("finishing_drives", "defense")[["team","pts_per_drive"]]
    df = def_to.merge(def_fin, on="team")
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter(ax, df["turnovers"], df["pts_per_drive"], df["team"],
            "3rd Down Turnovers Forced vs Points per Drive Allowed (Defense)",
            "Turnovers Forced on 3rd Down", "Points per Drive Allowed")
    save(fig, "21_scatter_turnovers_vs_pts")


def main():
    print(f"Saving ranking charts to {OUT}/")
    print("--- Bar chart groups ---")
    plot_early_down_defense()
    plot_finishing_drives_defense()
    plot_fourth_down_offense()
    plot_turnovers_group()
    print("--- Scatter plots ---")
    plot_scatter_early_down_vs_scoring()
    plot_scatter_field_pos_vs_pts()
    plot_scatter_third_down_vs_scoring()
    plot_scatter_sack_vs_third_down()
    plot_scatter_run_stuff_vs_early_down()
    plot_scatter_turnovers_vs_pts()
    print("Done.")


if __name__ == "__main__":
    main()
