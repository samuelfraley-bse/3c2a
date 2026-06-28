# DuckDB Pipeline

Milestone 1 of the Foothill DuckDB rebuild.

This subproject is a clean-room restart of the DuckDB pipeline.

Milestone 1 covers the structure pipeline:

- standings
- schedule
- games

Milestone 2 now starts the base PBP layer:

- raw play-by-play HTML
- base `plays` rows tied to canonical `games`
- failed game fetch audit rows

It intentionally does not include:

- field-position crosswalks
- participation
- roster scraping
- player identity resolution

The base PBP parser currently stops short of:

- `field_pos_side`
- `yardline_100`
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

## Test

From the repo root:

```powershell
python -m unittest discover duckdb_pipeline/tests
```

From inside `duckdb_pipeline/`:

```powershell
uv run python -m unittest discover tests
```
