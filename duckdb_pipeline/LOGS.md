# DuckDB Pipeline Log

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
