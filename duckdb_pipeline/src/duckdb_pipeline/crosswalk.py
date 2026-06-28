from __future__ import annotations

from datetime import datetime, timezone

from .parse import RE_FIELD_POS, normalize_field_position


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def extract_field_position_prefix(field_position: str | None) -> str | None:
    normalized = normalize_field_position(field_position)
    if not normalized:
        return None
    match = RE_FIELD_POS.match(normalized)
    if not match:
        return None
    return match.group(1).strip()


def build_field_position_prefix_rows(
    plays_rows: list[dict[str, object]],
    games_by_id: dict[str, dict[str, str]],
    season: str,
    source_plays_run_id: str,
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in plays_rows:
        game_id = str(row.get("game_id") or "").strip()
        prefix = extract_field_position_prefix(str(row.get("field_position") or ""))
        if not game_id or not prefix:
            continue
        grouped.setdefault((game_id, prefix), []).append(row)

    detected_at = utc_now()
    result: list[dict[str, object]] = []
    for (game_id, prefix), rows in sorted(grouped.items()):
        game = games_by_id.get(game_id, {})
        play_ids = [int(row["play_id"]) for row in rows if row.get("play_id") is not None]
        result.append(
            {
                "season": season,
                "source_plays_run_id": source_plays_run_id,
                "game_id": game_id,
                "prefix": prefix,
                "team_1": game.get("team_1", ""),
                "team_2": game.get("team_2", ""),
                "schedule_home": game.get("schedule_home", ""),
                "schedule_away": game.get("schedule_away", ""),
                "play_count": len(rows),
                "first_play_id": min(play_ids) if play_ids else None,
                "last_play_id": max(play_ids) if play_ids else None,
                "detected_at": detected_at,
            }
        )
    return result


def build_crosswalk_resolution_rows(
    prefix_rows: list[dict[str, object]],
    season: str,
    source_plays_run_id: str,
    game_id: str,
    chosen_prefix: str,
    canonical_team: str,
    note: str | None = None,
    resolution_method: str = "manual",
) -> list[dict[str, object]]:
    game_prefix_rows = [row for row in prefix_rows if row["game_id"] == game_id]
    if not game_prefix_rows:
        raise RuntimeError(f"No detected prefixes found for game_id={game_id}")

    unique_prefixes = sorted({str(row["prefix"]) for row in game_prefix_rows})
    if chosen_prefix not in unique_prefixes:
        raise RuntimeError(f"Prefix {chosen_prefix} not found for game_id={game_id}")
    if len(unique_prefixes) != 2:
        raise RuntimeError(
            f"Expected exactly 2 prefixes for auto-resolution, found {len(unique_prefixes)} for game_id={game_id}"
        )

    sample = game_prefix_rows[0]
    team_1 = str(sample.get("team_1") or "")
    team_2 = str(sample.get("team_2") or "")
    if canonical_team not in {team_1, team_2}:
        raise RuntimeError(f"Canonical team {canonical_team} is not one of [{team_1}, {team_2}]")

    other_prefix = next(prefix for prefix in unique_prefixes if prefix != chosen_prefix)
    other_team = team_2 if canonical_team == team_1 else team_1
    resolved_at = utc_now()

    return [
        {
            "season": season,
            "source_plays_run_id": source_plays_run_id,
            "game_id": game_id,
            "prefix": chosen_prefix,
            "canonical_team": canonical_team,
            "resolution_method": resolution_method,
            "note": note or "",
            "resolved_at": resolved_at,
        },
        {
            "season": season,
            "source_plays_run_id": source_plays_run_id,
            "game_id": game_id,
            "prefix": other_prefix,
            "canonical_team": other_team,
            "resolution_method": resolution_method,
            "note": note or "",
            "resolved_at": resolved_at,
        },
    ]


def build_field_position_rows(
    plays_rows: list[dict[str, object]],
    crosswalk_by_game_prefix: dict[tuple[str, str], str],
    season: str,
    source_plays_run_id: str,
    enrichment_run_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for play in plays_rows:
        game_id = str(play.get("game_id") or "")
        play_id = play.get("play_id")
        field_position = str(play.get("field_position") or "")
        offense = str(play.get("offense") or "")
        yardline_raw = play.get("yardline_raw")
        prefix = extract_field_position_prefix(field_position)
        prefix_owner = crosswalk_by_game_prefix.get((game_id, prefix)) if prefix else None

        field_pos_side = ""
        yardline_100 = None
        resolution_status = "no-field-position"
        if prefix and yardline_raw is not None:
            if prefix_owner:
                field_pos_side = "own" if prefix_owner == offense else "opponent"
                yardline_100 = 100 - int(yardline_raw) if field_pos_side == "own" else int(yardline_raw)
                resolution_status = "resolved"
            else:
                resolution_status = "unresolved-prefix"

        rows.append(
            {
                "run_id": enrichment_run_id,
                "season": season,
                "source_plays_run_id": source_plays_run_id,
                "game_id": game_id,
                "play_id": play_id,
                "field_position": field_position,
                "field_pos_prefix": prefix or "",
                "yardline_raw": yardline_raw,
                "offense": offense,
                "prefix_owner": prefix_owner or "",
                "field_pos_side": field_pos_side,
                "yardline_100": yardline_100,
                "resolution_status": resolution_status,
                "created_at": utc_now(),
            }
        )
    return rows


def build_team_prefix_memory(crosswalk_rows: list[dict[str, object]]) -> dict[str, set[str]]:
    candidates: dict[str, set[str]] = {}
    for row in crosswalk_rows:
        prefix = str(row.get("prefix") or "").strip()
        canonical_team = str(row.get("canonical_team") or "").strip()
        if not prefix or not canonical_team:
            continue
        candidates.setdefault(canonical_team, set()).add(prefix)
    return candidates


def build_memory_seed_rows(
    prefix_rows: list[dict[str, object]],
    team_prefix_memory: dict[str, set[str]],
    season: str,
    source_plays_run_id: str,
) -> list[dict[str, object]]:
    prefix_rows_by_game: dict[str, list[dict[str, object]]] = {}
    for row in prefix_rows:
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        prefix_rows_by_game.setdefault(game_id, []).append(row)

    seeded_rows: list[dict[str, object]] = []
    for game_id, game_rows in sorted(prefix_rows_by_game.items()):
        if len(game_rows) != 2:
            continue

        prefixes = [str(row.get("prefix") or "").strip() for row in game_rows]
        if not all(prefixes):
            continue

        sample = game_rows[0]
        team_1 = str(sample.get("team_1") or "").strip()
        team_2 = str(sample.get("team_2") or "").strip()
        valid_teams = {team_1, team_2} - {""}
        if len(valid_teams) != 2:
            continue

        team_1_matches = [prefix for prefix in prefixes if prefix in team_prefix_memory.get(team_1, set())]
        team_2_matches = [prefix for prefix in prefixes if prefix in team_prefix_memory.get(team_2, set())]

        remembered_prefix = ""
        remembered_team = ""

        if len(team_1_matches) == 1 and len(team_2_matches) == 1:
            if team_1_matches[0] != team_2_matches[0]:
                remembered_prefix = team_1_matches[0]
                remembered_team = team_1
        elif len(team_1_matches) == 1 and not team_2_matches:
            remembered_prefix = team_1_matches[0]
            remembered_team = team_1
        elif len(team_2_matches) == 1 and not team_1_matches:
            remembered_prefix = team_2_matches[0]
            remembered_team = team_2

        if remembered_prefix and remembered_team:
            seeded_rows.extend(
                build_crosswalk_resolution_rows(
                    prefix_rows,
                    season,
                    source_plays_run_id,
                    game_id,
                    remembered_prefix,
                    remembered_team,
                    note="preseeded from prior confirmed team-prefix memory",
                    resolution_method="auto-memory",
                )
            )

    return seeded_rows
