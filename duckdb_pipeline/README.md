# DuckDB Pipeline

Milestone 1 of the Foothill DuckDB rebuild.

This subproject is a clean-room restart of the structure pipeline:

- standings
- schedule
- games

It intentionally does not include:

- play-by-play
- field-position crosswalks
- participation
- roster scraping
- player identity resolution

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

## Run

From the repo root:

```powershell
python -m duckdb_pipeline.cli --season 2025-26
```

From inside `duckdb_pipeline/`:

```powershell
uv run python -m duckdb_pipeline.cli --season 2025-26
```

Optional flags:

```powershell
python -m duckdb_pipeline.cli --season 2025-26 --delay 2.0
python -m duckdb_pipeline.cli --season 2025-26 --db-path duckdb_pipeline/data/foothill.duckdb
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
