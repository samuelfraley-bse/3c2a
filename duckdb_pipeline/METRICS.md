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
- `is_conversion`
  - `supported_now`

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
  - `future_modeling`
- `score_margin_bucket`
  - `future_modeling`

This should be documented as planned but unsupported until score state is derived from plays or another trusted source layer.

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

- `score_margin`
  - `future_modeling`
- `score_margin_bucket`
  - `future_modeling`
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

## Automated Report Target

First report target:

- `team_report --team <team> --season <season>`

Recommended output groups:

- offense passing
- offense rushing
- defense passing allowed
- defense rushing allowed

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
