# DuckDB Pipeline Log

## 2026-07-03

### Session checkpoint
- Opened a new design session around the post-validation analytics layer.
- Decision:
  - freeze the current `plays` checkpoint as the working analytics source
  - define the football metrics contract before building the first automated report
  - keep the next implementation sequence as:
    - metrics spec
    - derived context views
    - automated `team_report`
    - later dashboard

### Metrics spec v1 added
- Added `duckdb_pipeline/METRICS.md` as the canonical football metrics and filters spec for the current `plays`-driven analytics layer.
- The document is intentionally a broad draft, but every metric/filter is labeled as:
  - `supported_now`
  - `derived_next`
  - `future_modeling`
- Locked project defaults:
  - offense/defense perspective definitions
  - success-rate rule:
    - `1st down = 50%`
    - `2nd down = 70%`
    - `3rd/4th down = 100%`
  - explosive thresholds:
    - `rush >= 10`
    - completed `pass >= 20`
  - `week` as team game order within season
  - normalized field-position analysis around `yardline_100` / zones
- Explicitly documented that:
  - `score_margin` is planned but not currently supported
  - `line_yards` can be a later project-defined estimate
  - `EPA` and `expected_completion_rate` require future modeling layers
- The intended next implementation target remains:
  - derived play-context and team report views
  - then a first automated `team_report`

### Current-run helper views added
- Added a small operator-facing DuckDB view layer so routine analysis no longer has to hardcode `run_id` values.
- New current-run helper views:
  - `v_current_structure_runs`
  - `v_current_plays_runs`
  - `v_current_field_position_runs`
  - `v_current_runs`
- New current working-surface views:
  - `v_games_current`
  - `v_plays_current`
  - `v_play_field_positions_current`
- New offense rollup views:
  - `v_team_game_offense`
  - `v_team_game_offense_current`
  - `v_team_season_offense_current`
  - `v_pbp_coverage_by_team_current`
- Intent:
  - keep base tables append-only and fully auditable
  - make DBeaver / SQL work feel stable by querying a blessed "current" surface
  - reduce repeated manual use of run IDs for routine inspection
- Current behavior:
  - the `v_*_current` views follow the latest completed run for each season by pipeline timestamp
  - raw historical runs remain queryable directly in `plays`, `games`, and `pipeline_runs`

## 2026-06-28

### Milestone 1 created
- Added a new in-repo subproject at `duckdb_pipeline/`.
- Implemented a clean-room DuckDB structure pipeline for:
  - standings
  - schedule
  - games
- Added these tables:
  - `raw_standings_html`
  - `raw_schedule_html`
  - `standings`
  - `schedule`
  - `games`
  - `pipeline_runs`

### Tooling and packaging
- Added subproject packaging in `duckdb_pipeline/pyproject.toml`.
- Added CLI entry point: `python -m duckdb_pipeline.cli`.
- Added tests for:
  - standings parsing
  - schedule parsing
  - canonical game derivation
  - DuckDB initialization/inserts

### Logging improvements
- Added timestamped console logging for:
  - run start
  - stage transitions
  - wait periods
  - fetch attempts
  - successful responses
  - retries / rate limiting
  - final write summary

### Dependency status
- Installed the subproject dependencies with `uv sync`.
- Verified tests pass in the subproject environment with:
  - `uv run python -m unittest discover tests`

### Live scrape status
- A first live structure scrape for season `2025-26` was started with `--delay 8`.
- The run was intentionally stopped before completion.
- The background process was terminated.
- Result: there may be a partial DuckDB file and/or an incomplete `pipeline_runs` row from the interrupted run.

### Cleanup performed
- Removed the partial DuckDB files from the interrupted run.
- Removed the accidental nested `duckdb_pipeline/duckdb_pipeline/data/` path created by the earlier relative DB path.
- Updated the default DB path logic so the database resolves to the subproject's own `data/foothill.duckdb` regardless of the current working directory.

### Neutral-site schedule fix
- Investigated six paired games with blank `home_team_canonical` / `away_team_canonical`.
- Confirmed the affected schedule pages used `neutral` event rows with wording like `Team A vs. Team B @ site`.
- Updated the schedule parser to infer home/away from the box-score `aria-label` for `neutral` rows.
- Added a second safety fallback in `build_games_rows()` that uses consistent `schedule_home` / `schedule_away` values when canonical home/away are still blank.
- Added parser tests covering neutral-site schedule handling and canonical home/away fallback.

### Fresh validation rerun
- Re-ran the full `2025-26` structure scrape after the neutral-row fix.
- Completed run ID: `471e4a97-8818-40b4-822e-93cf8134dc02`
- Verified counts:
  - `standings = 66`
  - `schedule = 694`
  - `games = 347`
- Verified all `347` games are `paired`.
- Verified `0` paired games have blank `home_team_canonical` or `away_team_canonical`.

### Milestone 2 scaffold started
- Added append-only `raw_pbp_html` table.
- Added base `plays` table keyed by `run_id`, `season`, and `game_id`.
- Added `failed_game_fetches` audit table for missing or zero-play game fetches.
- Added a new console command:
  - `scrape_season_plays`
- Plays runs now point back to a structure snapshot via `source_run_id` stored in run notes and raw/failure tables.

### Base PBP parser scope
- Parses drive headers, quarter changes, down-distance, field-position token, and base play actors.
- Keeps this milestone intentionally limited:
  - no field-position owner crosswalk yet
  - no `yardline_100` yet
  - no participation join yet
  - no player identity crosswalk yet

### Validation
- Added tests for:
  - neutral-site schedule handling
  - canonical game fallback logic
  - base PBP parsing for rush/pass/penalty rows
  - DuckDB schema initialization for the new PBP tables
- Added a `--limit` option to `scrape_season_plays` for small validation runs before full-season ingest.
- Updated interrupted plays runs to mark the `pipeline_runs` row as failed instead of leaving it stuck at `running`.
- Verified local test suite passes:

```powershell
uv run --active python -m unittest discover tests
```

### Field-position workflow added
- Added `field_position_prefixes` to store detected per-game prefixes from a specific `plays` run.
- Added `field_position_crosswalk` to store manual prefix-to-team decisions.
- Added `play_field_positions` as a rebuildable derived layer keyed back to the source `plays` run.
- Added console commands:
  - `prepare_field_positions`
  - `resolve_field_position_prefix`
  - `apply_field_positions`
- The resolution workflow now supports:
  - displaying canonical team names with both detected prefixes
  - manually selecting one prefix/team mapping
  - automatically assigning the other prefix to the other team

### Field-position validation
- Tested prefix detection on the 10-game plays validation run:
  - `440482d8-cb31-4388-9396-8103a16b07d2`
- Verified sample review output for truncated prefixes like:
  - `LONG BEA`
  - `RIVERSID`
  - `SADDLEBA`
- Tested manual resolution for:
  - `20250830_2nv6`
  - `LONG BEA -> Long Beach`
  - auto-filled `RIVERSID -> Riverside`
- Tested enrichment materialization for the 10-game sample:
  - `1638` derived field-position rows written
  - unresolved rows remained high because only one game had been manually resolved, which is expected for the current validation state

### Review queue breadcrumb
- Updated the field-position review flow to better match the real in-season workflow.
- `prepare_field_positions` now prints an unresolved review queue with:
  - sequential `queue` index
  - canonical teams
  - `schedule_home` / `schedule_away`
  - `prefix_a` / `prefix_b`
  - `resolved_count`
- `resolve_field_position_prefix` now supports queue-driven review with:
  - `--queue-index`
  - `--which a|b`
- This keeps the older explicit mode available:
  - `--game-id`
  - `--prefix`
- Rationale:
  - when new weekly games arrive, the operator usually does not know the `game_id` or raw prefix in advance
  - a console review queue lets the operator just work top-to-bottom and assign one side per game
  - the opposite prefix is still auto-filled, keeping the manual step small and auditable

### Interactive review loop
- Added a one-command interactive mode:
  - `prepare_field_positions --review`
- This mode:
  - rebuilds detected prefixes
  - shows the next unresolved game
  - prompts `Which prefix belongs to <team_1>? [a/b/s/q]`
  - auto-fills the opposite side after a single answer
- Verified the interactive flow across the unresolved sample queue for the 10-game validation run.
- Confirmed the loop reaches:
  - `No unresolved field-position games remain for this plays run.`
- Confirmed the queue display intentionally resets to `Queue 1` after each answer because it always reloads the next unresolved game rather than preserving a stale queue index.

### Historical vs in-season note
- Documented that the current field-position review flow is optimized for week-by-week in-season ingest.
- Expected in-season pattern:
  - scrape new games
  - review a small unresolved queue
  - apply the crosswalked field-position layer
- Historical backfill can still use the same manual review flow for now.
- If the historical scope becomes large, flag a future improvement for:
  - batched review
  - suggested mappings
  - partial automation with manual confirmation
- Decision for now:
  - keep the workflow manual-first and stable
  - defer larger historical automation until it is clearly worth the added complexity

### Full-season 2025-26 plays run completed
- Re-ran the full `2025-26` plays scrape after confirming that the earlier interrupted run had not fully committed.
- Successful completed plays run:
  - `3e4103ae-62c3-4195-9c45-71df4fcc23ce`
- Final logged counts:
  - `games = 347`
  - `raw_pbp = 344`
  - `plays = 55548`
  - `failed = 15`
- Important operational note:
  - the console `WRITE plays ...` line is emitted before DuckDB finishes the heavy insert/commit phase
  - on this full-season run, `WRITE` to `DONE` took roughly 6 minutes 38 seconds
- future runs should be treated as incomplete until the console prints `DONE run_id=...` and returns to the prompt
- Next intended step after returning to this project:
  - run `prepare_field_positions --review` against plays run `3e4103ae-62c3-4195-9c45-71df4fcc23ce`

### Team-prefix memory review flow
- Updated field-position review memory to follow confirmed `canonical_team + prefix` pairs rather than treating prefixes as globally exclusive.
- This keeps the workflow aligned with the operator's real mental model:
  - confirm which observed prefix belongs to the displayed canonical school
  - reuse that same pairing in future games for the same school
  - allow the same raw prefix text to appear for different schools in different games when the source site is ambiguous
- `prepare_field_positions --review` now:
  - prints progress while reviewing
  - auto-seeds future games when a previously confirmed team-prefix pairing appears again
  - keeps the review interactive instead of silently resolving the whole queue

### Field-position apply validation
- Applied field-position enrichment to the full-season `2025-26` plays run:
  - source plays run: `3e4103ae-62c3-4195-9c45-71df4fcc23ce`
- Validation result:
  - `49,277` rows resolved
  - `6,271` rows marked `no-field-position`
  - `0` rows marked `unresolved-prefix`
- Spot-checked sample `no-field-position` rows and confirmed they are expected non-scrimmage cases such as:
  - `kickoff`
  - `pat`
- Takeaway:
  - the crosswalk covered every row that actually carried a resolvable field-position token
  - the remaining unresolved count is normal pipeline residue, not a mapping failure

### Team-level rushing accounting decision
- Spot-checked Foothill's season rushing totals from the completed `2025-26` plays run against the official online box-score total.
- Parsed totals using only `play_type = 'rush'` produced:
  - `375` rushing attempts
  - `1723` rushing yards
  - `12` rushing touchdowns
- Official site total was:
  - `408` rushing attempts
  - `1520` rushing yards
  - `12` rushing touchdowns
- The gap reconciled exactly once sacks were included:
  - `33` sacks
  - `-203` sack yards
  - `375 + 33 = 408` rush attempts
  - `1723 - 203 = 1520` rush yards
- Schema decision going forward:
  - official team rushing should include sacks
  - play-level context should still distinguish:
    - designed runs
    - dropback passes
    - sacks
- Planned derived flags for downstream aggregates:
  - `is_rush_att` for official rushing attempts, including sacks
  - `is_dropback` for pass attempts and sacks
  - keep `play_type = 'rush' and not is_sack` as the designed-run slice
- Rationale:
  - this preserves exact reconciliation with official box scores
  - while still keeping cleaner contextual features for later analytics

### Dropback / pass-attempt / rush-attempt split
- Updated the `plays` schema to add explicit derived attempt flags:
  - `is_pass_attempt`
  - `is_rush_attempt`
- Kept `is_dropback` as the play-context flag.
- Confirmed intended sack behavior:
  - `is_dropback = true`
  - `is_pass_attempt = false`
  - `is_rush_attempt = true`
  - `is_sack = true`
- This reflects the intended accounting split:
  - sacks belong to pass-play context
  - sacks do not count as official pass attempts
  - sacks do count toward official team rushing attempts and rushing yards
- Ran a one-time backfill on the existing full-season `plays` rows so the new columns were populated for historical data already stored in DuckDB.
- Foothill validation after backfill for plays run `3e4103ae-62c3-4195-9c45-71df4fcc23ce`:
  - `dropbacks = 303`
  - `pass_attempts = 270`
  - `rush_attempts = 408`
  - `sacks = 33`
- Sample sack rows now correctly show:
  - `play_type = 'pass'`
  - `is_dropback = true`
  - `is_pass_attempt = false`
  - `is_rush_attempt = true`

### Team-stat validation order
- Decided to validate season team offense in two passes instead of treating every mismatch the same.
- Validation pass 1:
  - check coverage first
  - compare scheduled game count versus distinct play-by-play game count by team
  - use this to identify teams that are probably missing one or more logged games entirely
- Validation pass 2:
  - only after coverage is understood, inspect teams with full game counts but remaining stat mismatches
  - these are the better parser/accounting audit targets because missing PBP coverage is no longer a confounder
- Current examples:
  - missing-game-coverage checks are useful for teams like `Reedley`, `Riverside`, `Sequoias`, and others that appear short on distinct PBP games
  - full-coverage stat-mismatch checks are more appropriate for teams like `Ventura`, `Long Beach`, and `San Francisco`
- Immediate operator workflow:
  - list the exact games currently present in DuckDB for a team
  - compare those games against the official season schedule or stat page
  - identify whether the discrepancy is a missing game versus an accounting mismatch inside covered games

### Missing-PBP opponent pattern
- After fixing `pbp_url` construction to use canonical season-level boxscore paths built from `season + game_id`, several teams recovered to full play-by-play coverage.
- Remaining missing-game checks now appear to surface source-availability patterns more than scraper-path bugs.
- First confirmed example:
  - `Hartnell` appears as the opponent in `6` still-missing games
- Enumerated missing Hartnell-involved game IDs:
  - `20250830_l13b` — `Hartnell vs Chabot`
  - `20250913_cupn` — `Hartnell vs Los Medanos`
  - `20250920_33gi` — `Feather River vs Hartnell`
  - `20250927_2b9n` — `Hartnell vs Contra Costa`
  - `20251025_3ap7` — `Hartnell vs Merced`
  - `20251108_t19u` — `Hartnell vs Gavilan`
- Interpretation:
  - this no longer looks like six unrelated parser misses
  - it looks like a Hartnell-centered low- or no-PBP coverage pattern in the source data
- Next diagnostic path:
  - repeat the same missing-game breakdown for other high-frequency missing opponents such as `Feather River` and `Gavilan`
  - maintain a running list of likely low-PBP-coverage schools so future aggregate mismatches can be interpreted correctly

### Low-PBP coverage cluster
- Follow-up missing-game breakdowns suggest that some of the remaining gaps are better understood as a source-coverage cluster rather than isolated one-off misses.
- Confirmed overlapping missing-game patterns:
  - `Hartnell`
  - `Feather River`
  - `Gavilan`
  - `Siskiyous`
- Supporting examples:
  - `Feather River` missing-game set includes games versus `Gavilan`, `Hartnell`, `Cabrillo`, and `Siskiyous`
  - `Gavilan` missing-game set includes games versus `Siskiyous`, `Feather River`, `San Joaquin Delta`, and `Hartnell`
- Interpretation:
  - remaining missing play-by-play coverage is not purely school-by-school
  - some schools appear in a small low-coverage network where games involving either side are more likely to have no usable PBP
- Practical validation takeaway:
  - when a team's season totals are short by exactly one or a few games, check whether the missing opponent falls inside this low-coverage cluster before assuming a parsing bug
- Additional one-off checks reinforced the same cluster interpretation:
  - `Cabrillo`'s remaining missing game is against `Feather River`
  - `San Joaquin Delta`'s remaining missing game is against `Gavilan`
- This suggests some apparent single-school one-off gaps are really edges of the same low-PBP network rather than independent failures.

## 2026-06-30

### Interception return yardage bug found
- While reconciling Ventura team passing against the official season log, identified a play-level accounting bug in:
  - `20251011_cdcb` (`Ventura at Allan Hancock`)
- Symptom:
  - official Ventura passing for the game was `11-22-1` for `173` yards
  - DuckDB matched attempts, completions, interceptions, and touchdowns, but only produced `132` passing yards
- Root cause:
  - an intercepted pass was correctly parsed as:
    - `is_pass_attempt = true`
    - `completion = false`
    - `is_interception = true`
    - `yards_gained = 0`
  - but later in `parse_pbp_html()`, the generic fumble-recovery yardage adjustment overwrote that with `-41`
  - the trigger was an interception return that itself ended with a defensive fumble/recovery, causing the parser to treat the defender return location as offensive pass yardage
- Fix direction:
  - keep offensive pass yardage at `0` for intercepted passes
  - skip the fumble-based yardage rewrite when the parsed play is already marked `is_interception`
- Why this matters:
  - the same pattern can appear in other games
  - this is a clean parser/accounting bug, not a scraping coverage issue
- Data refresh note:
  - this fix should only require re-parsing from stored `raw_pbp_html`
  - no re-scrape should be needed unless the raw source itself was missing

### Offensive yardage semantics
- Clarified the intended meaning of offensive `yards_gained` for team-stat reconciliation.
- Rule:
  - offensive yardage should stop at the point where possession changes
  - any later return yards belong to the return event, not to offensive production
- Confirmed implications:
  - offensive pass yards are always `0` on any interception
  - interception return yards should not count as offensive passing yards
  - interception-return fumble yards should not count as offensive passing yards either
  - fumble return yards after an offensive fumble should not add to offensive rushing or passing totals
- Practical interpretation:
  - the offense keeps only the gain/loss up to the turnover spot
  - post-turnover movement is separate context for later analysis, not part of team offense
- Parser consequence:
  - once a play is classified as a turnover event, downstream return/recovery location text must not overwrite offensive `yards_gained`
- Why this breadcrumb matters:
  - it gives a stable accounting rule for future parser edge cases
  - it keeps team rushing, passing, and total offense aligned with official box-score semantics

### Quarter-start possession reset bug found
- While continuing Ventura/Bakersfield validation, found a second structural parser bug in:
  - `20250913_z92j`
- Symptom:
  - a third-quarter `Chase Furtado -> Dylan Johnson for 6 yards` completion was being credited to `Ventura`
  - that produced an extra `+1 completion`, `+1 attempt`, and `+6 passing yards` for Ventura
- Root cause:
  - the raw PBP used a quarter-start line with embedded possession text:
    - `Start of 3rd quarter, clock 15:00, BAKERSFI ball on BAKERSFI25.`
  - the parser recognized the quarter change but did not reset offense/defense from the embedded `TEAM ball on ...` token
  - offense therefore leaked forward from the prior half until a cleaner possession cue appeared
- Fix direction:
  - treat quarter-start lines with embedded `TEAM ball on ...` text as valid possession resets
  - reuse the same possession-resolution logic for:
    - standalone `TEAM ball on ...` rows
    - quarter-start rows that embed the same phrase
- Why this matters:
  - this is not a one-off Ventura bug
  - it affects any source page that compresses quarter start and possession reset into a single sentence

### Conversion-try accounting rule added
- While validating `20250830_fzzx` (`Ventura at Palomar`), isolated a remaining season-passing mismatch to a post-touchdown try play:
  - `Braesen Leon pass attempt to TEAM failed (intercepted), returned by Hunter Stowe.`
- Surrounding sequence confirmed this occurs:
  - immediately after a Ventura rushing touchdown
  - immediately before the ensuing kickoff
- Accounting interpretation:
  - this is a conversion try, not a standard offensive passing play
  - it should not count toward official team passing attempts, interceptions, or yards
- Schema / parser decision:
  - added explicit `plays.is_conversion`
  - explicit pass-try rows now parse as:
    - `play_type = 'two_point'`
    - `is_conversion = true`
    - `is_dropback = false`
    - `is_pass_attempt = false`
    - `is_rush_attempt = false`
    - `is_interception = false`
- Aggregate rule going forward:
  - conversion tries should add no normal passing, rushing, or interception stats even before aggregation
- Why this is better than a one-off patch:
  - it preserves the raw football event for context
  - it makes future audits easy if another try-format edge case appears
  - it keeps official team stat reconciliation correct by parsed-play semantics, not just downstream filtering

### Conversion-try reparse validation
- Rebuilt `plays` from stored `raw_pbp_html` after the try-play semantic change.
- New completed reparse run:
  - `85e57f9b-2363-4244-8d23-a1085093dcc7`
- Confirmed the motivating Palomar check now matches the official team line exactly for `Ventura` in `20250830_fzzx`:
  - `37` pass attempts
  - `19` completions
  - `220` passing yards
  - `0` interceptions
  - `1` passing touchdown
- Takeaway:
  - the post-touchdown try is now retained as an event in `plays`
  - but it no longer leaks into standard passing/interception accounting

### Defensive fumble-return touchdown fix
- While validating Long Beach season passing totals, found one remaining extra passing touchdown.
- The bad row was:
  - `20250906_t3z9`
  - `play_id 44`
  - `Wyatt McCauley sacked for loss of 1 yard ... fumble ... recovered by MT. SAN ... TOUCHDOWN`
- Root cause:
  - sacks are intentionally kept as `play_type = 'pass'` for dropback context
  - but the parser was letting a defensive fumble-return touchdown stay attached to the offensive row as `is_td = true`
- Fix direction:
  - when a fumble row ends in a touchdown and the recovery team matches the defense, clear offensive `is_td`
  - keep offensive yards only to the turnover point
- Additional hardening:
  - widened the defensive-recovery team matching logic for source tokens like `MT. SAN ...`
- Validation after reparse:
  - Long Beach season passing now matches the official site exactly:
    - `393` attempts
    - `220` completions
    - `3129` passing yards
    - `9` interceptions
    - `30` passing touchdowns

### Contradictory drive-label possession fix
- While validating San Francisco season passing, found a fragile source-format issue in:
  - `20250927_6pu6` (`San Francisco vs Sierra`)
- Symptom:
  - four real San Francisco completions were present in raw HTML but were not being credited to `offense = 'San Francisco'`
  - the missing chunk was exactly:
    - `4` completions
    - `60` passing yards
    - `1` passing touchdown
- Root cause:
  - the source emitted contradictory possession cues in this order:
    - stale/bad drive header: `Sierra at 00:56`
    - `Sierra drive start at 00:56.`
    - `CCSF ball on CCSF40, clock 00:56.`
    - `San Francisco drive start at 00:56.`
  - the parser previously ignored explicit `Team drive start at ...` rows
  - it also allowed unknown `TEAM ball on ...` tokens to overwrite offense with non-canonical junk like `CCSF`
- Fix direction:
  - treat explicit `Team drive start at ...` rows as authoritative possession resets
  - keep drive headers as weaker hints only
  - ignore unknown `TEAM ball on ...` abbreviations unless they map cleanly to the known home/away teams
- Why this is an important weakness breadcrumb:
  - the source can contradict itself mid-drive
  - future failures may come from malformed possession labels rather than missing games
  - this class of bug is a good candidate for later automated anomaly detection when raw HTML contains conflicting possession cues for the same timestamp

### Ghost-drive residue after possession fix
- After the contradictory-drive possession fix was reparsed into:
  - `ec2b4ae5-7bbb-403d-84bc-71f16339ba3a`
- San Francisco vs Sierra (`20250927_6pu6`) improved to the correct:
  - `18` completions
  - `320` passing yards
  - `0` interceptions
  - `2` passing touchdowns
- But the game still shows an attempts mismatch:
  - DuckDB: `27 att / 18 comp`
  - official: `22 att / 18 comp`
- This indicates the main ghost-drive possession error is fixed, but malformed source rows still survive as parsed football events.
- Current smoking-gun example:
  - parsed `play_id 88`
  - `Andre Watson punt no gain to the CCSF40, downed.`
- Why this matters:
  - the row appears immediately after Sierra's real punt and immediately before the restored San Francisco completion sequence
  - that strongly suggests we still need a second layer of control-row / duplicate-event hardening for malformed ghost-drive regions
- Working interpretation:
  - possession attribution is now mostly correct
  - event suppression for malformed duplicate rows is still incomplete

### San Francisco vs Sierra attempts reconciliation
- Follow-up validation for `20250927_6pu6` showed the remaining `27 att / 18 comp / 320 yds / 0 int / 2 td` line is supported by:
  - the raw play-by-play page
  - the game-level box score
- Important correction:
  - the earlier `official: 22 att / 18 comp` comparison came from a season-level stats page and does **not** appear to match the game-level source documents for this game
- Decision:
  - keep the narrow suppression for the clearly bogus ghost-drive punt residue:
    - `Andre Watson punt no gain to the CCSF40, downed.`
  - do **not** add any broader pass-attempt suppression rules for this game
- Rationale:
  - the fake punt is malformed source residue and should not survive parsing
  - the remaining San Francisco incompletions are present as ordinary football plays in the raw PBP and should be preserved
  - we should prefer the game-level raw/box sources over a contradictory season aggregate page when deciding whether to suppress parsed events

### Passing validation checkpoint
- Rebuilt full-season `plays` from stored raw HTML into:
  - `63fa3f95-a627-44fe-851a-d7463fcab7b6`
- Confirmed exact season passing matches against the official `2025-26` site for:
  - `Riverside`
  - `Moorpark`
  - `Citrus`
  - `San Francisco`
  - `Long Beach`
  - `Foothill`
- Confirmed additional strong matches or near-matches that no longer look urgent:
  - `Ventura`
  - `Pasadena City`
  - `Golden West`
  - `Mt. San Antonio`
  - `Southwestern`
  - `Fullerton`
  - `Reedley`
  - `Shasta`
  - `San Mateo`
  - `Laney`
  - `Compton`
- Remaining weaker teams fall into two broad buckets:
  - likely low-/missing-PBP coverage cluster:
    - `Hartnell`
    - `Feather River`
    - `Gavilan`
    - related schools already seen in that network such as `Cabrillo`, `Chabot`, `Merced`, `San Joaquin Delta`, `Siskiyous`
  - meaningful remaining validation targets where parser/accounting issues may still exist:
    - `Los Medanos`
    - `Victor Valley`
    - `Monterey Peninsula`
    - `Santa Monica`
    - `Mt. San Jacinto`
    - `Fresno City`
    - `LA Valley`
    - `Contra Costa`
- Most promising next targeted parser audit when work resumes:
  - `Los Medanos`
- Reason:
  - it is high on the passing leaderboard
  - the gap is large enough to be worth attention
  - and it may expose either a small number of missing games or a real remaining parser issue rather than just the already-known low-coverage school cluster

### Victor Valley vs Santa Monica source-side discrepancy
- Investigated `Victor Valley` passing mismatch for:
  - `20251116_5n02`
  - `Santa Monica at Victor Valley`
  - `November 16, 2025`
- DuckDB / parsed public PBP currently shows:
  - `29 comp`
  - `39 att`
  - `248 yds`
  - `3 pass TD`
  - `1 INT`
- Official game-level box-score passing table shows:
  - `Seth Burbine 30-38, 339 yds, 4 TD, 1 INT`
  - `Ricky Sampson 0-1, 0 yds, 0 TD, 0 INT`
- Confirmed:
  - the stored `raw_pbp_html` rows for `20251116_5n02` are all correctly tied to the `November 16, 2025` game
  - this is **not** a bad `game_id` / opponent-pairing issue despite Victor Valley playing Santa Monica twice in `2025-26`
  - the public `?view=plays` page itself only exposes `3` Victor Valley passing touchdowns:
    - `Seth Burbine -> Darren Gandy` for `4`
    - `Seth Burbine -> Darren Gandy` for `2`
    - `Seth Burbine -> Cael Meisman` for `19`
- Additional important clue from the site scoring summary:
  - one `4th quarter` summary row is mislabeled as:
    - `Victor Valley - Dylan Moreno pass complete to Bryson Wood for 39 yards ...`
  - but `Dylan Moreno` and `Bryson Wood` are `Santa Monica`, and the surrounding score flow confirms it is a `Santa Monica` touchdown
- Working conclusion:
  - DuckDB is matching the visible public play-by-play for this game
  - the `3C2A` source pages are internally inconsistent for this game
  - this is best treated as a **source-side stat discrepancy**, not a current parser bug
- Current policy implication:
  - keep `plays` as `PBP-truth` for play-derived modeling
  - note that some team-level validations against official aggregate/box pages may require a future box-score reconciliation layer

### Passing checkpoint: good enough to proceed
- Current `2025-26` season passing totals are in a usable place for play-by-play-driven tendency work.
- Decision:
  - do **not** keep chasing exact official season passing reconciliation right now
  - accept remaining mismatches where they are clearly driven by:
    - low / missing public PBP coverage
    - source-side page inconsistencies
    - noisy control/state rows in public PBP
- Teams that now look broadly reliable for PBP-derived passing work include:
  - `Riverside`
  - `Diablo Valley`
  - `Sequoias`
  - `Ventura`
  - `Moorpark`
  - `Citrus`
  - `Pasadena City`
  - `Golden West`
  - `Long Beach`
  - `De Anza`
  - `Cerritos`
  - `San Francisco`
  - `Grossmont`
  - `Mt. San Antonio`
  - `Southwestern`
  - `Palomar`
  - `Coalinga`
  - `Antelope Valley`
  - `Glendale`
  - `El Camino`
  - `Saddleback`
  - `Fullerton`
  - `West LA`
  - `Reedley`
  - `Shasta`
  - `San Mateo`
  - `Laney`
  - `Foothill`
- Teams with remaining known weakness / unresolved passing reconciliation are left as future work, especially:
  - `Los Medanos`
  - `Victor Valley`
  - `Monterey Peninsula`
  - `Santa Monica`
  - `Mt. San Jacinto`
  - `LA Valley`
  - `Contra Costa`
  - `San Joaquin Delta`
  - `Cabrillo`
  - `Desert`
  - `American River`
  - `Chabot`
  - `Merced`
  - `LA Pierce`
  - `Feather River`
  - `Gavilan`
  - `Hartnell`
- Next step after this checkpoint:
  - shift validation attention to `rushing`, using the same philosophy:
    - prefer public PBP as modeling truth
    - log known source mismatches
    - avoid forcing exact official reconciliation where source pages conflict

### Rushing checkpoint: missing-game coverage is real for some programs
- While reviewing the `2025-26` rushing mismatches, separated two different failure shapes:
  - real missing-game public PBP coverage
  - games present in public PBP but still disagreeing with official totals
- Using:
  - structure run `4b573736-96bb-4939-8ea8-661f0e51ddfc`
  - rebuilt plays run `63fa3f95-a627-44fe-851a-d7463fcab7b6`
- Confirmed missing-PBP cluster counts for the weaker teams:
  - `Hartnell`: `6` missing games
  - `Feather River`: `4` missing games
  - `Gavilan`: `4` missing games
  - `Siskiyous`: `2` missing games
  - `Cabrillo`: `1` missing game
  - `Chabot`: `1` missing game
  - `Contra Costa`: `1` missing game
  - `LA Valley`: `1` missing game
  - `Los Medanos`: `1` missing game
  - `Merced`: `1` missing game
  - `San Joaquin Delta`: `1` missing game
- Confirmed the main missing-opponent islands are:
  - `Hartnell` (`6` distinct games)
  - `Feather River` (`4`)
  - `Gavilan` (`4`)
  - `Siskiyous` (`2`)
- Practical interpretation:
  - for programs like `Hartnell`, `Feather River`, `Gavilan`, `Siskiyous`, `Cabrillo`, `Chabot`, `Contra Costa`, `Los Medanos`, `Merced`, and `San Joaquin Delta`, a meaningful share of the rushing gap is explained by **real absent public PBP**, not just parser logic
  - this makes those teams weak candidates for exact season-total reconciliation from `plays` alone
- Also useful to note the opposite case:
  - some teams still look off **without** a corresponding missing-game explanation, so they stay in the "source weirdness / accounting / future audit" bucket
  - especially `Victor Valley`, `San Francisco`, `De Anza`, `West LA`, `LA Southwest`, `Monterey Peninsula`, and `LA Pierce`
- Takeaway:
  - "missing games is real for some programs" is now a documented fact, not just a suspicion
  - future validation should first ask:
    - is this team inside a missing-PBP cluster?
    - or is this a present-but-weird source/accounting case?

### Session wrap / frozen checkpoint
- Freeze decision for `2025-26`:
  - treat the current rebuilt `plays` layer as stable enough for team tendency/context work
  - do **not** keep trying to force exact official stat-page reconciliation inside the `plays` parser
  - keep known weak programs documented rather than silently "fixing" them with overrides
- Frozen working baseline:
  - structure run: `4b573736-96bb-4939-8ea8-661f0e51ddfc`
  - plays scrape source run: `75e20b24-e705-463c-b966-59d32dd2d361`
  - current frozen full reparse baseline: `63fa3f95-a627-44fe-851a-d7463fcab7b6`
- Current high-level stance:
  - `plays` = tendency/context truth
  - future `box score` layer = official game-performance / validation truth
  - reconciliation should live in an explicit audit layer later, not as silent overwrite logic
- Recommended next implementation track:
  - create a parallel box-score layer for later validation and missing-PBP coverage support
  - suggested tables:
    - `raw_boxscore_html`
    - `box_score_team_stats`
  - keep this separate from `plays`
- Recommended derived-football track after that:
  - build `team_game_stats` from `plays`
  - build `team_season_stats` on top of `team_game_stats`
  - preserve the current semantics:
    - `is_dropback`
    - `is_pass_attempt`
    - `is_rush_attempt`
    - `is_sack`
  - then add situational rollups such as:
    - down / distance
    - normalized field position
    - red zone
    - quarter / clock bucket
    - score margin
- Practical plan for next session:
  - `1.` scaffold the box-score ingestion layer without changing the existing `plays` pipeline
  - `2.` scrape/store one season of raw box-score pages by `game_id`
  - `3.` parse team-level official game stats into a separate curated table
  - `4.` compare `plays`-derived `team_game_stats` vs `box_score_team_stats` game by game
  - `5.` only then decide if any targeted reconciliation rules are worth adding
