from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

from .constants import DEFAULT_DB_PATH, DEFAULT_DELAY, DEFAULT_SEASON
from .crosswalk import (
    build_memory_seed_rows,
    build_team_prefix_memory,
    build_crosswalk_resolution_rows,
    build_field_position_prefix_rows,
    build_field_position_rows,
)
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


def _load_plays_rows(conn, season: str, source_plays_run_id: str) -> list[dict[str, object]]:
    cursor = conn.execute(
        """
        SELECT *
        FROM plays
        WHERE season = ? AND run_id = ?
        ORDER BY game_id, play_id
        """,
        [season, source_plays_run_id],
    )
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _load_raw_pbp_rows(conn, season: str, source_plays_run_id: str) -> list[dict[str, object]]:
    cursor = conn.execute(
        """
        SELECT *
        FROM raw_pbp_html
        WHERE season = ? AND run_id = ?
        ORDER BY game_id
        """,
        [season, source_plays_run_id],
    )
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _resolve_plays_run_id(conn, season: str, source_plays_run_id: str | None) -> str:
    if source_plays_run_id:
        row = conn.execute(
            "SELECT COUNT(*) FROM plays WHERE season = ? AND run_id = ?",
            [season, source_plays_run_id],
        ).fetchone()
        if row and row[0] > 0:
            return source_plays_run_id
        raise RuntimeError(f"No plays rows found for season={season} run_id={source_plays_run_id}")

    row = conn.execute(
        """
        SELECT run_id
        FROM pipeline_runs
        WHERE season = ?
          AND status = 'completed'
          AND notes LIKE '%"plays_count"%'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        [season],
    ).fetchone()
    if not row:
        raise RuntimeError(f"No plays runs available for season={season}. Run plays scrape first.")
    return row[0]


def _load_detected_prefix_rows(conn, season: str, source_plays_run_id: str) -> list[dict[str, object]]:
    cursor = conn.execute(
        """
        SELECT *
        FROM field_position_prefixes
        WHERE season = ? AND source_plays_run_id = ?
        ORDER BY game_id, prefix
        """,
        [season, source_plays_run_id],
    )
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _load_crosswalk_rows(
    conn,
    season: str,
    source_plays_run_id: str | None = None,
) -> list[dict[str, object]]:
    sql = """
        SELECT *
        FROM field_position_crosswalk
        WHERE season = ?
    """
    params: list[object] = [season]
    if source_plays_run_id is not None:
        sql += " AND source_plays_run_id = ?"
        params.append(source_plays_run_id)
    sql += " ORDER BY game_id, prefix"
    cursor = conn.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _resolve_structure_run_id_for_plays_run(conn, plays_run_id: str) -> str:
    row = conn.execute(
        "SELECT notes FROM pipeline_runs WHERE run_id = ?",
        [plays_run_id],
    ).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"No pipeline_runs notes found for plays run {plays_run_id}")
    try:
        notes = json.loads(row[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse pipeline_runs notes for plays run {plays_run_id}") from exc
    source_run_id = notes.get("source_run_id")
    if not source_run_id:
        raise RuntimeError(f"source_run_id missing from pipeline_runs notes for plays run {plays_run_id}")
    return str(source_run_id)


def _print_review_rows(rows: list[tuple[object, ...]]) -> None:
    for row in rows:
        print(" | ".join("" if value is None else str(value) for value in row))


def _print_field_position_queue(rows: list[dict[str, object]]) -> None:
    print(
        "queue | game_id | team_1 | team_2 | schedule_home | schedule_away | "
        "prefix_a | prefix_b | prefix_count | resolved_count"
    )
    _print_review_rows(
        [
            (
                row["queue_index"],
                row["game_id"],
                row["team_1"],
                row["team_2"],
                row["schedule_home"],
                row["schedule_away"],
                row["prefix_a"],
                row["prefix_b"],
                row["prefix_count"],
                row["resolved_count"],
            )
            for row in rows
        ]
    )


def _load_field_position_review_queue(
    conn,
    season: str,
    source_plays_run_id: str,
    include_resolved: bool = False,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT
                p.game_id,
                p.team_1,
                p.team_2,
                p.schedule_home,
                p.schedule_away,
                p.prefix,
                row_number() OVER (PARTITION BY p.game_id ORDER BY p.prefix) AS prefix_rank,
                COUNT(c.prefix) OVER (PARTITION BY p.game_id) AS resolved_count
            FROM field_position_prefixes p
            LEFT JOIN field_position_crosswalk c
              ON c.season = p.season
             AND c.source_plays_run_id = p.source_plays_run_id
             AND c.game_id = p.game_id
             AND c.prefix = p.prefix
            WHERE p.season = ? AND p.source_plays_run_id = ?
        )
        SELECT
            game_id,
            team_1,
            team_2,
            schedule_home,
            schedule_away,
            MAX(CASE WHEN prefix_rank = 1 THEN prefix END) AS prefix_a,
            MAX(CASE WHEN prefix_rank = 2 THEN prefix END) AS prefix_b,
            COUNT(*) AS prefix_count,
            MAX(COALESCE(resolved_count, 0)) AS resolved_count
        FROM ranked
        GROUP BY 1,2,3,4,5
        ORDER BY game_id
        """,
        [season, source_plays_run_id],
    ).fetchall()
    queue: list[dict[str, object]] = []
    next_index = 1
    for row in rows:
        record = {
            "queue_index": None,
            "game_id": row[0],
            "team_1": row[1],
            "team_2": row[2],
            "schedule_home": row[3],
            "schedule_away": row[4],
            "prefix_a": row[5],
            "prefix_b": row[6],
            "prefix_count": row[7],
            "resolved_count": row[8],
        }
        if include_resolved or record["resolved_count"] < record["prefix_count"]:
            record["queue_index"] = next_index
            next_index += 1
            queue.append(record)
    return queue


def _upsert_crosswalk_rows(
    conn,
    prefix_rows: list[dict[str, object]],
    season: str,
    source_plays_run_id: str,
    game_id: str,
    prefix: str,
    canonical_team: str,
    note: str = "",
    resolution_method: str = "manual",
) -> list[dict[str, object]]:
    from .db import insert_rows

    rows = build_crosswalk_resolution_rows(
        prefix_rows,
        season,
        source_plays_run_id,
        game_id,
        prefix,
        canonical_team,
        note,
        resolution_method=resolution_method,
    )
    conn.execute(
        """
        DELETE FROM field_position_crosswalk
        WHERE season = ? AND source_plays_run_id = ? AND game_id = ?
        """,
        [season, source_plays_run_id, game_id],
    )
    insert_rows(conn, "field_position_crosswalk", rows)
    return rows


def _preseed_memory_crosswalk_rows(
    conn,
    prefix_rows: list[dict[str, object]],
    season: str,
    source_plays_run_id: str,
) -> int:
    existing_rows = _load_crosswalk_rows(conn, season)
    team_prefix_memory = build_team_prefix_memory(existing_rows)
    if not team_prefix_memory:
        return 0

    existing_game_ids = {
        str(row.get("game_id") or "")
        for row in existing_rows
        if str(row.get("source_plays_run_id") or "") == source_plays_run_id
    }
    candidate_prefix_rows = [
        row
        for row in prefix_rows
        if str(row.get("game_id") or "") not in existing_game_ids
    ]
    seeded_rows = build_memory_seed_rows(
        candidate_prefix_rows,
        team_prefix_memory,
        season,
        source_plays_run_id,
    )
    if not seeded_rows:
        return 0

    from .db import insert_rows

    insert_rows(conn, "field_position_crosswalk", seeded_rows)
    return len({str(row["game_id"]) for row in seeded_rows})


def _run_field_position_review_loop(
    conn,
    prefix_rows: list[dict[str, object]],
    season: str,
    source_plays_run_id: str,
) -> int:
    resolved_games = 0
    skipped_games = 0
    initial_queue = _load_field_position_review_queue(conn, season, source_plays_run_id)
    initial_total = len(initial_queue)
    while True:
        queue = _load_field_position_review_queue(conn, season, source_plays_run_id)
        if not queue:
            print("No unresolved field-position games remain for this plays run.")
            break

        current = queue[0]
        remaining_games = len(queue)
        completed_games = initial_total - remaining_games
        team_1 = str(current["team_1"] or "")
        team_2 = str(current["team_2"] or "")
        prefix_a = str(current["prefix_a"] or "")
        prefix_b = str(current["prefix_b"] or "")

        print()
        print(
            f"Progress: completed={completed_games}/{initial_total} "
            f"resolved_this_session={resolved_games} skipped={skipped_games} remaining={remaining_games}"
        )
        print(
            f"Queue {current['queue_index']} | game_id={current['game_id']} | "
            f"{team_1} vs {team_2}"
        )
        print(
            f"schedule_home={current['schedule_home']} | "
            f"schedule_away={current['schedule_away']}"
        )
        print(f"a = {prefix_a}")
        print(f"b = {prefix_b}")
        print(f"Which prefix belongs to {team_1}? [a/b/s/q]")

        choice = input("> ").strip().lower()
        if choice == "q":
            print(f"Stopped review. Resolved {resolved_games} games, skipped {skipped_games}.")
            break
        if choice == "s":
            skipped_games += 1
            print(f"Skipped {current['game_id']}.")
            continue
        if choice not in {"a", "b"}:
            print("Please enter a, b, s, or q.")
            continue

        chosen_prefix = prefix_a if choice == "a" else prefix_b
        rows = _upsert_crosswalk_rows(
            conn,
            prefix_rows,
            season,
            source_plays_run_id,
            str(current["game_id"]),
            chosen_prefix,
            team_1,
            note="review-queue",
            resolution_method="manual-review-queue",
        )
        resolved_games += 1
        print("Resolved crosswalk rows:")
        for row in rows:
            print(f"{row['game_id']} | {row['prefix']} -> {row['canonical_team']}")
        auto_seeded_games = _preseed_memory_crosswalk_rows(
            conn,
            prefix_rows,
            season,
            source_plays_run_id,
        )
        if auto_seeded_games:
            print(f"Auto-seeded {auto_seeded_games} additional games from remembered prefixes.")

    return 0


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
        log(f"WRITE plays insert start rows={len(result['plays_rows'])}")
        insert_rows(
            conn,
            "plays",
            result["plays_rows"],
            chunk_size=5000,
            progress_label="plays",
            progress_logger=log,
        )
        log("WRITE plays insert done")
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


def main_rebuild_plays_from_raw(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-parse stored raw play-by-play HTML into a fresh plays run.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--source-plays-run-id", default=None)
    args = parser.parse_args(argv)

    from .db import connect, init_db, insert_rows
    from .parse import parse_pbp_html

    run_id = str(uuid.uuid4())
    conn = connect(args.db_path)
    init_db(conn)
    _insert_running_run(conn, run_id, args.season)

    try:
        source_plays_run_id = _resolve_plays_run_id(conn, args.season, args.source_plays_run_id)
        structure_run_id = _resolve_structure_run_id_for_plays_run(conn, source_plays_run_id)
        games_rows = _load_games_rows(conn, args.season, structure_run_id)
        games_by_id = {str(row["game_id"]): row for row in games_rows}
        raw_rows = _load_raw_pbp_rows(conn, args.season, source_plays_run_id)
        if not raw_rows:
            raise RuntimeError(
                f"No raw_pbp_html rows found for season={args.season} plays_run_id={source_plays_run_id}"
            )

        log(
            f"RUN   started reparse season={args.season} db={args.db_path} "
            f"source_plays_run_id={source_plays_run_id}"
        )
        log(
            f"BEGIN reparse season={args.season} run_id={run_id} "
            f"source_plays_run_id={source_plays_run_id}"
        )
        log("STAGE reparse")

        plays_rows: list[dict[str, object]] = []
        zero_play_game_ids: list[str] = []
        for index, raw_row in enumerate(raw_rows, start=1):
            game_id = str(raw_row["game_id"])
            game = games_by_id.get(game_id)
            if game is None:
                raise RuntimeError(
                    f"Could not find canonical games row for game_id={game_id} "
                    f"from structure run {structure_run_id}"
                )
            parsed_rows = parse_pbp_html(str(raw_row["html_text"]), game, args.season, run_id)
            if not parsed_rows:
                zero_play_game_ids.append(game_id)
                log(f"EMPTY reparse {game_id} -> 0 plays parsed")
                continue
            plays_rows.extend(parsed_rows)
            log(f"PARSE reparse [{index}/{len(raw_rows)}] {game_id} -> {len(parsed_rows)} rows")

        log(f"WRITE reparse insert start rows={len(plays_rows)}")
        insert_rows(
            conn,
            "plays",
            plays_rows,
            chunk_size=5000,
            progress_label="reparse plays",
            progress_logger=log,
        )
        log("WRITE reparse insert done")
        _finish_completed_run(
            conn,
            run_id,
            notes=json.dumps(
                {
                    "source_run_id": structure_run_id,
                    "reparsed_from_plays_run_id": source_plays_run_id,
                    "raw_pbp_count": len(raw_rows),
                    "plays_count": len(plays_rows),
                },
                sort_keys=True,
            ),
        )
        log(f"WRITE reparse raw_pbp={len(raw_rows)} plays={len(plays_rows)}")
        if zero_play_game_ids:
            log("ZERO  reparse parsed 0 plays for game_ids=" + ", ".join(zero_play_game_ids))
        log(f"DONE  run_id={run_id} db={args.db_path}")
        return 0
    except Exception as exc:
        _finish_failed_run(conn, run_id, exc)
        log(f"FAIL  run_id={run_id} -> {exc}")
        print(f"Run failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    return main_structure(argv)


def main_prepare_field_positions(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect field-position prefixes from a plays run.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--source-plays-run-id", default=None)
    parser.add_argument("--limit-games", type=int, default=None)
    parser.add_argument("--include-resolved", action="store_true")
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args(argv)

    from .db import connect, init_db, insert_rows

    conn = connect(args.db_path)
    init_db(conn)
    try:
        source_plays_run_id = _resolve_plays_run_id(conn, args.season, args.source_plays_run_id)
        plays_rows = _load_plays_rows(conn, args.season, source_plays_run_id)
        structure_run_id = _resolve_structure_run_id_for_plays_run(conn, source_plays_run_id)
        games_rows = _load_games_rows(conn, args.season, structure_run_id)
        games_by_id = {row["game_id"]: row for row in games_rows}

        prefix_rows = build_field_position_prefix_rows(plays_rows, games_by_id, args.season, source_plays_run_id)
        if args.limit_games is not None:
            keep_game_ids = []
            for row in prefix_rows:
                game_id = str(row["game_id"])
                if game_id not in keep_game_ids:
                    keep_game_ids.append(game_id)
                if len(keep_game_ids) >= args.limit_games:
                    break
            prefix_rows = [row for row in prefix_rows if str(row["game_id"]) in set(keep_game_ids)]

        conn.execute(
            "DELETE FROM field_position_prefixes WHERE season = ? AND source_plays_run_id = ?",
            [args.season, source_plays_run_id],
        )
        insert_rows(conn, "field_position_prefixes", prefix_rows)
        auto_seeded_games = _preseed_memory_crosswalk_rows(
            conn,
            prefix_rows,
            args.season,
            source_plays_run_id,
        )

        rows = _load_field_position_review_queue(
            conn,
            args.season,
            source_plays_run_id,
            include_resolved=args.include_resolved,
        )

        _print_field_position_queue(rows)
        if auto_seeded_games:
            print(f"\nAuto-seeded {auto_seeded_games} games from prior confirmed team-prefix memory.")
        print(f"\nDetected {len(prefix_rows)} prefix rows across {len(rows)} queued games for plays run {source_plays_run_id}.")
        if args.review:
            return _run_field_position_review_loop(conn, prefix_rows, args.season, source_plays_run_id)
        return 0
    finally:
        conn.close()


def main_resolve_field_position_prefix(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve one field-position prefix and auto-assign the other side.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--source-plays-run-id", default=None)
    parser.add_argument("--game-id")
    parser.add_argument("--prefix")
    parser.add_argument("--queue-index", type=int)
    parser.add_argument("--which", choices=["a", "b"])
    parser.add_argument("--canonical-team", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)

    from .db import connect, init_db, insert_rows

    conn = connect(args.db_path)
    init_db(conn)
    try:
        source_plays_run_id = _resolve_plays_run_id(conn, args.season, args.source_plays_run_id)
        prefix_rows = _load_detected_prefix_rows(conn, args.season, source_plays_run_id)
        if not prefix_rows:
            raise RuntimeError(
                f"No detected prefixes found for plays run {source_plays_run_id}. Run prepare_field_positions first."
            )

        game_id = args.game_id
        prefix = args.prefix
        if args.queue_index is not None:
            queue = _load_field_position_review_queue(conn, args.season, source_plays_run_id)
            chosen = next((row for row in queue if row["queue_index"] == args.queue_index), None)
            if chosen is None:
                raise RuntimeError(f"queue-index {args.queue_index} not found in unresolved review queue")
            if not args.which:
                raise RuntimeError("--which is required when using --queue-index")
            game_id = str(chosen["game_id"])
            prefix = str(chosen["prefix_a"] if args.which == "a" else chosen["prefix_b"])

        if not game_id or not prefix:
            raise RuntimeError("Provide either --game-id and --prefix, or --queue-index and --which")

        rows = _upsert_crosswalk_rows(
            conn,
            prefix_rows,
            args.season,
            source_plays_run_id,
            game_id,
            prefix,
            args.canonical_team,
            note=args.note,
        )
        print("Resolved crosswalk rows:")
        for row in rows:
            print(f"{row['game_id']} | {row['prefix']} -> {row['canonical_team']}")
        return 0
    finally:
        conn.close()


def main_apply_field_positions(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply field-position crosswalk rows to a plays run.")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--source-plays-run-id", default=None)
    args = parser.parse_args(argv)

    from .db import connect, init_db, insert_rows

    run_id = str(uuid.uuid4())
    conn = connect(args.db_path)
    init_db(conn)
    _insert_running_run(conn, run_id, args.season)

    try:
        source_plays_run_id = _resolve_plays_run_id(conn, args.season, args.source_plays_run_id)
        plays_rows = _load_plays_rows(conn, args.season, source_plays_run_id)
        crosswalk_rows = conn.execute(
            """
            SELECT game_id, prefix, canonical_team
            FROM field_position_crosswalk
            WHERE season = ? AND source_plays_run_id = ?
            """,
            [args.season, source_plays_run_id],
        ).fetchall()
        crosswalk = {(str(game_id), str(prefix)): str(canonical_team) for game_id, prefix, canonical_team in crosswalk_rows}
        enriched_rows = build_field_position_rows(
            plays_rows,
            crosswalk,
            args.season,
            source_plays_run_id,
            run_id,
        )
        insert_rows(conn, "play_field_positions", enriched_rows)
        unresolved_count = sum(1 for row in enriched_rows if row["resolution_status"] != "resolved")
        _finish_completed_run(
            conn,
            run_id,
            notes=json.dumps(
                {
                    "source_plays_run_id": source_plays_run_id,
                    "field_position_rows": len(enriched_rows),
                    "resolved_count": len(enriched_rows) - unresolved_count,
                    "unresolved_count": unresolved_count,
                },
                sort_keys=True,
            ),
        )
        print(
            f"Applied field positions for plays run {source_plays_run_id}: "
            f"{len(enriched_rows)} rows, {unresolved_count} unresolved."
        )
        return 0
    except Exception as exc:
        _finish_failed_run(conn, run_id, exc)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
