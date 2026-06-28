from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone

from .constants import DEFAULT_DB_PATH, DEFAULT_DELAY, DEFAULT_SEASON
from .scrape import log, scrape_plays, scrape_structure


def _insert_running_run(conn, run_id: str, season: str) -> None:
    from .db import insert_rows

    insert_rows(
        conn,
        "pipeline_runs",
        [
            {
                "run_id": run_id,
                "season": season,
                "started_at": datetime.now(timezone.utc),
                "finished_at": None,
                "status": "running",
                "standings_count": None,
                "schedule_count": None,
                "games_count": None,
                "notes": None,
            }
        ],
    )


def _finish_completed_run(
    conn,
    run_id: str,
    standings_count: int | None = None,
    schedule_count: int | None = None,
    games_count: int | None = None,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE pipeline_runs
        SET finished_at = ?, status = ?, standings_count = ?, schedule_count = ?, games_count = ?, notes = ?
        WHERE run_id = ?
        """,
        [
            datetime.now(timezone.utc),
            "completed",
            standings_count,
            schedule_count,
            games_count,
            notes,
            run_id,
        ],
    )


def _finish_failed_run(conn, run_id: str, exc: Exception) -> None:
    conn.execute(
        """
        UPDATE pipeline_runs
        SET finished_at = ?, status = ?, notes = ?
        WHERE run_id = ?
        """,
        [datetime.now(timezone.utc), "failed", str(exc), run_id],
    )


def _resolve_source_run_id(conn, season: str, source_run_id: str | None) -> str:
    if source_run_id:
        row = conn.execute(
            "SELECT COUNT(*) FROM games WHERE season = ? AND run_id = ?",
            [season, source_run_id],
        ).fetchone()
        if row and row[0] > 0:
            return source_run_id
        raise RuntimeError(f"No games rows found for season={season} run_id={source_run_id}")

    row = conn.execute(
        """
        SELECT pr.run_id
        FROM pipeline_runs pr
        JOIN games g
          ON g.run_id = pr.run_id
         AND g.season = pr.season
        WHERE pr.season = ?
          AND pr.status = 'completed'
        GROUP BY pr.run_id, pr.finished_at, pr.started_at
        ORDER BY COALESCE(pr.finished_at, pr.started_at) DESC, pr.run_id DESC
        LIMIT 1
        """,
        [season],
    ).fetchone()
    if not row:
        raise RuntimeError(f"No games rows available for season={season}. Run structure scrape first.")
    return row[0]


def _load_games_rows(conn, season: str, source_run_id: str) -> list[dict[str, str]]:
    cursor = conn.execute(
        """
        SELECT
            run_id,
            season,
            game_id,
            game_date,
            pbp_url,
            schedule_home,
            schedule_away,
            home_team_canonical,
            away_team_canonical,
            team_1,
            team_2,
            schedule_row_count,
            unique_team_count,
            pairing_status
        FROM games
        WHERE season = ? AND run_id = ?
        ORDER BY game_date, game_id
        """,
        [season, source_run_id],
    )
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def main_structure(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape standings, schedules, and games into DuckDB.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args(argv)

    from .db import connect, init_db, insert_rows

    run_id = str(uuid.uuid4())
    conn = connect(args.db_path)
    init_db(conn)
    _insert_running_run(conn, run_id, args.season)

    try:
        log(f"RUN   started season={args.season} db={args.db_path} delay={args.delay:.1f}s")
        result = scrape_structure(args.season, args.delay, run_id)
        insert_rows(conn, "raw_standings_html", result["raw_standings_rows"])
        insert_rows(conn, "raw_schedule_html", result["raw_schedule_rows"])
        insert_rows(conn, "standings", result["standings_rows"])
        insert_rows(conn, "schedule", result["schedule_rows"])
        insert_rows(conn, "games", result["games_rows"])

        _finish_completed_run(
            conn,
            run_id,
            standings_count=len(result["standings_rows"]),
            schedule_count=len(result["schedule_rows"]),
            games_count=len(result["games_rows"]),
        )

        log(
            f"WRITE standings={len(result['standings_rows'])} "
            f"schedule={len(result['schedule_rows'])} games={len(result['games_rows'])}"
        )
        log(f"DONE  run_id={run_id} db={args.db_path}")
        return 0
    except Exception as exc:
        _finish_failed_run(conn, run_id, exc)
        log(f"FAIL  run_id={run_id} -> {exc}")
        print(f"Run failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def main_plays(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape game play-by-play into DuckDB.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--source-run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    from .db import connect, init_db, insert_rows

    run_id = str(uuid.uuid4())
    conn = connect(args.db_path)
    init_db(conn)
    _insert_running_run(conn, run_id, args.season)

    try:
        source_run_id = _resolve_source_run_id(conn, args.season, args.source_run_id)
        games_rows = _load_games_rows(conn, args.season, source_run_id)
        if args.limit is not None:
            if args.limit <= 0:
                raise RuntimeError("--limit must be greater than 0")
            games_rows = games_rows[: args.limit]

        log(
            f"RUN   started plays season={args.season} db={args.db_path} "
            f"delay={args.delay:.1f}s source_run_id={source_run_id}"
            f"{f' limit={args.limit}' if args.limit is not None else ''}"
        )
        result = scrape_plays(games_rows, args.season, args.delay, run_id, source_run_id)
        insert_rows(conn, "raw_pbp_html", result["raw_pbp_rows"])
        insert_rows(conn, "plays", result["plays_rows"])
        insert_rows(conn, "failed_game_fetches", result["failed_rows"])

        _finish_completed_run(
            conn,
            run_id,
            notes=result["summary_notes"],
        )
        log(f"DONE  run_id={run_id} db={args.db_path}")
        return 0
    except KeyboardInterrupt as exc:
        _finish_failed_run(conn, run_id, exc)
        log(f"STOP  run_id={run_id} -> interrupted by user")
        print("Run interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        _finish_failed_run(conn, run_id, exc)
        log(f"FAIL  run_id={run_id} -> {exc}")
        print(f"Run failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    return main_structure(argv)


if __name__ == "__main__":
    raise SystemExit(main())
