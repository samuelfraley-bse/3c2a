# Metrics Spec v1

Canonical metrics and filters spec for the current `plays`-driven analytics layer.

This is a broad draft, but each metric and filter is labeled with a support state:

- `supported_now`
- `derived_next`
- `future_modeling`

The current goal is a stable **team offense / team defense automated report**. A later dashboard should sit on top of the same metric definitions and derived views rather than inventing its own logic.

## Foundations

### Perspective

All team metrics must be computed from an explicit perspective:

- `offense`
  - rows where the selected team is `plays.offense`
- `defense`
  - rows where the selected team is `plays.defense`

Defense metrics are mirror metrics derived from opponent production against the selected team.

### Current core play flags

These are established project primitives and should be treated as the base football vocabulary:

- `is_dropback`
  - `supported_now`
  - pass-play context, including sacks
- `is_pass_attempt`
  - `supported_now`
  - official forward pass attempts only
- `is_rush_attempt`
  - `supported_now`
  - official team rushing attempts, including sacks
- `is_sack`
  - `supported_now`
- `is_interception`
  - `supported_now`
- `is_td`
  - `supported_now`
  - offensive touchdown only; see `is_defensive_td` below for the defense's mirror
- `is_conversion`
  - `supported_now`
- `is_safety`
  - `supported_now`
  - parsed directly from raw play text; 2 points to the defense
- `is_defensive_td`
  - `supported_now`
  - true for a defensive/return touchdown; 6 points to the defense. Two sources feed this, one parse-time and one view-level:
    - interception-return (pick-six): unambiguous from raw text alone (`is_interception` + `touchdown`), resolved directly on the `plays` row at parse time
    - fumble-return: the parse-time suppression of the offensive `is_td` flag can be wrong when the recovering team's raw abbreviation doesn't textually match the defense's canonical name (e.g. `MSJC-FB` for `Mt. San Jacinto`), or when the recovering player's name gets swept into the stored `fumble_recovered_by` value by the fumble regex (e.g. `FULLERTO Ethan`). `v_play_context_current` resolves this case using the field-position crosswalk (`field_position_crosswalk`, matched as a prefix since `fumble_recovered_by` can carry that trailing junk) rather than trusting the parse-time heuristic; it falls back to the stored `is_td` only when no crosswalk entry exists yet for that game
  - `plays.is_defensive_td` (the stored column) only covers the pick-six case; `v_play_context_current.is_defensive_td` (the view column) is the complete, resolved version — same bronze/silver-vs-gold pattern as `plays.field_position` (raw) vs `v_play_context_current.field_position` (crosswalk-resolved)
  - remaining known gap: blocked-kick-return touchdowns (blocked punt/FG returned for a score) are not covered by either source; confirmed real but rare (~5 instances across the season)

### Success rate

Project default success-rate rule:

- `1st down`
  - success if `yards_gained >= 50%` of yards-to-go
- `2nd down`
  - success if `yards_gained >= 70%` of yards-to-go
- `3rd down`
  - success if `yards_gained >= 100%` of yards-to-go
- `4th down`
  - success if `yards_gained >= 100%` of yards-to-go

Support status:

- `success_rate`
  - `derived_next`
- `is_success`
  - `derived_next`

Default application:

- pass attempts
- rush attempts

Possible later expansion:

- dropback-level success, if the report explicitly wants sacks included in the context denominator

### Explosives

Project default explosive thresholds:

- `explosive_rush`
  - `yards_gained >= 10`
- `explosive_pass`
  - completed pass with `yards_gained >= 20`
- `is_explosive`
  - true when the play meets the explosive rule for its play family

Support status:

- `explosive_rush`
  - `derived_next`
- `explosive_pass`
  - `derived_next`
- `is_explosive`
  - `derived_next`

### Field position

Primary analyst-facing field-position filter should be normalized:

- `yardline_100`
  - `derived_next`
- `field_zone`
  - `derived_next`

Raw source token handling:

- `plays.field_position`
  - `supported_now`
  - keep for debugging and parser audits
- raw token is **not** the main analyst-facing field-position filter

`yardline_100` should be built from the derived field-position layer, not from raw token text alone.

### Down/distance situations

Project definitions, ported verbatim from the old CSV pipeline's `analysis/helpers.py::add_flags()`:

- `is_passing_down`
  - `supported_now`
  - `(down = 2 AND distance >= 8) OR (down IN (3, 4) AND distance >= 5)`
- `is_early_down`
  - `supported_now`
  - `down IN (1, 2) AND NOT is_passing_down`

These intentionally **overlap** with `down = 3` / `down = 4` — a 3rd-and-8 is both `is_passing_down` and third down. Don't force artificial mutual exclusivity onto these categories; they're independent lenses on the same play, matching how the old pipeline treated them.

`v_team_game_situation_offense_current` / `_defense_current` and their season rollups (`v_team_season_situation_offense_current` / `_defense_current`) expose one row per `(team, game, situation)` via `UNION ALL` across `situation IN ('early_down', 'passing_down', 'third_down', 'fourth_down')`, reusing the same aggregate column shape (pass/rush attempts, yards, successes, explosives, stuffed runs, sacks) as the non-situational `v_team_game_offense_current` / `_defense_current`, plus `distance_sum`/`distance_n` (a weighted-average-safe pair, not a pre-averaged `avg_distance`, so season rollups don't average-of-averages).

### Week

Project definition:

- `week`
  - team game order within season
  - not calendar week
  - not source-native

Support status:

- `week`
  - `derived_next`

### Score margin

Project status:

- `score_margin`
  - `supported_now`
  - offense score minus defense score, as of the state entering the play (pre-snap, matching `down`/`distance`/`quarter` semantics elsewhere in this view)
- `score_margin_bucket`
  - `supported_now`
  - buckets: `blowout_lead` (`>= 17`), `two_score_lead` (`9-16`), `one_score_lead` (`1-8`), `tied` (`0`), `one_score_deficit` (`-1 to -8`), `two_score_deficit` (`-9 to -16`), `blowout_deficit` (`<= -17`)

Score state is derived entirely from `plays` itself (no box-score dependency): a play scores 6 for a non-conversion `is_td`, 3 for a made `field_goal`, 1 for a made `pat`, 2 for a made `two_point`, 2 for `is_safety` (to the defense), and 6 for `is_defensive_td` (to the defense, suppressing the offensive 6 for the same play) — attributed to whichever of `schedule_home`/`schedule_away` matches the relevant side, then summed as a running pre-play total per game ordered by `play_id`. See `is_safety`/`is_defensive_td` above for how each is resolved.

Remaining known gap (documented rather than silently wrong):

- **Blocked-kick-return touchdowns are not recorded as scoring events.** A blocked punt or field goal that's returned for a score doesn't fall under either the pick-six or fumble-recovery resolution paths above. Confirmed real (~5 instances found in the season's raw play text) but rare enough that this is deferred rather than blocking the rest of `score_margin`.

This gap leaves `score_margin` permanently short (not just temporarily desynced) for any game where it occurs, until parser support is added.

`v_play_context_current` also exposes the per-play `offense_points`/`defense_points` values that feed the `home_score`/`away_score` window sums above (previously computed internally but not surfaced as columns). These are what `v_team_game_points_current` (see Cross-Team Rankings) sums into points-per-game — no separate scoring logic exists anywhere else in this schema.

### Schedule running record

- `v_schedule_current.wins_entering_game` / `losses_entering_game` / `ties_entering_game`
  - `supported_now`
  - Running overall W/L/T record **entering** each game (not including it), parsed from the raw `schedule.result` text (`"W, 42-7"` / `"L, 7-42"`; future/unplayed games with blank or score-less `result` just don't match `W`/`L`/`T` and contribute 0). Computed the same way as `score_margin`'s pre-play state: a window sum with `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING`.
  - **Known gap**: this is the *overall* record only. There is no per-game conference-game flag anywhere in this pipeline — `v_standings_current`'s `conference_wins`/`conference_losses` come from a separately-scraped season-end totals row, not derived from individual `schedule` rows — so a conference-specific running record entering each game is not derivable without new data (would need a way to classify which scheduled games are conference games).

## Offense Metrics

### Passing offense

- `dropbacks`
  - `supported_now`
  - numerator: count of offensive plays where `is_dropback = true`

- `pass_attempts`
  - `supported_now`
  - numerator: count of offensive plays where `is_pass_attempt = true`

- `completions`
  - `supported_now`
  - numerator: count of offensive plays where `completion = true`

- `completion_pct`
  - `derived_next`
  - formula: `completions / pass_attempts`

- `pass_yards`
  - `supported_now`
  - numerator: sum of offensive `yards_gained` on pass plays that are not sacks and not interceptions

- `pass_td`
  - `supported_now`
  - numerator: count of offensive pass plays where `play_type = 'pass'` and `is_td = true`

- `interceptions`
  - `supported_now`
  - numerator: count of offensive plays where `is_interception = true`

- `yards_per_attempt`
  - `derived_next`
  - formula: `pass_yards / pass_attempts`

- `passing_success_rate`
  - `derived_next`
  - formula: successful pass attempts / pass attempts

- `completions_10_plus`
  - `derived_next`
  - numerator: count of completed passes with `yards_gained >= 10`

- `completions_10_plus_rate`
  - `derived_next`
  - formula: `completions_10_plus / completions`

- `completions_20_plus`
  - `derived_next`
  - numerator: count of completed passes with `yards_gained >= 20`

- `completions_20_plus_rate`
  - `derived_next`
  - formula: `completions_20_plus / completions`

- `sacks`
  - `supported_now`
  - numerator: count of offensive plays where `is_sack = true`

- `sack_rate`
  - `derived_next`
  - formula: `sacks / dropbacks`

- `passer_rating`
  - `supported_now`
  - the **NCAA college** passer-efficiency formula, not the NFL one — the two are unrelated formulas that produce very different numbers for an identical box score, so don't assume "passer rating" means the same thing across sources
  - formula: `(8.4 * pass_yards + 330 * pass_td + 100 * completions - 200 * interceptions) / pass_attempts`
  - unlike the NFL rating, the NCAA formula has no component clamps/caps — it's a single linear expression
  - available at team level on `v_team_game_offense_current` / `_defense_current` (as `passer_rating` / `opp_passer_rating`) and ranked at season level on `v_team_season_offense_ranked_current` / `_defense_ranked_current` (higher-better for offense, lower-better for defense, consistent with every other passing metric in that view)
  - also available per-player on `v_player_game_passing_current` / `v_player_season_passing_current` (see below) — no rank column there, since ranking individual players would need the cross-team player-name crosswalk this deliberately avoids depending on

### Player-level passing (raw-name grouping, no crosswalk)

`v_player_game_passing_current` / `v_player_season_passing_current` group `v_play_context_current` by `(season, run_id, game_id or nothing, team_name, passer)` using the raw `plays.passer` text field directly — no join to a player-identity crosswalk.

This is a meaningfully different reliability posture than a cross-team leaderboard (like the "Team Leaders" section cut from the weekly coach report for exactly this reason):

- **Reliable for**: one team's own passing stats within a season, since the same source repeatedly parses that team's own player names with consistent spelling. A team typically only has 1-2 QBs who take meaningful pass attempts in a season, so raw-name grouping does the right thing without needing full identity resolution.
- **Not reliable for**: deduplicating genuine name-spelling variants for the same player across games (a source-side formatting change would split one player into two rows), or any comparison across teams (different teams' players are never confused with each other, since `team_name` is part of the group key, but this isn't a substitute for a real player-identity system if one is built later).

Status: `supported_now`, with this caveat documented rather than gated behind the unresolved crosswalk work.

### Rushing offense

- `rush_attempts`
  - `supported_now`
  - numerator: count of offensive plays where `is_rush_attempt = true`

- `rush_yards`
  - `supported_now`
  - numerator: sum of offensive `yards_gained` where `is_rush_attempt = true`

- `rush_td`
  - `supported_now`
  - numerator: count of offensive plays where `is_rush_attempt = true` and `is_td = true`

- `yards_per_carry`
  - `derived_next`
  - formula: `rush_yards / rush_attempts`

- `rushes_10_plus`
  - `derived_next`
  - numerator: count of rush attempts with `yards_gained >= 10`

- `rushes_10_plus_rate`
  - `derived_next`
  - formula: `rushes_10_plus / rush_attempts`

- `rushes_20_plus`
  - `derived_next`
  - numerator: count of rush attempts with `yards_gained >= 20`

- `rushes_20_plus_rate`
  - `derived_next`
  - formula: `rushes_20_plus / rush_attempts`

- `rushing_success_rate`
  - `derived_next`
  - formula: successful rush attempts / rush attempts

- `stuffed_runs`
  - `derived_next`
  - numerator: count of rush attempts with `yards_gained <= 0`

- `stuffed_run_rate`
  - `derived_next`
  - formula: `stuffed_runs / rush_attempts`

## Defense Metrics

Defense metrics mirror the same event logic from opponent rows.

### Passing defense

- `opp_dropbacks`
  - `supported_now`
- `opp_pass_attempts`
  - `supported_now`
- `opp_completions`
  - `supported_now`
- `opp_completion_pct`
  - `derived_next`
- `opp_pass_yards`
  - `supported_now`
- `opp_pass_td`
  - `supported_now`
- `opp_interceptions`
  - `supported_now`
  - offense perspective: opponent throws an interception
- `interceptions_forced`
  - `supported_now`
  - same underlying event count from the selected team's defense perspective
- `sacks_forced`
  - `supported_now`
- `opp_passing_success_rate`
  - `derived_next`
- `opp_completions_10_plus`
  - `derived_next`
- `opp_completions_10_plus_rate`
  - `derived_next`
- `opp_completions_20_plus`
  - `derived_next`
- `opp_completions_20_plus_rate`
  - `derived_next`
- `sack_rate_forced`
  - `derived_next`
  - formula: `sacks_forced / opp_dropbacks`

- `opp_passer_rating`
  - `supported_now`
  - mirror of `passer_rating` above (same NCAA formula) computed from opponent passing production; lower is better defensively

### Rushing defense

- `opp_rush_attempts`
  - `supported_now`
- `opp_rush_yards`
  - `supported_now`
- `opp_rush_td`
  - `supported_now`
- `opp_yards_per_carry`
  - `derived_next`
- `opp_rushing_success_rate`
  - `derived_next`
- `opp_rushes_10_plus`
  - `derived_next`
- `opp_rushes_10_plus_rate`
  - `derived_next`
- `opp_rushes_20_plus`
  - `derived_next`
- `opp_rushes_20_plus_rate`
  - `derived_next`
- `stuffed_runs_forced`
  - `derived_next`
  - numerator: opponent rush attempts with `yards_gained <= 0`
- `stuffed_run_rate_forced`
  - `derived_next`
  - formula: `stuffed_runs_forced / opp_rush_attempts`

## Filters

### Supported now / derived next

- `season`
  - `supported_now`
- `week`
  - `derived_next`
  - team game order within season
- `team`
  - `supported_now`
- `opponent`
  - `supported_now`
- `quarter`
  - `supported_now`
- `down`
  - `supported_now`
- `distance`
  - `supported_now`
- `yardline_100`
  - `derived_next`
- `field_zone`
  - `derived_next`
- `is_explosive`
  - `derived_next`
- `is_dropback`
  - `supported_now`
- `score_margin`
  - `supported_now`
- `score_margin_bucket`
  - `supported_now`
- `is_early_down`
  - `supported_now`
- `is_passing_down`
  - `supported_now`

### Derived buckets for the first report layer

- `distance_bucket`
  - `derived_next`
  - `short = 1-3`
  - `medium = 4-6`
  - `long = 7+`

- `field_zone`
  - `derived_next`
  - recommended first-pass buckets:
    - `backed_up`
    - `own_territory`
    - `midfield`
    - `fringe`
    - `red_zone`

Exact yardline cut points should be chosen when `v_play_context_current` is implemented.

### Future filters

- `home_away`
  - `derived_next`
  - available from `games`, but not yet defined as a first report filter
- `clock`
  - `future_modeling`
- `half`
  - `derived_next`
  - possible from quarter once needed
- `late_game_state`
  - `future_modeling`
- `personnel`
  - `future_modeling`
- `participation-based filters`
  - `future_modeling`

## Cross-Team Rankings

For the weekly coach report's rank-annotated tables (e.g. `"1,657 (48th)"`), ranks are computed **live via `RANK() OVER (PARTITION BY season ...)` window functions in the view layer**, not snapshotted into a separate audit table. A cross-team percentile rank is a pure, deterministic function of data that's already frozen per the existing `v_current_*_runs` resolution — recomputing it on every view refresh can't drift out of sync with a metric definition change, and there's no "in-flight" state to protect the way there is for a scrape run. The historical record of what a coach saw in a given week is the saved report file itself (`reports/*.docx`), not a database row.

New ranked views:

- `v_team_season_offense_ranked_current` / `v_team_season_defense_ranked_current`
  - wrap `v_team_season_offense_current` / `_defense_current`, adding rate columns (`pass_pct`, `pass_ypa`, `comp_pct`, `pass_success_rate`, `rush_pct`, `rush_ypa`, `rush_success_rate`, and the `opp_*` mirrors) plus a `<metric>_rank` column per metric, `PARTITION BY season`.
  - Also adds a **combined** (pass + rush, all scrimmage plays) `success_rate`/`explosive_rate` — distinct from the pass-only/rush-only `pass_success_rate`/`rush_success_rate` above, which are each relative to their own attempt count rather than to all scrimmage plays — plus the split `rush_explosive_rate`/`pass_explosive_rate` and `run_stuff_rate` (`stuffed_runs / rush_att`). All ranked (`run_stuff_rate_rank` ASC on offense — fewer of your own rushes stuffed is better; `opp_run_stuff_rate_rank` DESC on defense — stuffing more of the opponent's rushes is better).
- `v_team_season_situation_offense_ranked_current` / `v_team_season_situation_defense_ranked_current`
  - same idea for the situational rollups, `PARTITION BY (season, situation)` so early-down ranks and third-down ranks don't mix pools. Adds `pass_pct`, `rush_pct`, `yards_per_play`, `success_rate`, `explosive_rate` (all ranked) plus `avg_distance` (descriptive context, deliberately **not** ranked — "average yards to go" isn't inherently good or bad).
- `v_team_season_points_current` / `v_team_season_points_ranked_current`
  - `points_scored`/`points_allowed` are summed from `v_play_context_current.offense_points`/`defense_points` across **both** roles a team plays in a game (its own offensive scoring, plus any safety/pick-six/defensive-fumble-TD points it puts up on defense) via a `v_team_game_points_current` view that `UNION ALL`s the offense-role and defense-role attribution — not split by offense/defense like every other team-season view, since points-for and points-against both belong on the same team-game row.
  - `ppg`/`ppg_allowed` (`points_scored`/`points_allowed` divided by `games`), ranked `ppg_rank` DESC / `ppg_allowed_rank` ASC.
- `v_team_season_drives_offense_ranked_current` / `v_team_season_drives_defense_ranked_current`
  - see the new "Drives" section below.

Ranking direction (higher-better vs. lower-better) is ported 1:1 from the old pipeline's per-metric direction dicts (`analysis/table_production.py::add_ranks()`): offense metrics are all higher-better; defense metrics are lower-better except `pass_pct`/`rush_pct`, which the old pipeline kept higher-better/neutral (its own comment calls this inconsistent — "opponent passing more = bad, but neutral stat" — but the *code* still ranked it higher-better; this spec ports the code's actual behavior, not the comment, and treats it as descriptive context rather than a graded stat).

**Scrimmage-play denominator convention:** `pass_pct` and `rush_pct` (and, in the situational views, `yards_per_play`/`success_rate`/`explosive_rate`) are computed against `pass_att + rush_att` ("scrimmage plays"), not the raw `play_count` column, which also includes non-scrimmage rows (punts, kickoffs, PAT/two-point, drive markers). Verified against the live season data: this produces an exact match against the old pipeline's season-aggregate numbers (`44.5%` pass / `60.4%` rush for Foothill 2025-26, matching `analysis/table_production.py`'s output exactly, including the sacks-double-counted-into-both-pass-and-rush convention that pushes the two percentages' sum above 100%).

The situational views (`early_down`/`passing_down`/`third_down`/`fourth_down`) do **not** attempt to reproduce the old `analysis/table_early_down.py` / `table_third_down.py` numbers exactly. Those scripts use an inconsistent, per-script sack convention (a sack silently drops out of *both* the pass and rush numerator while still counting in the denominator) that conflicts with this project's own already-canonical `is_rush_attempt`/`is_pass_attempt` definitions (`is_rush_attempt` includes sacks everywhere else in this schema). This spec applies the canonical convention uniformly instead, which produces situational percentages a few points off from the old pipeline's — an intentional, documented divergence, not a bug.

## Player Lineup Stats (Team Leaders)

Unlike every other metric in this spec, `player_lineup_stats` is **not derived from `plays`** — it's parsed from an official, separately-sourced PrestoSports JSON feed (`raw_lineup_json`'s `players_json` rows; see `LOGS.md`, 2026-07-05, for the discovery narrative and full field legend). It exists specifically to drive the weekly coach report's Team Leaders section (Passing/Rushing/Receiving/Tackles/Sacks) without depending on the unresolved player-name crosswalk that raw `plays.passer`/`rusher`/`receiver` text grouping would need for a cross-team leaderboard — this source comes with a stable `player_id`, jersey number, and class year directly from the conference's own records.

- `player_lineup_stats` / `v_player_lineup_stats_current`
  - `supported_now`
  - One row per player per season, covering every team in the conference in a single parse (the source JSON itself is conference-wide, not per-team).
  - `position_group` (`qb`/`rb`/`wr`/`d`/`k`/`p`/`kr`/`other`) is derived from the player's own raw `position` field via a hardcoded mapping (see `lineup_parse.py::POSITION_GROUP_MAP`) — it's for classification/leaderboard filtering, not a gate on which stat columns get populated. A QB's incidental rushing still lands in `rush_*`.
  - Passing (`qb`): `pass_att`, `pass_comp`, `pass_pct`, `pass_yds`, `pass_ypg`, `pass_ypa`, `pass_td`, `pass_int`, `pass_lg`, `pass_rating` (this `pass_rating` is the source's own NCAA-formula computation — cross-validated this session against this project's independently plays-derived `passer_rating` and found to match exactly for a real player).
  - Rushing: `rush_att`, `rush_yds`, `rush_ypg`, `rush_ypc`, `rush_td`, `rush_lg`, `fumbles`, `fumbles_lost`.
  - Receiving: `rec`, `rec_ypg`, `rec_yds`, `rec_ypc`, `rec_td`, `rec_lg`.
  - Defense: `tackles_solo`, `tackles_ast`, `tackles_total`, `tackles_pg`, `sacks`, `sack_yds`, `tfl`, `tfl_yds`, `forced_fumbles`, `fumble_rec`, `fumble_rec_yds`, `interceptions`, `int_yds`, `pass_breakups`, `blocked_kicks`.
  - Kicking/punting/return categories are **not parsed** — out of scope until a report actually needs them.
  - A player who never recorded a given stat category has `NULL` there (not `0`) — the source's own per-player stats dict is sparse, only including categories a player actually accumulated.

## Drives

`drive_id` has been a column on `plays`/`v_play_context_current` since the parser was first built, but nothing aggregated by it until this pass. All of the below is derived purely from `plays` (no new scraping/data source needed).

- `v_drives_current`
  - `supported_now`
  - One row per drive: `start_yardline_100` (`ARG_MIN(yardline_100, play_id)` — the field position of the drive's first play, using `play_id` as the intra-game chronological key, same convention `game_score_state`'s window already relies on), `scrimmage_plays` (pass/rush attempts only — penalties and punts/kickoffs don't count), `drive_points` (`SUM(offense_points)` for the drive), `is_scoring_drive` (`drive_points > 0`).
  - `is_three_and_out` — **project decision**: `scrimmage_plays <= 3 AND NOT is_scoring_drive`. Covers both a punt after 3-or-fewer snaps and a turnover-on-downs after 3-or-fewer snaps (no punt required); does not require the drive to literally end in a punt.
- `v_team_game_drives_offense_current` / `_defense_current` → season → ranked
  - Offense view groups by `offense AS team_name` (the team's own drives); defense view groups by `defense AS team_name` (drives the team's defense faced). **Deliberately the same column names on both, no `opp_` prefix** — unlike other `opp_*` columns in this schema (where a higher value means worse for the team being described), `drives_three_and_out` on the defense view means drives *forced* into a 3-and-out, which is good, not bad. Reusing the `opp_` convention here would misleadingly imply the opposite.
  - Season views carry forward raw per-game sums (`total_scrimmage_plays`, `total_start_yardline_100`), not pre-averaged per-game rates, so the season rollup is a plain `SUM/SUM` — no average-of-averages recovery step needed, matching the `distance_sum`/`distance_n` weighting discipline already used for `avg_distance` in the situational views.
  - Ranked columns: `avg_start_yardline_100` (offense: higher/closer-to-opponent's-goal is better, ranked DESC; defense: lower/pinning-opponent-back is better, ranked ASC — `yardline_100` convention per `field_zone` elsewhere: higher = closer to the opponent's end zone), `pct_drives_scored` (offense DESC, defense ASC — allowing fewer scoring drives is good), `pct_drives_three_and_out` (offense ASC — fewer is better; defense DESC — forcing more is good).
  - `avg_plays_per_drive` and `plays_per_game`: **no rank column** — tempo has no inherently-better direction, same treatment as `avg_distance`.

## Advanced Metrics

### Line yards

- `line_yards`
  - `derived_next`

This can be documented now because the current data is close enough to support a project-defined estimate, but it is not source truth.

Important constraint:

- if implemented, it must be framed as a **project-defined estimate**
- the attribution rule must be explicitly documented in this file before it is treated as stable

Examples of likely rule families:

- partial credit to OL on early yards
- capped credit on long runs
- separate treatment for stuffed runs

The exact project rule is still open and should be locked before implementation.

### EPA

- `EPA`
  - `future_modeling`

Requires a real expected-points framework with stable pre-play state inputs. It should not be treated as a quick derived stat from the current raw `plays` layer.

### Expected completion rate

- `expected_completion_rate`
  - `future_modeling`

Current schema is not rich enough for a trustworthy xComp model. This would require more contextual features and a trained baseline model.

## Recommended Next Derived Layer

The next derived layer should follow this metrics spec rather than define metrics ad hoc.

### Recommended views

- `v_play_context_current`
  - one row per play
  - adds:
    - `week`
    - `distance_bucket`
    - `yardline_100`
    - `field_zone`
    - `is_success`
    - `explosive_rush`
    - `explosive_pass`
    - `is_explosive`
    - `home_score` / `away_score` (pre-play)
    - `score_margin` / `score_margin_bucket`

- `v_team_game_offense_current`
  - extend the current offense game view with:
    - success counts/rates
    - explosive counts/rates
    - stuffed-run counts/rates

- `v_team_season_offense_current`
  - roll up the game view

- `v_team_game_defense_current`
  - mirror offense rollups from defensive perspective

- `v_team_season_defense_current`
  - roll up the defense game view

- `v_team_game_situation_offense_current` / `_defense_current` and their season rollups
  - situational (early down / passing down / third down / fourth down) mirrors of the above, one row per `(team, game or season, situation)`

- `v_team_season_offense_ranked_current` / `_defense_ranked_current` and their situational counterparts
  - cross-team `RANK()` annotations for the weekly report's rank-annotated tables

## Automated Report Target

First report target — a weekly coach report, not a dashboard:

- `build_weekly_report --team <team> --opponent <opponent> --week <n> --season <season>`

4-page format, mostly tables with 1-2 embedded charts:

1. Title + schedule/season recap
2. Overall production (season-aggregate O-vs-D matchup, both directions)
3. Early & third downs (trimmed table + one "success rate by down" chart)
4. Weekly trends (featured team's game-by-game trajectory, one multi-subplot chart)

Recommended split tables:

- by down
- by distance bucket
- by quarter
- by explosive / non-explosive where useful

## Acceptance Notes

This spec should be considered stable enough to drive the first automated report once:

- every listed metric has an exact numerator/denominator definition
- every filter is labeled `supported_now`, `derived_next`, or `future_modeling`
- offense and defense perspectives are explicit
- success-rate rule is fixed
- explosive thresholds are fixed
- field-position filtering is defined around normalized field position
- advanced metrics are documented without pretending they are already trustworthy

When the derived layer is implemented, spot-check:

- Foothill offense passing season totals
- Foothill offense rushing season totals
- at least one defense mirror example
- at least one split by down and distance bucket
- at least one normalized field-position split

## Assumptions

- `plays` remains the source of truth for play-derived analytics
- official/stat-page reconciliation remains separate and later
- `xComp` is out of reach for v1 with current data
- `EPA` is a later modeling layer, not a quick derived stat
- `line_yards` may be documented now, but any implementation must be explicitly framed as a project-defined estimate
