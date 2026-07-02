from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


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


def _ensure_column(conn, table: str, column: str, column_type: str) -> None:
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _refresh_views(conn) -> None:
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_current_structure_runs AS
        WITH ranked AS (
            SELECT
                run_id,
                season,
                started_at,
                finished_at,
                standings_count,
                schedule_count,
                games_count,
                ROW_NUMBER() OVER (
                    PARTITION BY season
                    ORDER BY COALESCE(finished_at, started_at) DESC, run_id DESC
                ) AS rn
            FROM pipeline_runs
            WHERE status = 'completed'
              AND games_count IS NOT NULL
        )
        SELECT
            season,
            run_id AS structure_run_id,
            started_at,
            finished_at,
            standings_count,
            schedule_count,
            games_count
        FROM ranked
        WHERE rn = 1
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_current_plays_runs AS
        WITH ranked AS (
            SELECT
                run_id,
                season,
                started_at,
                finished_at,
                CASE
                    WHEN json_valid(notes) THEN json_extract_string(notes, '$.source_run_id')
                    ELSE NULL
                END AS source_run_id,
                CASE
                    WHEN json_valid(notes) THEN json_extract_string(notes, '$.reparsed_from_plays_run_id')
                    ELSE NULL
                END AS reparsed_from_plays_run_id,
                CASE
                    WHEN json_valid(notes) THEN TRY_CAST(json_extract_string(notes, '$.raw_pbp_count') AS INTEGER)
                    ELSE NULL
                END AS raw_pbp_count,
                CASE
                    WHEN json_valid(notes) THEN TRY_CAST(json_extract_string(notes, '$.plays_count') AS INTEGER)
                    ELSE NULL
                END AS plays_count,
                ROW_NUMBER() OVER (
                    PARTITION BY season
                    ORDER BY COALESCE(finished_at, started_at) DESC, run_id DESC
                ) AS rn
            FROM pipeline_runs
            WHERE status = 'completed'
              AND notes LIKE '%"plays_count"%'
        )
        SELECT
            season,
            run_id AS plays_run_id,
            source_run_id,
            reparsed_from_plays_run_id,
            started_at,
            finished_at,
            raw_pbp_count,
            plays_count
        FROM ranked
        WHERE rn = 1
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_current_field_position_runs AS
        WITH ranked AS (
            SELECT
                run_id,
                season,
                started_at,
                finished_at,
                CASE
                    WHEN json_valid(notes) THEN json_extract_string(notes, '$.source_plays_run_id')
                    ELSE NULL
                END AS source_plays_run_id,
                CASE
                    WHEN json_valid(notes) THEN TRY_CAST(json_extract_string(notes, '$.field_position_rows') AS INTEGER)
                    ELSE NULL
                END AS field_position_rows,
                CASE
                    WHEN json_valid(notes) THEN TRY_CAST(json_extract_string(notes, '$.resolved_count') AS INTEGER)
                    ELSE NULL
                END AS resolved_count,
                CASE
                    WHEN json_valid(notes) THEN TRY_CAST(json_extract_string(notes, '$.unresolved_count') AS INTEGER)
                    ELSE NULL
                END AS unresolved_count,
                ROW_NUMBER() OVER (
                    PARTITION BY season
                    ORDER BY COALESCE(finished_at, started_at) DESC, run_id DESC
                ) AS rn
            FROM pipeline_runs
            WHERE status = 'completed'
              AND notes LIKE '%"field_position_rows"%'
        )
        SELECT
            season,
            run_id AS field_position_run_id,
            source_plays_run_id,
            started_at,
            finished_at,
            field_position_rows,
            resolved_count,
            unresolved_count
        FROM ranked
        WHERE rn = 1
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_current_runs AS
        SELECT
            COALESCE(s.season, p.season, f.season) AS season,
            s.structure_run_id,
            p.plays_run_id,
            f.field_position_run_id,
            p.source_run_id AS plays_source_structure_run_id,
            p.reparsed_from_plays_run_id,
            f.source_plays_run_id AS field_position_source_plays_run_id
        FROM v_current_structure_runs s
        FULL OUTER JOIN v_current_plays_runs p
            ON p.season = s.season
        FULL OUTER JOIN v_current_field_position_runs f
            ON f.season = COALESCE(s.season, p.season)
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_games_current AS
        SELECT
            g.*,
            r.structure_run_id
        FROM games g
        JOIN v_current_structure_runs r
          ON r.season = g.season
         AND r.structure_run_id = g.run_id
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_plays_current AS
        SELECT
            p.*,
            r.plays_run_id,
            r.source_run_id AS source_structure_run_id,
            r.reparsed_from_plays_run_id
        FROM plays p
        JOIN v_current_plays_runs r
          ON r.season = p.season
         AND r.plays_run_id = p.run_id
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_play_field_positions_current AS
        SELECT
            pfp.*,
            r.field_position_run_id,
            r.source_plays_run_id AS current_source_plays_run_id
        FROM play_field_positions pfp
        JOIN v_current_field_position_runs r
          ON r.season = pfp.season
         AND r.field_position_run_id = pfp.run_id
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_game_offense AS
        SELECT
            p.season,
            p.run_id,
            p.game_id,
            p.offense AS team_name,
            MAX(p.schedule_home) AS schedule_home,
            MAX(p.schedule_away) AS schedule_away,
            SUM(CASE WHEN p.is_pass_attempt THEN 1 ELSE 0 END) AS pass_att,
            SUM(CASE WHEN p.completion THEN 1 ELSE 0 END) AS pass_comp,
            SUM(
                CASE
                    WHEN p.play_type = 'pass'
                     AND NOT COALESCE(p.is_sack, FALSE)
                     AND NOT COALESCE(p.is_interception, FALSE)
                    THEN COALESCE(p.yards_gained, 0)
                    ELSE 0
                END
            ) AS pass_yds,
            SUM(CASE WHEN p.is_interception THEN 1 ELSE 0 END) AS pass_int,
            SUM(
                CASE
                    WHEN p.play_type = 'pass'
                     AND p.is_td
                    THEN 1
                    ELSE 0
                END
            ) AS pass_td,
            SUM(CASE WHEN p.is_rush_attempt THEN 1 ELSE 0 END) AS rush_att,
            SUM(CASE WHEN p.is_rush_attempt THEN COALESCE(p.yards_gained, 0) ELSE 0 END) AS rush_yds,
            SUM(
                CASE
                    WHEN p.is_rush_attempt
                     AND p.is_td
                    THEN 1
                    ELSE 0
                END
            ) AS rush_td,
            SUM(CASE WHEN p.is_sack THEN 1 ELSE 0 END) AS sacks,
            SUM(CASE WHEN p.is_dropback THEN 1 ELSE 0 END) AS dropbacks,
            COUNT(*) AS play_count
        FROM plays p
        WHERE p.offense IS NOT NULL
          AND p.offense <> ''
        GROUP BY 1,2,3,4
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_game_offense_current AS
        SELECT tgo.*
        FROM v_team_game_offense tgo
        JOIN v_current_plays_runs r
          ON r.season = tgo.season
         AND r.plays_run_id = tgo.run_id
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_offense_current AS
        SELECT
            season,
            run_id,
            team_name,
            COUNT(DISTINCT game_id) AS games,
            SUM(pass_att) AS pass_att,
            SUM(pass_comp) AS pass_comp,
            SUM(pass_yds) AS pass_yds,
            SUM(pass_int) AS pass_int,
            SUM(pass_td) AS pass_td,
            SUM(rush_att) AS rush_att,
            SUM(rush_yds) AS rush_yds,
            SUM(rush_td) AS rush_td,
            SUM(sacks) AS sacks,
            SUM(dropbacks) AS dropbacks,
            SUM(play_count) AS play_count
        FROM v_team_game_offense_current
        GROUP BY 1,2,3
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_pbp_coverage_by_team_current AS
        WITH current_structure AS (
            SELECT * FROM v_current_structure_runs
        ),
        current_plays AS (
            SELECT * FROM v_current_plays_runs
        ),
        schedule_games AS (
            SELECT
                s.season,
                s.team_name,
                COUNT(DISTINCT s.game_id) AS scheduled_games
            FROM schedule s
            JOIN current_structure cs
              ON cs.season = s.season
             AND cs.structure_run_id = s.run_id
            GROUP BY 1,2
        ),
        pbp_games AS (
            SELECT
                p.season,
                p.offense AS team_name,
                COUNT(DISTINCT p.game_id) AS pbp_games
            FROM plays p
            JOIN current_plays cp
              ON cp.season = p.season
             AND cp.plays_run_id = p.run_id
            WHERE p.offense IS NOT NULL
              AND p.offense <> ''
            GROUP BY 1,2
        )
        SELECT
            sg.season,
            cs.structure_run_id,
            cp.plays_run_id,
            sg.team_name,
            sg.scheduled_games,
            COALESCE(pg.pbp_games, 0) AS pbp_games,
            sg.scheduled_games - COALESCE(pg.pbp_games, 0) AS missing_pbp_games
        FROM schedule_games sg
        JOIN current_structure cs
          ON cs.season = sg.season
        LEFT JOIN current_plays cp
          ON cp.season = sg.season
        LEFT JOIN pbp_games pg
          ON pg.season = sg.season
         AND pg.team_name = sg.team_name
        """
    )


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
        CREATE TABLE IF NOT EXISTS raw_pbp_html (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            fetched_at TIMESTAMP NOT NULL,
            source_url TEXT NOT NULL,
            html_text TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plays (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            game_id TEXT NOT NULL,
            home_team TEXT,
            away_team TEXT,
            schedule_home TEXT,
            schedule_away TEXT,
            play_id INTEGER NOT NULL,
            drive_id INTEGER,
            drive_start_time TEXT,
            quarter INTEGER,
            down INTEGER,
            distance INTEGER,
            field_position TEXT,
            yardline_raw INTEGER,
            offense TEXT,
            defense TEXT,
            play_type TEXT,
            passer TEXT,
            rusher TEXT,
            receiver TEXT,
            pass_result TEXT,
            yards_gained INTEGER,
            is_dropback BOOLEAN,
            is_attempt BOOLEAN,
            is_conversion BOOLEAN,
            is_pass_attempt BOOLEAN,
            is_rush_attempt BOOLEAN,
            completion BOOLEAN,
            is_interception BOOLEAN,
            is_td BOOLEAN,
            is_sack BOOLEAN,
            is_fumble BOOLEAN,
            fumble_recovered_by TEXT,
            is_penalty BOOLEAN,
            penalty_team TEXT,
            penalty_type TEXT,
            penalty_player TEXT,
            penalty_yards INTEGER,
            fg_result TEXT,
            tackler_1 TEXT,
            tackler_2 TEXT,
            raw_text TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS failed_game_fetches (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            failure_reason TEXT NOT NULL,
            recorded_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS field_position_prefixes (
            season TEXT NOT NULL,
            source_plays_run_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            prefix TEXT NOT NULL,
            team_1 TEXT,
            team_2 TEXT,
            schedule_home TEXT,
            schedule_away TEXT,
            play_count INTEGER,
            first_play_id INTEGER,
            last_play_id INTEGER,
            detected_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS field_position_crosswalk (
            season TEXT NOT NULL,
            source_plays_run_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            prefix TEXT NOT NULL,
            canonical_team TEXT NOT NULL,
            resolution_method TEXT NOT NULL,
            note TEXT,
            resolved_at TIMESTAMP NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS play_field_positions (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            source_plays_run_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            play_id INTEGER NOT NULL,
            field_position TEXT,
            field_pos_prefix TEXT,
            yardline_raw INTEGER,
            offense TEXT,
            prefix_owner TEXT,
            field_pos_side TEXT,
            yardline_100 INTEGER,
            resolution_status TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
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
    _ensure_column(conn, "plays", "is_pass_attempt", "BOOLEAN")
    _ensure_column(conn, "plays", "is_rush_attempt", "BOOLEAN")
    _ensure_column(conn, "plays", "is_conversion", "BOOLEAN")
    _refresh_views(conn)


def fetch_all(conn, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    return conn.execute(sql, params or []).fetchall()


def insert_rows(
    conn,
    table: str,
    rows: list[dict[str, Any]],
    chunk_size: int | None = None,
    progress_label: str | None = None,
    progress_logger: Callable[[str], None] | None = None,
) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    values = [tuple(row.get(col) for col in columns) for row in rows]
    if not chunk_size or chunk_size <= 0 or len(values) <= chunk_size:
        conn.executemany(sql, values)
        return

    total = len(values)
    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)
        conn.executemany(sql, values[start:end])
        if progress_label and progress_logger:
            progress_logger(f"INSERT {progress_label} [{end}/{total}]")
