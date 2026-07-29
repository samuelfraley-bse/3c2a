"""
What increases the odds a drive ends in a score?

Logistic regression (primary, interpretable odds ratios) + XGBoost (secondary,
cross-check for nonlinear/ranking disagreement) on drive-level features, pooled
across all 3 seasons in the DB (2023-24, 2024-25, 2025-26).

Target: is_scoring_drive (any TD or made FG)

Features (drive-level, offense side):
  start_from_own    - starting field position, yards from own goal (0-100, higher=better).
                       The only feature here that's genuinely knowable BEFORE the drive
                       happens; everything else below is computed from plays within the
                       drive itself (including whichever play ended it), so this is a
                       descriptive "what characterizes scoring drives" model, not a
                       true pre-snap predictive one.
  n_explosive       - COUNT of explosive plays this drive (rush >=10 or pass >=15).
                       Used as a count rather than a rate or binary: ~50% of drives have
                       zero, ~30% have exactly one, ~20% have two or more, so there's real
                       information in "how many," not just "any."
  pass_rate         - % of plays that were a pass
  comp_rate         - completions / attempts
  any_sack          - was the offense sacked at least once this drive (binary; ~86% of
                       drives have 0 sacks, ~14% have exactly 1, 2+ is rare enough that a
                       count buys little over binary)
  neg_play_rate     - % of ALL plays (rush + pass) gaining <= 0 yards (replaces the old
                       rush-only "stuff rate" with a broader, play-type-agnostic version)
  off_penalty       - was a penalty called ON THE OFFENSE during the drive. Resolved from
                       the raw `penalty_team` abbreviation to a canonical team name via
                       exact/startswith/first-word matching against the 67 known team
                       names, with a small manual lookup for irregular acronyms (ARC, CCSF,
                       LMC, etc.). ~99.8% of penalty plays resolve; the rest (ambiguous
                       "SANT*" tokens, a few rare typos) are dropped as unresolved.

Outputs:
  Console: logistic regression odds ratios (raw + standardized) + XGBoost importance
  analysis/showcase/scoring_drive_model.png - standardized odds ratio forest plot

Usage: python analysis/model_scoring_drives.py
"""

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm
import matplotlib.pyplot as plt
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

DB_PATH = "duckdb_pipeline/data/foothill.duckdb"
OUT_PNG = "analysis/showcase/scoring_drive_model.png"
SEASONS = ("2023-24", "2024-25", "2025-26")

# manual overrides for penalty_team acronyms that don't algorithmically resolve
# to a canonical team name (verified against the 67-team roster; ~4% of tokens)
PENALTY_TEAM_MANUAL = {
    "CCSF": "San Francisco", "LMC": "Los Medanos", "DVC": "Diablo Valley",
    "WEST HIL": "West Hills", "COD": "Desert", "ARC": "American River",
    "ECC": "El Camino", "CSM": "San Mateo", "MSJC": "Mt. San Jacinto",
    "SWC": "Southwestern", "SRJC": "Santa Rosa", "FCC": "Fresno City",
    "VCTV": "Victor Valley", "WHC": "West Hills", "SJD": "San Joaquin Delta",
    "RCC": "Riverside", "SBCC": "Santa Barbara", "SDMESA": "San Diego Mesa",
    "SANDIEGO": "San Diego Mesa", "COR": "Redwoods", "CABNEW": "Cabrillo",
    "FRC": "Feather River", "MPC": "Monterey Peninsula", "WLAC": "West LA",
    "CCC": "Contra Costa", "SANTAROS": "Santa Rosa", "LAPIERCE": "LA Pierce",
    "SMC": "Santa Monica", "SJCC": "San Jose", "AVC": "Antelope Valley",
    "SBV": "San Bernardino Valley", "SJC": "San Jose",
    "FEATHERR": "Feather River", "LASW": "LA Southwest", "SANFRANC": "San Francisco",
    "MTSANJAC": "Mt. San Jacinto", "ELCO": "El Camino", "WESTLA": "West LA",
    "CMPTN": "Compton", "LAV": "LA Valley", "LAP": "LA Pierce", "CHFY": "Chaffey",
    "AHC": "Allan Hancock", "GOLDENWE": "Golden West", "SBVC": "San Bernardino Valley",
    "VVC": "Victor Valley", "GWC": "Golden West", "SAC CITY": "Sacramento City",
    "PCC": "Pasadena City", "SJDC": "San Joaquin Delta", "PSDNA": "Pasadena City",
    "SANJOAQU": "San Joaquin Delta", "SCC": "Sacramento City", "ORANGECO": "Orange Coast",
    "MSAC": "Mt. San Antonio",
}

con = duckdb.connect(DB_PATH, read_only=True)

teams = sorted(con.execute(
    """
    select distinct offense as t from v_drives_current where offense is not null and offense != ''
    union select distinct defense from v_drives_current where defense is not null and defense != ''
    """
).fetchdf()["t"].tolist())

def resolve_penalty_team(token):
    if pd.isna(token):
        return None
    t = str(token).upper().strip()
    if t in PENALTY_TEAM_MANUAL:
        return PENALTY_TEAM_MANUAL[t]
    exact = [team for team in teams if team.upper() == t]
    if exact:
        return exact[0]
    starts = [team for team in teams if team.upper().startswith(t)]
    if len(starts) == 1:
        return starts[0]
    firstword = [team for team in teams if team.upper().split()[0] == t]
    if len(firstword) == 1:
        return firstword[0]
    return None  # unresolved / ambiguous (e.g. "SANT*" matches 4 Santa-* teams)

plays = con.execute(
    """
    select game_id, drive_id, offense, play_type, yards_gained,
           is_sack, is_dropback, is_attempt, completion, is_penalty, penalty_team
    from v_plays_current
    where season in ('2023-24','2024-25','2025-26')
      and offense is not null and offense != ''
    """
).fetchdf()

drives = con.execute(
    """
    select season, game_id, drive_id, offense, start_yardline_100,
           scrimmage_plays, is_scoring_drive
    from v_drives_current
    where season in ('2023-24','2024-25','2025-26')
      and offense is not null and offense != ''
    """
).fetchdf()
drives["start_from_own"] = 100 - drives["start_yardline_100"]
drives = drives[drives["start_from_own"].between(0, 100)]

scrim = plays[plays["play_type"].isin(["rush", "pass"])].copy()

def agg_drive(g):
    rush = g[g["play_type"] == "rush"]
    pass_ = g[g["play_type"] == "pass"]
    dropbacks = pass_[pass_["is_dropback"].fillna(False) | pass_["is_sack"].fillna(False)]
    attempts = pass_[pass_["is_attempt"].fillna(False)]
    explosive = (((g["play_type"] == "rush") & (g["yards_gained"] >= 10))
                 | ((g["play_type"] == "pass") & (g["yards_gained"] >= 15)))
    return pd.Series({
        "n_explosive": explosive.sum(),
        "pass_rate": (g["play_type"] == "pass").mean(),
        "comp_rate": attempts["completion"].fillna(False).mean() if len(attempts) else 0.0,
        "any_sack": int(pass_["is_sack"].fillna(False).any()),
        "neg_play_rate": (g["yards_gained"] <= 0).mean(),
    })

drive_feats = scrim.groupby(["game_id", "drive_id", "offense"]).apply(agg_drive, include_groups=False).reset_index()

pen_plays = plays[plays["is_penalty"].fillna(False)].copy()
pen_plays["resolved_team"] = pen_plays["penalty_team"].apply(resolve_penalty_team)
n_pen_total = pen_plays["penalty_team"].notna().sum()
n_pen_resolved = pen_plays["resolved_team"].notna().sum()
print(f"Penalty team resolution: {n_pen_resolved:,}/{n_pen_total:,} ({n_pen_resolved/n_pen_total*100:.1f}%)")

pen_plays["off_pen_hit"] = pen_plays["resolved_team"] == pen_plays["offense"]
off_pen = pen_plays.groupby(["game_id", "drive_id", "offense"])["off_pen_hit"].any().reset_index()
off_pen.columns = ["game_id", "drive_id", "offense", "off_penalty"]

df = drives.merge(drive_feats, on=["game_id", "drive_id", "offense"], how="left")
df = df.merge(off_pen, on=["game_id", "drive_id", "offense"], how="left")
df["off_penalty"] = df["off_penalty"].fillna(False).astype(int)
df["is_scoring_drive"] = df["is_scoring_drive"].astype(int)

FEATURES = ["start_from_own", "n_explosive", "pass_rate", "comp_rate", "any_sack", "neg_play_rate", "off_penalty"]
df = df.dropna(subset=FEATURES + ["is_scoring_drive"])
df[FEATURES] = df[FEATURES].astype(float)
print(f"n drives = {len(df):,}  (scoring = {df['is_scoring_drive'].sum():,}, "
      f"{df['is_scoring_drive'].mean()*100:.1f}%)")

# ── correlation / multicollinearity check ───────────────────────────────────
corr = df[FEATURES].corr()
print("\nHighest pairwise correlations among features:")
pairs = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool)).stack().sort_values(key=abs, ascending=False)
print(pairs.head(8).to_string())

# ── logistic regression (raw scale, for real-world odds ratios) ────────────
X_raw = sm.add_constant(df[FEATURES])
y = df["is_scoring_drive"]
logit_raw = sm.Logit(y, X_raw).fit(disp=0)

# ── logistic regression (standardized, for ranking relative importance) ────
X_std = df[FEATURES].copy()
means, stds = X_std.mean(), X_std.std()
X_std = (X_std - means) / stds
X_std = sm.add_constant(X_std)
logit_std = sm.Logit(y, X_std).fit(disp=0)

results = pd.DataFrame({
    "raw_coef": logit_raw.params.drop("const"),
    "raw_p": logit_raw.pvalues.drop("const"),
    "std_coef": logit_std.params.drop("const"),
    "std_p": logit_std.pvalues.drop("const"),
})
results["odds_ratio_raw"] = np.exp(results["raw_coef"])
results["odds_ratio_per_1sd"] = np.exp(results["std_coef"])
results = results.sort_values("std_coef", key=abs, ascending=False)

pd.set_option("display.width", 140)
print(f"\nLogistic regression (n={len(df):,}, pseudo-R2={logit_raw.prsquared:.3f})")
print(results[["odds_ratio_per_1sd", "odds_ratio_raw", "raw_p"]].round(4).to_string())

# ── XGBoost cross-check ─────────────────────────────────────────────────────
X_train, X_test, y_train, y_test = train_test_split(
    df[FEATURES], y, test_size=0.2, random_state=42, stratify=y
)
xgb = XGBClassifier(
    n_estimators=200, max_depth=3, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, eval_metric="logloss", random_state=42,
)
xgb.fit(X_train, y_train)
auc = roc_auc_score(y_test, xgb.predict_proba(X_test)[:, 1])
xgb_importance = pd.Series(xgb.feature_importances_, index=FEATURES).sort_values(ascending=False)

print(f"\nXGBoost holdout AUC: {auc:.3f}")
print("XGBoost feature importance (gain-normalized):")
print(xgb_importance.round(3).to_string())

logit_rank = results["std_coef"].abs().rank(ascending=False)
xgb_rank = xgb_importance.rank(ascending=False)
rank_compare = pd.DataFrame({"logit_rank": logit_rank, "xgb_rank": xgb_rank.reindex(logit_rank.index)})
print("\nRank agreement (logistic |std coef| vs. XGBoost importance):")
print(rank_compare.sort_values("logit_rank").to_string())

# ── plot: standardized odds ratio forest plot ───────────────────────────────
plot_df = results.copy()
plot_df["label"] = plot_df.index
plot_df = plot_df.sort_values("odds_ratio_per_1sd")

fig, ax = plt.subplots(figsize=(9, 6.5))
colors = ["#2a78d6" if v >= 1 else "#e34948" for v in plot_df["odds_ratio_per_1sd"]]
ax.scatter(plot_df["odds_ratio_per_1sd"], plot_df["label"], s=90, c=colors, zorder=3)
ax.axvline(1.0, color="#898781", lw=1.2, ls="--", zorder=1)
for _, row in plot_df.iterrows():
    sig = "" if row["std_p"] < 0.05 else "  (n.s.)"
    ax.text(row["odds_ratio_per_1sd"] + 0.03, row["label"], f"{row['odds_ratio_per_1sd']:.2f}x{sig}",
            va="center", fontsize=8.5)
ax.set_xlabel("Odds Ratio per +1 SD of the feature\n(>1 = raises odds of scoring, <1 = lowers it)", fontsize=10)
ax.set_title(f"What Moves the Odds a Drive Scores?\nLogistic regression, {len(df):,} drives, CA JC 2023-24 to 2025-26",
             fontsize=12.5, fontweight="bold")
plt.tight_layout()
plt.savefig(OUT_PNG, bbox_inches="tight", dpi=150)
print(f"\nSaved {OUT_PNG}")
