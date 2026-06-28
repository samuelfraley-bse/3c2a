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

### Next recommended step
- Before the next clean scrape, either:
  - delete the current DuckDB file and rerun, or
  - inspect and remove the interrupted run from `pipeline_runs`
- Then run:

```powershell
uv run python -m duckdb_pipeline.cli --season 2025-26 --delay 8
```
