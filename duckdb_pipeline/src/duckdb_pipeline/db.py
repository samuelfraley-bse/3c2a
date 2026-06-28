from __future__ import annotations

from pathlib import Path
from typing import Any


def _duckdb_module():
    try:
        import duckdb  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "DuckDB is not installed. Install dependencies from duckdb_pipeline/pyproject.toml first."
        ) from exc
    return duckdb


def connect(db_path: str):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return _duckdb_module().connect(str(path))


def init_db(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_standings_html (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            fetched_at TIMESTAMP NOT NULL,
            source_url TEXT NOT NULL,
            html_text TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_schedule_html (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            team_id TEXT,
            team_name TEXT NOT NULL,
            fetched_at TIMESTAMP NOT NULL,
            source_url TEXT NOT NULL,
            html_text TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS standings (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            conference TEXT,
            team_name TEXT NOT NULL,
            team_id TEXT,
            schedule_url TEXT NOT NULL,
            conf_gp TEXT,
            conf_w TEXT,
            conf_l TEXT,
            conf_t TEXT,
            conf_pct TEXT,
            overall_gp TEXT,
            overall_w TEXT,
            overall_l TEXT,
            overall_t TEXT,
            overall_pct TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            team_name TEXT NOT NULL,
            team_id TEXT,
            game_id TEXT NOT NULL,
            game_date TEXT,
            home_away TEXT,
            opponent TEXT,
            result TEXT,
            pbp_url TEXT,
            schedule_home TEXT,
            schedule_away TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            game_id TEXT NOT NULL,
            game_date TEXT,
            pbp_url TEXT,
            schedule_home TEXT,
            schedule_away TEXT,
            home_team_canonical TEXT,
            away_team_canonical TEXT,
            team_1 TEXT,
            team_2 TEXT,
            schedule_row_count INTEGER,
            unique_team_count INTEGER,
            pairing_status TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP,
            status TEXT NOT NULL,
            standings_count INTEGER,
            schedule_count INTEGER,
            games_count INTEGER,
            notes TEXT
        )
        """
    )


def insert_rows(conn, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    values = [tuple(row.get(col) for col in columns) for row in rows]
    conn.executemany(sql, values)
