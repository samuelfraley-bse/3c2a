# Analyst Dashboard Spec v1

Structure for a click-through analyst dashboard: tabs, metrics, and filters. This is a **content spec, not an implementation** — no dashboard tool has been chosen yet (see `LOGS.md` for the tooling discussion). The goal is to lock down what the dashboard shows before deciding how it's built.

## Why this exists

The weekly coach report (`report_data.py`/`report_build.py`) automates one fixed, opinionated slice of these metrics into a `.docx`. This dashboard is the opposite: a way to freely browse, filter, and sort the same underlying data yourself, team by team, situation by situation — the tool for fact-checking the report's numbers and for exploring questions the report doesn't ask. Both sit on top of the exact same metric definitions in `METRICS.md`; neither should ever invent its own formula for something the other already computes.

## Tab hierarchy

```
Team Offense
  Season
    Passing   (one row per team)
    Rushing   (one row per team)
  Game
    Passing   (one row per team per game)
    Rushing   (one row per team per game)
Team Defense
  Season
    Passing   (one row per team)
    Rushing   (one row per team)
  Game
    Passing   (one row per team per game)
    Rushing   (one row per team per game)
```

8 tabs total. **Season and Game are genuinely different row grains, not the same query with a filter toggled:**

- **Season tab** — `GROUP BY team` only, one row per team. Applying a `week` filter still collapses to one row per team; it just changes *which plays feed the aggregation* (e.g. "season totals through week 5" instead of the full season). The grain never changes.
- **Game tab** — `GROUP BY team, game_id`, one row per team **per game**. Applying a `week` filter changes *which game-rows are shown* (narrows the list), it doesn't change the grain — each visible row is still exactly one game. Game-grain rows also carry an `opponent` column (the other team in that specific game) so it's clear who played whom — this has no equivalent on Season rows, since a team faces a different opponent every week.

Both tabs share the same filter set and the same metric formulas; they differ only in whether `game_id` (and `opponent`) is part of the `GROUP BY`/`SELECT`.

Offense tabs group by `offense`; Defense tabs group by `defense` (i.e. Defense tabs show what opponents did *against* that team — same play data, opposite grouping column).

## Filters (apply to all 8 tabs)

All of these already exist as columns on `v_play_context_current` — no new schema needed:

| Filter | Column | Notes |
|---|---|---|
| Season | `season` | required, single-select |
| Week | `week` | optional; none selected = season rollup / all games, one selected = single game or season-to-date |
| Offense team | `offense` | pins to one team; on Defense tabs this narrows to "defense performance against this specific opponent" |
| Defense team | `defense` | mirror of the above |
| Quarter | `quarter` | optional, multi-select (1–4/OT) |
| Score margin | `score_margin` / `score_margin_bucket` | optional; the bucket (`tied`, `one_score_lead`, `two_score_deficit`, etc. — defined in `METRICS.md`) is probably the more usable filter than a raw numeric range |
| Drive number | `drive_id` | **resolved**: this is the single sequential counter per **game** (0, 1, 2, ... shared across both teams' possessions, not reset per team) — used as-is, no transformation needed. Filtering "drive number = 3" means "whichever team had the game's 3rd drive," not "this team's own 3rd possession." |
| Down | `down` | optional, multi-select (1–4) |
| Distance | `distance` / `distance_bucket` | optional; `distance_bucket` (`short`/`medium`/`long`) is the easier filter, but exact `distance` should stay available too (e.g. "3rd-and-short" vs. "exactly 3rd-and-2") |

`games` (count of distinct `game_id` among the filtered plays) is always shown as a column on every tab — sample size shrinks fast once quarter/score-margin/down/distance filters stack up, and that needs to stay visible.

## Passing tab columns (Offense and Defense)

Same formulas already established in `v_team_season_offense_ranked_current`/`_defense_ranked_current` (`METRICS.md` is the canonical source for these — never redefine them here), computed as a filtered aggregation instead of a static full-season one:

`team_name, games, pass_att, pass_comp, comp_pct, pass_yds, pass_ypa, pass_td, pass_int, dropbacks, sacks, sack_rate, pass_success_rate, pass_explosive_rate, pass_comp_10_plus, pass_comp_20_plus, passer_rating`

`sack_rate` = `sacks / dropbacks` (not `sacks / pass_att` — `dropbacks` already includes sacks per this project's own `is_dropback` convention). Lower is better on Offense tabs, higher is better on Defense tabs (forcing more sacks).

`pass_td`/`rush_td` exclude any play where `is_defensive_td = true` — a fumble recovered and returned for a score by the defense must not be miscredited as the offense's own touchdown (this was a real bug, found and fixed; see `LOGS.md` and `METRICS.md`'s `pass_td` entry).

## Rushing tab columns (Offense and Defense)

`team_name, games, rush_att, rush_yds, rush_ypa, rush_td, rush_success_rate, rush_explosive_rate, run_stuff_rate, rush_10_plus, rush_20_plus`

On the Defense tabs, drop the `opp_` prefix used in the DB views — the tab itself is already labeled "Team Defense," so plain column names read more clearly.

## Rank column

One column, first position (pinned, alongside Team), showing which row is **best** by whatever column the table is currently sorted by — 1 is always the best team at that metric, regardless of whether you sorted ascending or descending. Sorting `pass_int` ascending, for example, puts the team with the *fewest* interceptions at Rank 1, even though that row then sits at the bottom of the visible (ascending) list — rank means "how good is this team here," not "row position."

This requires knowing each metric's direction of "better" (higher vs. lower), which flips between Offense and Defense tabs for the same column name (`pass_yds` is higher-is-better on Offense — yards gained — but lower-is-better on Defense — yards allowed). `dashboard_data.py::OFFENSE_METRIC_DIRECTION` / `metric_direction_for_side()` hold this, ported directly from the direction choices already encoded in the existing `RANK()` columns in `db.py`'s ranked views — not reinvented. Columns with no direction (team name, game id, week) just fall back to plain row position.

The existing `<metric>_rank` window-function columns in `v_team_season_offense_ranked_current` etc. stay as they are for the static docx report, where there's no interactivity to hang a dynamic rank off of — the dashboard doesn't reuse them.

## Query shape (for whichever tool ends up implementing this)

Every tab is one parameterized query against `v_play_context_current`. Season and Game tabs differ only in `GROUP BY`:

```sql
-- Season tab (one row per team):
SELECT team_name, games, <passing or rushing columns...>
FROM v_play_context_current
WHERE season = ?
  AND (? IS NULL OR week = ?)
  AND (? IS NULL OR offense = ?)
  AND (? IS NULL OR defense = ?)
  AND (? IS NULL OR quarter = ?)
  AND (? IS NULL OR score_margin_bucket = ?)
  AND (? IS NULL OR drive_id = ?)
  AND (? IS NULL OR down = ?)
  AND (? IS NULL OR distance_bucket = ?)
GROUP BY offense  -- or `defense` for Defense tabs

-- Game tab (one row per team per game): identical WHERE clause, `game_id` added to GROUP BY:
-- ... GROUP BY offense, game_id  -- or `defense, game_id` for Defense tabs
```

This is the same shape already used by `v_team_game_offense_current`'s inner subquery (groups by `offense, game_id`) and `v_team_season_offense_current` (groups by `offense` alone) — just parameterized, with the extra filters added, and computed on demand instead of materialized as a fixed view. Nothing here requires new database schema; it's a query template a dashboard backend builds dynamically from whichever filters are active.

## Explicitly out of scope for v1

- Any dashboard tool/framework choice (Streamlit, a plain script, a BI tool, etc.) — separate decision, see `LOGS.md`.
- PPG and any combined (non-split) pass+rush metrics.
- Team Leaders (`player_lineup_stats`) tabs — not part of this spec; can be added as a 9th/10th tab later using the same filter pattern if useful.
- Editing/annotating data from the dashboard — this is a read-only view over the existing views.
