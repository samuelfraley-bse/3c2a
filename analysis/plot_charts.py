"""
Generate Foothill 2025-26 season charts as PNG files.
Uses United Serif fonts and Foothill color scheme.
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import os

# --- Register United Serif fonts ---
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

# --- Foothill colors ---
RED    = "#A61E2F"
BLACK  = "#000000"
GOLD   = "#FFC82E"
LIGHT  = "#F2E7D1"
GRAY   = "#D0D1CE"

DATA_DIR = "outputs/2025-26/chart_data"
OUT_DIR  = "outputs/2025-26/charts"
os.makedirs(OUT_DIR, exist_ok=True)


def style_ax(ax, title, xlabel="", ylabel=""):
    ax.set_title(title, fontproperties=FONT_HEAVY, fontsize=14, color=BLACK, pad=10)
    ax.set_xlabel(xlabel, fontfamily=FONT_NAME, fontsize=10, color=BLACK)
    ax.set_ylabel(ylabel, fontfamily=FONT_NAME, fontsize=10, color=BLACK)
    ax.tick_params(colors=BLACK, labelsize=9)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(FONT_NAME)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRAY)
    ax.spines["bottom"].set_color(GRAY)
    ax.set_facecolor("white")
    ax.yaxis.grid(True, color=GRAY, linewidth=0.5, linestyle="--")
    ax.set_axisbelow(True)


def save(fig, name):
    path = f"{OUT_DIR}/{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {name}.png")


def load(fname):
    return pd.read_csv(f"{DATA_DIR}/{fname}").sort_values("game_order")


# ---------------------------------------------------------------------------
# Game-by-game line charts
# ---------------------------------------------------------------------------

def plot_success_rate():
    df = load("chart_game_success_rate.csv")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["opp_abbr"], df["off_success"], color=RED,   marker="o", linewidth=2, label="Offense")
    ax.plot(df["opp_abbr"], df["def_success"], color=BLACK, marker="s", linewidth=2, label="Defense Faced")
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "Success Rate by Game", ylabel="Success Rate %")
    save(fig, "01_success_rate_by_game")


def plot_explosive_rate():
    df = load("chart_game_explosive_rate.csv")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["opp_abbr"], df["off_exp_pct"], color=RED,   marker="o", linewidth=2, label="Offense")
    ax.plot(df["opp_abbr"], df["def_exp_pct"], color=BLACK, marker="s", linewidth=2, label="Defense Faced")
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "Explosive Play Rate by Game", ylabel="Explosive %")
    save(fig, "02_explosive_rate_by_game")


def plot_stuff_rate():
    df = load("chart_game_stuff_rate.csv")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["opp_abbr"], df["off_stuff_pct"], color=RED,   marker="o", linewidth=2, label="Offense Stuffed")
    ax.plot(df["opp_abbr"], df["def_stuff_pct"], color=BLACK, marker="s", linewidth=2, label="Defense Stuffed Opponent")
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "Run Stuff Rate by Game", ylabel="Stuff %")
    save(fig, "03_stuff_rate_by_game")


def plot_third_down():
    df = load("chart_game_third_down.csv")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["opp_abbr"], df["off_conv_pct"], color=RED,   marker="o", linewidth=2, label="Offense")
    ax.plot(df["opp_abbr"], df["def_conv_pct"], color=BLACK, marker="s", linewidth=2, label="Defense Faced")
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "3rd Down Conversion Rate by Game", ylabel="Conversion %")
    save(fig, "04_third_down_by_game")


def plot_early_down_rush():
    df = load("chart_game_early_down_rush.csv")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["opp_abbr"], df["off_rush_pct"], color=RED,   marker="o", linewidth=2, label="Offense")
    ax.plot(df["opp_abbr"], df["def_rush_pct"], color=BLACK, marker="s", linewidth=2, label="Defense Faced")
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "Early Down Rush Rate by Game", ylabel="Rush %")
    save(fig, "05_early_down_rush_by_game")


def plot_passing_down_pass():
    df = load("chart_game_passing_down_pass.csv")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["opp_abbr"], df["off_pass_pct"], color=RED,   marker="o", linewidth=2, label="Offense")
    ax.plot(df["opp_abbr"], df["def_pass_pct"], color=BLACK, marker="s", linewidth=2, label="Defense Faced")
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "Passing Down Pass Rate by Game", ylabel="Pass %")
    save(fig, "06_passing_down_pass_by_game")


def plot_avg_start_pos():
    df = load("chart_game_avg_start_pos.csv")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["opp_abbr"], df["off_avg_start"], color=RED,   marker="o", linewidth=2, label="Foothill offense avg start")
    ax.plot(df["opp_abbr"], df["def_avg_start"], color=BLACK, marker="s", linewidth=2, label="Opponent offense avg start")
    ax.set_ylim(0, 100)
    ticks = [10, 20, 30, 40, 50, 60, 70, 80, 90]
    labels = ["OWN 10","OWN 20","OWN 30","OWN 40","50","OPP 40","OPP 30","OPP 20","OPP 10"]
    ax.set_yticks(ticks)
    ax.set_yticklabels(labels)
    ax.axhline(50, color=GRAY, linewidth=0.8, linestyle="--")
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "Avg Drive Starting Position by Game", ylabel="Field Position (higher = deeper in opp. territory)")
    save(fig, "07_avg_start_pos_by_game")


def plot_penalty_yards():
    df = load("chart_game_penalty_yards.csv")
    x = range(len(df))
    width = 0.35
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([i - width/2 for i in x], df["off_penalty_yds"], width, color=RED,   label="Offense")
    ax.bar([i + width/2 for i in x], df["def_penalty_yds"], width, color=BLACK, label="Defense")
    ax.set_xticks(list(x))
    ax.set_xticklabels(df["opp_abbr"])
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "Penalty Yards by Game", ylabel="Yards")
    save(fig, "08_penalty_yards_by_game")


def plot_half_success():
    df = load("chart_game_half_success.csv")
    off = df[df["side"] == "off"]
    dff = df[df["side"] == "def"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    for ax, data, title in [
        (axes[0], off, "Offense — 1st vs 2nd Half Success Rate"),
        (axes[1], dff, "Defense — 1st vs 2nd Half Success Rate"),
    ]:
        ax.plot(data["opp_abbr"], data["first_half_succ"],  color=RED,   marker="o", linewidth=2, label="1st Half")
        ax.plot(data["opp_abbr"], data["second_half_succ"], color=BLACK, marker="s", linewidth=2, label="2nd Half")
        ax.legend(prop=FONT_MEDIUM, frameon=False)
        style_ax(ax, title, ylabel="Success Rate %")
    fig.tight_layout()
    save(fig, "09_half_success_by_game")


# ---------------------------------------------------------------------------
# Season aggregate charts
# ---------------------------------------------------------------------------

def plot_success_by_down():
    df = pd.read_csv(f"{DATA_DIR}/chart_success_by_down.csv")
    off = df[df["side"] == "offense"]
    dff = df[df["side"] == "defense"]
    x = [1, 2, 3, 4]
    width = 0.35
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar([i - width/2 for i in x], off["success_pct"], width, color=RED,   label="Offense")
    ax.bar([i + width/2 for i in x], dff["success_pct"], width, color=BLACK, label="Defense Faced")
    ax.set_xticks(x)
    ax.set_xticklabels(["1st Down", "2nd Down", "3rd Down", "4th Down"])
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "Success Rate by Down", ylabel="Success Rate %")
    save(fig, "10_success_by_down")


def plot_conv_by_distance():
    df = pd.read_csv(f"{DATA_DIR}/chart_conv_by_distance.csv")
    off = df[df["side"] == "offense"]
    dff = df[df["side"] == "defense"]
    x = range(len(off))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar([i - width/2 for i in x], off["conv_pct"], width, color=RED,   label="Offense")
    ax.bar([i + width/2 for i in x], dff["conv_pct"], width, color=BLACK, label="Defense Faced")
    ax.set_xticks(list(x))
    ax.set_xticklabels(off["distance"].tolist())
    ax.legend(prop=FONT_MEDIUM, frameon=False)
    style_ax(ax, "3rd/4th Down Conversion % by Yards to Go", ylabel="Conversion %")
    save(fig, "11_conv_by_distance")


def main():
    print(f"Saving charts to {OUT_DIR}/")
    plot_success_rate()
    plot_explosive_rate()
    plot_stuff_rate()
    plot_third_down()
    plot_early_down_rush()
    plot_passing_down_pass()
    plot_avg_start_pos()
    plot_penalty_yards()
    plot_half_success()
    plot_success_by_down()
    plot_conv_by_distance()
    print("Done.")


if __name__ == "__main__":
    main()
