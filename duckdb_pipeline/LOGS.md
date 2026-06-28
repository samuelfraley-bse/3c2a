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
