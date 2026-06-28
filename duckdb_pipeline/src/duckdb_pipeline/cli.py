from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone

from .constants import DEFAULT_DB_PATH, DEFAULT_DELAY, DEFAULT_SEASON
from .scrape import log, scrape_structure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape standings, schedules, and games into DuckDB.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args(argv)

    from .db import connect, init_db, insert_rows

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    conn = connect(args.db_path)
    init_db(conn)
    insert_rows(
        conn,
        "pipeline_runs",
        [
            {
                "run_id": run_id,
                "season": args.season,
                "started_at": started_at,
                "finished_at": None,
                "status": "running",
                "standings_count": None,
                "schedule_count": None,
                "games_count": None,
                "notes": None,
            }
        ],
    )

    try:
        log(f"RUN   started season={args.season} db={args.db_path} delay={args.delay:.1f}s")
        result = scrape_structure(args.season, args.delay, run_id)
        insert_rows(conn, "raw_standings_html", result["raw_standings_rows"])
        insert_rows(conn, "raw_schedule_html", result["raw_schedule_rows"])
        insert_rows(conn, "standings", result["standings_rows"])
        insert_rows(conn, "schedule", result["schedule_rows"])
        insert_rows(conn, "games", result["games_rows"])

        finished_at = datetime.now(timezone.utc)
        conn.execute(
            """
            UPDATE pipeline_runs
            SET finished_at = ?, status = ?, standings_count = ?, schedule_count = ?, games_count = ?
            WHERE run_id = ?
            """,
            [
                finished_at,
                "completed",
                len(result["standings_rows"]),
                len(result["schedule_rows"]),
                len(result["games_rows"]),
                run_id,
            ],
        )

        log(f"WRITE standings={len(result['standings_rows'])} schedule={len(result['schedule_rows'])} games={len(result['games_rows'])}")
        log(f"DONE  run_id={run_id} db={args.db_path}")
        return 0
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        conn.execute(
            """
            UPDATE pipeline_runs
            SET finished_at = ?, status = ?, notes = ?
            WHERE run_id = ?
            """,
            [finished_at, "failed", str(exc), run_id],
        )
        log(f"FAIL  run_id={run_id} -> {exc}")
        print(f"Run failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
