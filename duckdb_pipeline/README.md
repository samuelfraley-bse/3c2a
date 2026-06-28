# DuckDB Pipeline

Milestone 1 of the Foothill DuckDB rebuild.

This subproject is a clean-room restart of the DuckDB pipeline.

Milestone 1 covers the structure pipeline:

- standings
- schedule
- games

Milestone 2 now covers:

- raw play-by-play HTML
- base `plays` rows tied to canonical `games`
- failed game fetch audit rows
- manual field-position crosswalk workflow
- derived field-position enrichment rows

It intentionally does not include:

- participation
- roster scraping
- player identity resolution

The remaining gaps after this slice are:

- participation joins
- player-name crosswalk application

## What it writes

Default database path:

`duckdb_pipeline/data/foothill.duckdb`

Tables created in Milestone 1:

- `raw_standings_html`
- `raw_schedule_html`
- `standings`
- `schedule`
- `games`
- `pipeline_runs`

Additional tables for the next slice:

- `raw_pbp_html`
- `plays`
- `failed_game_fetches`
- `field_position_prefixes`
- `field_position_crosswalk`
- `play_field_positions`

## Run

From the repo root:

```powershell
python -m duckdb_pipeline.cli --season 2025-26
```

From inside `duckdb_pipeline/`:

```powershell
uv run python -m duckdb_pipeline.cli --season 2025-26
```

Or via the console script:

```powershell
uv run --active scrape_season_structure --season 2025-26
```

To scrape base play-by-play using an existing `games` run:

```powershell
uv run --active scrape_season_plays --season 2025-26
uv run --active scrape_season_plays --season 2025-26 --source-run-id 471e4a97-8818-40b4-822e-93cf8134dc02
uv run --active scrape_season_plays --season 2025-26 --source-run-id 471e4a97-8818-40b4-822e-93cf8134dc02 --limit 5
```

Optional flags:

```powershell
python -m duckdb_pipeline.cli --season 2025-26 --delay 2.0
python -m duckdb_pipeline.cli --season 2025-26 --db-path duckdb_pipeline/data/foothill.duckdb
```

For plays:

```powershell
uv run --active scrape_season_plays --season 2025-26 --delay 5.0
uv run --active scrape_season_plays --season 2025-26 --source-run-id <structure_run_id>
uv run --active scrape_season_plays --season 2025-26 --source-run-id <structure_run_id> --limit 3
```

For field-position review and enrichment:

```powershell
uv run --active prepare_field_positions --season 2025-26 --source-plays-run-id <plays_run_id>
uv run --active prepare_field_positions --season 2025-26 --source-plays-run-id <plays_run_id> --review
uv run --active resolve_field_position_prefix --season 2025-26 --source-plays-run-id <plays_run_id> --game-id 20250830_2nv6 --prefix "LONG BEA" --canonical-team "Long Beach"
uv run --active resolve_field_position_prefix --season 2025-26 --source-plays-run-id <plays_run_id> --queue-index 4 --which a --canonical-team "Long Beach"
uv run --active apply_field_positions --season 2025-26 --source-plays-run-id <plays_run_id>
```

## Manual field-position workflow

The intended stable loop is:

1. Scrape `plays` for a season or week.
2. Detect per-game prefixes with `prepare_field_positions`.
3. Review the unresolved queue output for each game:
   - each unresolved game gets a sequential `queue` number
   - canonical teams are shown
   - both observed prefixes are shown
4. Resolve one prefix with `resolve_field_position_prefix`.
   - the other prefix is auto-assigned to the other team
   - this can be done either by explicit `--game-id` and `--prefix`
   - or by `--queue-index` and `--which a|b` when you are just working top-to-bottom through new games
5. Materialize `play_field_positions` with `apply_field_positions`.

This keeps:

- raw `plays` unchanged
- manual decisions auditable in `field_position_crosswalk`
- derived field-position data rebuildable when logic changes

## Review queue workflow

For in-season use, the intended operator flow is:

1. scrape new `plays`
2. run `prepare_field_positions --review`
3. the console shows the next unresolved game
4. answer `a` or `b` for which prefix belongs to `team_1`
5. let the command auto-assign the other side
6. continue until the queue is empty, or use `s` to skip and `q` to stop

That avoids needing to know `game_id` or the raw prefix string ahead of time, which makes weekly manual review much less fragile.

The prompt intentionally resets to `Queue 1` after each resolution, because it always reloads the next unresolved game instead of preserving a stale index from the earlier list.

## Test

From the repo root:

```powershell
python -m unittest discover duckdb_pipeline/tests
```

From inside `duckdb_pipeline/`:

```powershell
uv run python -m unittest discover tests
```
