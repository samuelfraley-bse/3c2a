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


def _backfill_pipeline_run_stages(conn) -> None:
    """Assign `stage` to legacy pipeline_runs rows written before the column existed.

    Uses the same signals the `v_current_*_runs` views used to sniff stage from
    before this column existed, so backfilled rows resolve identically to how
    they resolved previously.
    """
    conn.execute(
        """
        UPDATE pipeline_runs
        SET stage = CASE
            WHEN games_count IS NOT NULL THEN 'structure'
            WHEN notes LIKE '%"plays_count"%' THEN 'plays'
            WHEN notes LIKE '%"field_position_rows"%' THEN 'field_position'
            ELSE stage
        END
        WHERE stage IS NULL
        """
    )


def _backfill_plays_safety_and_defensive_td(conn) -> None:
    """Backfill `is_safety` / `is_defensive_td` for plays rows written before
    these columns existed.

    Both are fully recoverable from data already stored on the row (raw_text
    and is_interception), so this can run as a plain idempotent backfill
    instead of requiring a `rebuild_plays_from_raw` reparse. `is_defensive_td`
    here only covers the interception-return (pick-six) case, since that is
    unambiguous from raw_text alone; the fumble-recovery case is resolved
    separately at the view layer in `v_play_context_current` using the
    field-position crosswalk.
    """
    conn.execute(
        """
        UPDATE plays
        SET is_safety = COALESCE(raw_text ILIKE '%safety%', FALSE)
        WHERE is_safety IS NULL
        """
    )
    conn.execute(
        """
        UPDATE plays
        SET is_defensive_td = (
            COALESCE(is_interception, FALSE)
            AND COALESCE(raw_text ILIKE '%touchdown%', FALSE)
        )
        WHERE is_defensive_td IS NULL
        """
    )


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
              AND stage = 'structure'
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
              AND stage = 'plays'
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
              AND stage = 'field_position'
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
        CREATE OR REPLACE VIEW v_current_lineup_stats_runs AS
        WITH ranked AS (
            SELECT
                run_id,
                season,
                started_at,
                finished_at,
                CASE
                    WHEN json_valid(notes) THEN json_extract_string(notes, '$.source_lineup_json_run_id')
                    ELSE NULL
                END AS source_lineup_json_run_id,
                CASE
                    WHEN json_valid(notes) THEN TRY_CAST(json_extract_string(notes, '$.player_count') AS INTEGER)
                    ELSE NULL
                END AS player_count,
                ROW_NUMBER() OVER (
                    PARTITION BY season
                    ORDER BY COALESCE(finished_at, started_at) DESC, run_id DESC
                ) AS rn
            FROM pipeline_runs
            WHERE status = 'completed'
              AND stage = 'lineup_stats'
        )
        SELECT
            season,
            run_id AS lineup_stats_run_id,
            source_lineup_json_run_id,
            started_at,
            finished_at,
            player_count
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
            f.source_plays_run_id AS field_position_source_plays_run_id,
            -- True whenever the current field_position run wasn't built
            -- from the current plays run (including "no field_position run
            -- exists at all yet") -- i.e. play_field_positions/yardline_100
            -- is stale and needs `apply_field_positions` re-run. See
            -- LOGS.md: this used to fail silently (yardline_100 just went
            -- NULL) until this column made it visible.
            (f.source_plays_run_id IS NULL OR f.source_plays_run_id <> p.plays_run_id) AS field_position_is_stale
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
        CREATE OR REPLACE VIEW v_standings_current AS
        SELECT
            s.season,
            s.run_id,
            s.conference,
            s.team_name,
            s.team_id,
            s.schedule_url,
            TRY_CAST(s.overall_gp AS INTEGER) AS games,
            TRY_CAST(s.overall_w AS INTEGER) AS wins,
            TRY_CAST(s.overall_l AS INTEGER) AS losses,
            TRY_CAST(s.overall_t AS INTEGER) AS ties,
            TRY_CAST(s.overall_pct AS DOUBLE) AS win_pct,
            TRY_CAST(s.conf_gp AS INTEGER) AS conference_games,
            TRY_CAST(s.conf_w AS INTEGER) AS conference_wins,
            TRY_CAST(s.conf_l AS INTEGER) AS conference_losses,
            TRY_CAST(s.conf_t AS INTEGER) AS conference_ties,
            TRY_CAST(s.conf_pct AS DOUBLE) AS conference_win_pct
        FROM standings s
        JOIN v_current_structure_runs r
          ON r.season = s.season
         AND r.structure_run_id = s.run_id
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_schedule_current AS
        -- Running overall W/L/T record *entering* each game (not including
        -- it), parsed from the raw `result` text (e.g. "W, 42-7"/"L, 7-42";
        -- may be blank/score-less for future/unplayed games -- those rows
        -- just don't match 'W'/'L'/'T' and contribute 0). Uses the same
        -- ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING pattern already
        -- established in game_score_state's pre-play score state.
        --
        -- NOTE: this is the OVERALL record only. There is no per-game
        -- conference-game flag anywhere in this pipeline today (the
        -- conference_wins/conference_losses on v_standings_current come
        -- from a separately-scraped season-end totals row, not derived from
        -- individual schedule rows), so a conference-specific running
        -- record entering each game is not derivable without new data.
        SELECT
            s.*,
            r.structure_run_id,
            COALESCE(
                SUM(CASE WHEN TRIM(SPLIT_PART(s.result, ',', 1)) = 'W' THEN 1 ELSE 0 END)
                    OVER (
                        PARTITION BY s.season, s.team_name
                        ORDER BY s.game_date, s.game_id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
            ) AS wins_entering_game,
            COALESCE(
                SUM(CASE WHEN TRIM(SPLIT_PART(s.result, ',', 1)) = 'L' THEN 1 ELSE 0 END)
                    OVER (
                        PARTITION BY s.season, s.team_name
                        ORDER BY s.game_date, s.game_id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
            ) AS losses_entering_game,
            COALESCE(
                SUM(CASE WHEN TRIM(SPLIT_PART(s.result, ',', 1)) = 'T' THEN 1 ELSE 0 END)
                    OVER (
                        PARTITION BY s.season, s.team_name
                        ORDER BY s.game_date, s.game_id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
            ) AS ties_entering_game
        FROM schedule s
        JOIN v_current_structure_runs r
          ON r.season = s.season
         AND r.structure_run_id = s.run_id
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
        CREATE OR REPLACE VIEW v_player_lineup_stats_current AS
        SELECT
            pls.*,
            r.lineup_stats_run_id
        FROM player_lineup_stats pls
        JOIN v_current_lineup_stats_runs r
          ON r.season = pls.season
         AND r.lineup_stats_run_id = pls.run_id
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
        CREATE OR REPLACE VIEW v_play_context_current AS
        SELECT
            *,
            CASE
                WHEN score_margin IS NULL THEN NULL
                WHEN score_margin >= 17 THEN 'blowout_lead'
                WHEN score_margin >= 9 THEN 'two_score_lead'
                WHEN score_margin >= 1 THEN 'one_score_lead'
                WHEN score_margin = 0 THEN 'tied'
                WHEN score_margin >= -8 THEN 'one_score_deficit'
                WHEN score_margin >= -16 THEN 'two_score_deficit'
                ELSE 'blowout_deficit'
            END AS score_margin_bucket
        FROM (
        WITH schedule_team_games AS (
            SELECT
                s.season,
                s.team_name,
                s.game_id,
                s.game_date,
                ROW_NUMBER() OVER (
                    PARTITION BY s.season, s.team_name
                    ORDER BY s.game_date, s.game_id
                ) AS week
            FROM schedule s
            JOIN v_current_structure_runs csr
              ON csr.season = s.season
             AND csr.structure_run_id = s.run_id
        ),
        scoring_points AS (
            -- Points scored on each play, attributed to home/away by
            -- schedule_home/schedule_away. Covers offensive TD/FG/PAT/two-
            -- point, safeties (2 to the defense), and defensive/return
            -- touchdowns (6 to the defense) from two sources:
            --   1. interception-return TD (pick-six): unambiguous from
            --      raw_text alone, resolved at parse time as
            --      `plays.is_defensive_td`.
            --   2. fumble-return TD: the parse-time `is_td` suppression can
            --      be wrong when the recovering team's raw abbreviation
            --      doesn't textually match the defense's canonical name
            --      (e.g. "MSJC-FB" for "Mt. San Jacinto", or when the
            --      recovering player's name gets swept into
            --      `fumble_recovered_by` by the fumble regex, e.g.
            --      "FULLERTO Ethan"). The field-position crosswalk already
            --      resolves these same raw abbreviations from human-
            --      reviewed field-position work, so prefer it here (matched
            --      as a prefix, since `fumble_recovered_by` can carry that
            --      trailing junk); fall back to the parse-time `is_td` when
            --      no crosswalk entry exists yet for this game.
            SELECT
                p.season,
                p.run_id,
                p.game_id,
                p.play_id,
                p.schedule_home,
                p.schedule_away,
                CASE
                    WHEN p.is_fumble AND p.raw_text ILIKE '%touchdown%' THEN
                        COALESCE(
                            (
                                SELECT fpc.canonical_team = p.defense
                                FROM field_position_crosswalk fpc
                                WHERE fpc.season = p.season
                                  AND fpc.game_id = p.game_id
                                  AND p.fumble_recovered_by LIKE fpc.prefix || '%'
                                ORDER BY LENGTH(fpc.prefix) DESC
                                LIMIT 1
                            ),
                            NOT COALESCE(p.is_td, FALSE)
                        )
                    ELSE FALSE
                END AS fumble_recovery_is_defensive_td,
                p.offense,
                p.defense,
                p.is_td,
                p.is_conversion,
                p.play_type,
                p.fg_result,
                COALESCE(p.is_defensive_td, FALSE) AS is_pick_six,
                COALESCE(p.is_safety, FALSE) AS is_safety
            FROM v_plays_current p
        ),
        scoring_totals AS (
            SELECT
                season,
                run_id,
                game_id,
                play_id,
                schedule_home,
                schedule_away,
                offense,
                defense,
                CASE
                    WHEN fumble_recovery_is_defensive_td THEN 0
                    WHEN is_td AND NOT COALESCE(is_conversion, FALSE) THEN 6
                    WHEN play_type = 'field_goal' AND fg_result = 'good' THEN 3
                    WHEN play_type = 'pat' AND fg_result = 'good' THEN 1
                    WHEN play_type = 'two_point' AND fg_result = 'good' THEN 2
                    ELSE 0
                END AS offense_points,
                CASE
                    WHEN fumble_recovery_is_defensive_td THEN 6
                    WHEN is_pick_six THEN 6
                    WHEN is_safety THEN 2
                    ELSE 0
                END AS defense_points
            FROM scoring_points
        ),
        game_score_state AS (
            -- Pre-play score state: the score entering each play, matching
            -- the pre-snap semantics of down/distance/quarter elsewhere in
            -- this view. The play that scores shows the score *before* its
            -- own points landed.
            SELECT
                season,
                run_id,
                game_id,
                play_id,
                offense_points,
                defense_points,
                COALESCE(
                    SUM(
                        CASE
                            WHEN offense = schedule_home THEN offense_points
                            WHEN defense = schedule_home THEN defense_points
                            ELSE 0
                        END
                    ) OVER (
                        PARTITION BY season, run_id, game_id
                        ORDER BY play_id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS home_score,
                COALESCE(
                    SUM(
                        CASE
                            WHEN offense = schedule_away THEN offense_points
                            WHEN defense = schedule_away THEN defense_points
                            ELSE 0
                        END
                    ) OVER (
                        PARTITION BY season, run_id, game_id
                        ORDER BY play_id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS away_score
            FROM scoring_totals
        )
        SELECT
            p.season,
            p.run_id,
            p.game_id,
            p.play_id,
            p.drive_id,
            p.drive_start_time,
            p.quarter,
            p.down,
            p.distance,
            CASE
                WHEN p.distance IS NULL THEN NULL
                WHEN p.distance BETWEEN 1 AND 3 THEN 'short'
                WHEN p.distance BETWEEN 4 AND 6 THEN 'medium'
                WHEN p.distance >= 7 THEN 'long'
                ELSE NULL
            END AS distance_bucket,
            CASE
                WHEN p.down IS NULL OR p.distance IS NULL THEN NULL
                WHEN p.down = 2 AND p.distance >= 8 THEN TRUE
                WHEN p.down IN (3, 4) AND p.distance >= 5 THEN TRUE
                ELSE FALSE
            END AS is_passing_down,
            CASE
                WHEN p.down IS NULL OR p.distance IS NULL THEN NULL
                WHEN p.down NOT IN (1, 2) THEN FALSE
                WHEN p.down = 2 AND p.distance >= 8 THEN FALSE
                ELSE TRUE
            END AS is_early_down,
            p.home_team,
            p.away_team,
            p.schedule_home,
            p.schedule_away,
            p.offense,
            p.defense,
            CASE
                WHEN p.offense = p.schedule_home THEN p.schedule_away
                WHEN p.offense = p.schedule_away THEN p.schedule_home
                ELSE NULL
            END AS opponent,
            CASE
                WHEN p.offense = p.schedule_home THEN 'home'
                WHEN p.offense = p.schedule_away THEN 'away'
                ELSE NULL
            END AS home_away,
            stg.week,
            p.play_type,
            p.passer,
            p.rusher,
            p.receiver,
            p.pass_result,
            p.yards_gained,
            p.is_dropback,
            p.is_attempt,
            p.is_conversion,
            p.is_pass_attempt,
            p.is_rush_attempt,
            p.completion,
            p.is_interception,
            p.is_td,
            p.is_sack,
            p.is_fumble,
            COALESCE(p.is_safety, FALSE) AS is_safety,
            (
                COALESCE(p.is_defensive_td, FALSE)
                OR (
                    p.is_fumble AND p.raw_text ILIKE '%touchdown%' AND COALESCE(
                        (
                            SELECT fpc.canonical_team = p.defense
                            FROM field_position_crosswalk fpc
                            WHERE fpc.season = p.season
                              AND fpc.game_id = p.game_id
                              AND p.fumble_recovered_by LIKE fpc.prefix || '%'
                            ORDER BY LENGTH(fpc.prefix) DESC
                            LIMIT 1
                        ),
                        NOT COALESCE(p.is_td, FALSE)
                    )
                )
            ) AS is_defensive_td,
            p.is_penalty,
            p.field_position AS raw_field_position,
            p.yardline_raw AS raw_yardline_raw,
            pfp.field_position,
            pfp.field_pos_prefix,
            pfp.prefix_owner,
            pfp.field_pos_side,
            pfp.yardline_100,
            -- yardline_100 is distance remaining to the opponent's goal
            -- line (confirmed against crosswalk.py's own formula and real
            -- plays: a 1-yard touchdown rush lands at yardline_100=1) --
            -- LOWER is closer to scoring. These labels were previously
            -- inverted (backed_up/red_zone swapped) with no downstream
            -- consumer having caught it yet; fixed here.
            CASE
                WHEN pfp.yardline_100 IS NULL THEN NULL
                WHEN pfp.yardline_100 <= 20 THEN 'red_zone'
                WHEN pfp.yardline_100 <= 49 THEN 'opponent_territory'
                WHEN pfp.yardline_100 <= 60 THEN 'midfield'
                WHEN pfp.yardline_100 <= 79 THEN 'own_territory'
                ELSE 'backed_up'
            END AS field_zone,
            pfp.resolution_status AS field_position_status,
            CASE
                WHEN (p.is_pass_attempt OR p.is_rush_attempt)
                 AND p.down IS NOT NULL
                 AND p.distance IS NOT NULL
                 AND p.distance > 0
                 AND p.yards_gained IS NOT NULL
                 AND (
                    (p.down = 1 AND p.yards_gained >= 0.5 * p.distance) OR
                    (p.down = 2 AND p.yards_gained >= 0.7 * p.distance) OR
                    (p.down IN (3, 4) AND p.yards_gained >= p.distance)
                 )
                THEN TRUE
                WHEN p.is_pass_attempt OR p.is_rush_attempt
                THEN FALSE
                ELSE NULL
            END AS is_success,
            CASE
                WHEN p.is_rush_attempt
                 AND COALESCE(p.yards_gained, 0) >= 10
                THEN TRUE
                ELSE FALSE
            END AS explosive_rush,
            CASE
                WHEN p.completion
                 AND COALESCE(p.yards_gained, 0) >= 20
                THEN TRUE
                ELSE FALSE
            END AS explosive_pass,
            CASE
                WHEN p.is_rush_attempt
                 AND COALESCE(p.yards_gained, 0) >= 10
                THEN TRUE
                WHEN p.completion
                 AND COALESCE(p.yards_gained, 0) >= 20
                THEN TRUE
                ELSE FALSE
            END AS is_explosive,
            CASE
                WHEN p.is_rush_attempt
                 AND COALESCE(p.yards_gained, 0) <= 0
                THEN TRUE
                ELSE FALSE
            END AS is_stuffed,
            gss.home_score,
            gss.away_score,
            gss.offense_points,
            gss.defense_points,
            CASE
                WHEN p.offense = p.schedule_home THEN gss.home_score - gss.away_score
                WHEN p.offense = p.schedule_away THEN gss.away_score - gss.home_score
                ELSE NULL
            END AS score_margin,
            p.raw_text
        FROM v_plays_current p
        LEFT JOIN v_play_field_positions_current pfp
          ON pfp.season = p.season
         AND pfp.source_plays_run_id = p.run_id
         AND pfp.game_id = p.game_id
         AND pfp.play_id = p.play_id
        LEFT JOIN schedule_team_games stg
          ON stg.season = p.season
         AND stg.team_name = p.offense
         AND stg.game_id = p.game_id
        LEFT JOIN game_score_state gss
          ON gss.season = p.season
         AND gss.run_id = p.run_id
         AND gss.game_id = p.game_id
         AND gss.play_id = p.play_id
        ) inner_play_context
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_game_points_current AS
        -- Points scored/allowed per team per game, from BOTH roles a team
        -- plays: its own offensive scoring (offense_points when this team
        -- is on offense) plus any defensive/special-teams scoring it puts
        -- up itself (defense_points -- safety/pick-six/defensive-fumble-TD
        -- -- when this team is on defense). Points-for and points-against
        -- both land on the same team-game row, so this is one shared view
        -- rather than a separate offense/defense split.
        SELECT
            season,
            run_id,
            game_id,
            team_name,
            SUM(points_for) AS points_scored,
            SUM(points_against) AS points_allowed
        FROM (
            SELECT
                season, run_id, game_id,
                offense AS team_name,
                offense_points AS points_for,
                defense_points AS points_against
            FROM v_play_context_current
            WHERE offense IS NOT NULL AND offense <> ''
            UNION ALL
            SELECT
                season, run_id, game_id,
                defense AS team_name,
                defense_points AS points_for,
                offense_points AS points_against
            FROM v_play_context_current
            WHERE defense IS NOT NULL AND defense <> ''
        ) per_role
        GROUP BY 1,2,3,4
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_points_current AS
        SELECT
            season,
            run_id,
            team_name,
            COUNT(DISTINCT game_id) AS games,
            SUM(points_scored) AS points_scored,
            SUM(points_allowed) AS points_allowed,
            ROUND(SUM(points_scored) / NULLIF(COUNT(DISTINCT game_id), 0), 1) AS ppg,
            ROUND(SUM(points_allowed) / NULLIF(COUNT(DISTINCT game_id), 0), 1) AS ppg_allowed
        FROM v_team_game_points_current
        GROUP BY 1,2,3
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_points_ranked_current AS
        SELECT
            *,
            RANK() OVER (PARTITION BY season ORDER BY ppg DESC) AS ppg_rank,
            RANK() OVER (PARTITION BY season ORDER BY ppg_allowed ASC) AS ppg_allowed_rank
        FROM v_team_season_points_current
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_drives_current AS
        -- One row per drive. `drive_id` is already a column on `plays`/
        -- `v_play_context_current`, but nothing aggregates by it until now.
        -- 3-and-out definition (user decision): <=3 scrimmage plays
        -- (penalties don't count) that do NOT end in a score -- covers both
        -- punts and turnovers-on-downs.
        WITH drive_base AS (
            SELECT
                season,
                run_id,
                game_id,
                drive_id,
                offense,
                defense,
                play_id,
                yardline_100,
                is_pass_attempt,
                is_rush_attempt,
                offense_points
            FROM v_play_context_current
            WHERE drive_id IS NOT NULL
        )
        SELECT
            season,
            run_id,
            game_id,
            drive_id,
            MAX(offense) AS offense,
            MAX(defense) AS defense,
            -- Starting field position: yardline_100 of the drive's first
            -- play, using play_id as the intra-game chronological key (same
            -- ordering already relied on by game_score_state's window).
            ARG_MIN(yardline_100, play_id) AS start_yardline_100,
            SUM(CASE WHEN is_pass_attempt OR is_rush_attempt THEN 1 ELSE 0 END) AS scrimmage_plays,
            SUM(offense_points) AS drive_points,
            SUM(offense_points) > 0 AS is_scoring_drive,
            (
                SUM(CASE WHEN is_pass_attempt OR is_rush_attempt THEN 1 ELSE 0 END) <= 3
                AND NOT (SUM(offense_points) > 0)
            ) AS is_three_and_out
        FROM drive_base
        GROUP BY 1,2,3,4
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_game_drives_offense_current AS
        SELECT
            season,
            run_id,
            game_id,
            offense AS team_name,
            COUNT(*) AS drives,
            SUM(scrimmage_plays) AS total_scrimmage_plays,
            SUM(start_yardline_100) AS total_start_yardline_100,
            SUM(CASE WHEN is_scoring_drive THEN 1 ELSE 0 END) AS drives_scored,
            SUM(CASE WHEN is_three_and_out THEN 1 ELSE 0 END) AS drives_three_and_out
        FROM v_drives_current
        GROUP BY 1,2,3,4
        """
    )
    conn.execute(
        """
        -- Same column names as the offense view (deliberately no `opp_`
        -- prefix): unlike other opp_* columns in this file, where higher
        -- means worse for the team being described, `drives_three_and_out`
        -- here means drives this team's DEFENSE forced into a 3-and-out --
        -- that's good, not bad, so reusing the opp_ convention would
        -- misleadingly imply the opposite (same spirit as the pass_pct/
        -- rush_pct "kept higher-better ... not a claim that facing more
        -- pass plays is actually good defense" comment on the defense-
        -- ranked view below).
        CREATE OR REPLACE VIEW v_team_game_drives_defense_current AS
        SELECT
            season,
            run_id,
            game_id,
            defense AS team_name,
            COUNT(*) AS drives,
            SUM(scrimmage_plays) AS total_scrimmage_plays,
            SUM(start_yardline_100) AS total_start_yardline_100,
            SUM(CASE WHEN is_scoring_drive THEN 1 ELSE 0 END) AS drives_scored,
            SUM(CASE WHEN is_three_and_out THEN 1 ELSE 0 END) AS drives_three_and_out
        FROM v_drives_current
        GROUP BY 1,2,3,4
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_drives_offense_current AS
        SELECT
            season,
            run_id,
            team_name,
            COUNT(DISTINCT game_id) AS games,
            SUM(drives) AS drives,
            SUM(total_scrimmage_plays) AS total_scrimmage_plays,
            SUM(total_start_yardline_100) AS total_start_yardline_100,
            SUM(drives_scored) AS drives_scored,
            SUM(drives_three_and_out) AS drives_three_and_out
        FROM v_team_game_drives_offense_current
        GROUP BY 1,2,3
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_drives_defense_current AS
        SELECT
            season,
            run_id,
            team_name,
            COUNT(DISTINCT game_id) AS games,
            SUM(drives) AS drives,
            SUM(total_scrimmage_plays) AS total_scrimmage_plays,
            SUM(total_start_yardline_100) AS total_start_yardline_100,
            SUM(drives_scored) AS drives_scored,
            SUM(drives_three_and_out) AS drives_three_and_out
        FROM v_team_game_drives_defense_current
        GROUP BY 1,2,3
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_drives_offense_ranked_current AS
        SELECT
            *,
            ROUND(total_scrimmage_plays / NULLIF(drives, 0), 2) AS avg_plays_per_drive,
            ROUND(total_start_yardline_100 / NULLIF(drives, 0), 1) AS avg_start_yardline_100,
            ROUND(100.0 * drives_scored / NULLIF(drives, 0), 1) AS pct_drives_scored,
            ROUND(100.0 * drives_three_and_out / NULLIF(drives, 0), 1) AS pct_drives_three_and_out,
            ROUND(total_scrimmage_plays / NULLIF(games, 0), 1) AS plays_per_game,
            -- yardline_100 is distance remaining to the opponent's goal
            -- line -- LOWER is a better starting position for the offense
            -- (confirmed against crosswalk.py's formula and real plays: a
            -- 1-yard TD rush lands at yardline_100=1). Previously ranked
            -- DESC on the wrong assumption that higher was better; fixed.
            RANK() OVER (PARTITION BY season ORDER BY total_start_yardline_100 / NULLIF(drives, 0) ASC) AS avg_start_yardline_100_rank,
            RANK() OVER (PARTITION BY season ORDER BY 100.0 * drives_scored / NULLIF(drives, 0) DESC) AS pct_drives_scored_rank,
            RANK() OVER (PARTITION BY season ORDER BY 100.0 * drives_three_and_out / NULLIF(drives, 0) ASC) AS pct_drives_three_and_out_rank
            -- avg_plays_per_drive/plays_per_game deliberately have no rank
            -- column -- tempo is descriptive context, not a graded metric,
            -- same treatment as avg_distance elsewhere in this file.
        FROM v_team_season_drives_offense_current
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_drives_defense_ranked_current AS
        SELECT
            *,
            ROUND(total_scrimmage_plays / NULLIF(drives, 0), 2) AS avg_plays_per_drive,
            ROUND(total_start_yardline_100 / NULLIF(drives, 0), 1) AS avg_start_yardline_100,
            ROUND(100.0 * drives_scored / NULLIF(drives, 0), 1) AS pct_drives_scored,
            ROUND(100.0 * drives_three_and_out / NULLIF(drives, 0), 1) AS pct_drives_three_and_out,
            ROUND(total_scrimmage_plays / NULLIF(games, 0), 1) AS plays_per_game,
            -- yardline_100 is distance remaining to the opponent's (here:
            -- this team's own) goal line -- pinning the opposing offense
            -- back means forcing a HIGH average starting yardline_100 for
            -- them, so that's the good outcome for this team's defense.
            -- Previously ranked ASC on the wrong assumption; fixed.
            RANK() OVER (PARTITION BY season ORDER BY total_start_yardline_100 / NULLIF(drives, 0) DESC) AS avg_start_yardline_100_rank,
            -- Allowing fewer opponent scoring drives is good.
            RANK() OVER (PARTITION BY season ORDER BY 100.0 * drives_scored / NULLIF(drives, 0) ASC) AS pct_drives_scored_rank,
            -- Forcing more opponent 3-and-outs is good.
            RANK() OVER (PARTITION BY season ORDER BY 100.0 * drives_three_and_out / NULLIF(drives, 0) DESC) AS pct_drives_three_and_out_rank
        FROM v_team_season_drives_defense_current
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
        SELECT
            *,
            -- NCAA college passer-efficiency formula (no clamps, unlike the
            -- NFL rating): (8.4*Yds + 330*TD + 100*Comp - 200*Int) / Att.
            ROUND(
                (8.4 * pass_yds + 330 * pass_td + 100 * pass_comp - 200 * pass_int)
                / NULLIF(pass_att, 0),
                1
            ) AS passer_rating
        FROM (
        SELECT
            pc.season,
            pc.run_id,
            pc.game_id,
            pc.team_name,
            MAX(pc.opponent) AS opponent,
            MAX(pc.home_away) AS home_away,
            MAX(pc.week) AS week,
            MAX(pc.schedule_home) AS schedule_home,
            MAX(pc.schedule_away) AS schedule_away,
            SUM(CASE WHEN pc.is_pass_attempt THEN 1 ELSE 0 END) AS pass_att,
            SUM(CASE WHEN pc.completion THEN 1 ELSE 0 END) AS pass_comp,
            SUM(
                CASE
                    WHEN pc.play_type = 'pass'
                     AND NOT COALESCE(pc.is_sack, FALSE)
                     AND NOT COALESCE(pc.is_interception, FALSE)
                    THEN COALESCE(pc.yards_gained, 0)
                    ELSE 0
                END
            ) AS pass_yds,
            SUM(CASE WHEN pc.is_interception THEN 1 ELSE 0 END) AS pass_int,
            -- `AND NOT COALESCE(pc.is_defensive_td, FALSE)`: a fumble
            -- recovered and returned for a score by the DEFENSE can carry a
            -- misleading raw is_td=True (see METRICS.md's is_defensive_td
            -- section) -- without this guard, that defensive touchdown gets
            -- double-miscredited as this offense's own passing/rushing TD,
            -- which then inflates passer_rating (+330 per phantom TD).
            -- Confirmed 5 real instances in the 2025-26 season data.
            SUM(
                CASE
                    WHEN pc.play_type = 'pass'
                     AND pc.is_td
                     AND NOT COALESCE(pc.is_defensive_td, FALSE)
                    THEN 1
                    ELSE 0
                END
            ) AS pass_td,
            SUM(CASE WHEN pc.is_dropback THEN 1 ELSE 0 END) AS dropbacks,
            SUM(CASE WHEN pc.is_sack THEN 1 ELSE 0 END) AS sacks,
            SUM(CASE WHEN pc.is_pass_attempt AND pc.is_success THEN 1 ELSE 0 END) AS pass_successes,
            SUM(CASE WHEN pc.completion AND COALESCE(pc.yards_gained, 0) >= 10 THEN 1 ELSE 0 END) AS pass_comp_10_plus,
            SUM(CASE WHEN pc.completion AND COALESCE(pc.yards_gained, 0) >= 20 THEN 1 ELSE 0 END) AS pass_comp_20_plus,
            SUM(CASE WHEN pc.is_rush_attempt THEN 1 ELSE 0 END) AS rush_att,
            SUM(CASE WHEN pc.is_rush_attempt THEN COALESCE(pc.yards_gained, 0) ELSE 0 END) AS rush_yds,
            SUM(
                CASE
                    WHEN pc.is_rush_attempt
                     AND pc.is_td
                     AND NOT COALESCE(pc.is_defensive_td, FALSE)
                    THEN 1
                    ELSE 0
                END
            ) AS rush_td,
            SUM(CASE WHEN pc.is_rush_attempt AND pc.is_success THEN 1 ELSE 0 END) AS rush_successes,
            SUM(CASE WHEN pc.is_rush_attempt AND COALESCE(pc.yards_gained, 0) >= 10 THEN 1 ELSE 0 END) AS rush_10_plus,
            SUM(CASE WHEN pc.is_rush_attempt AND COALESCE(pc.yards_gained, 0) >= 20 THEN 1 ELSE 0 END) AS rush_20_plus,
            SUM(CASE WHEN pc.is_stuffed THEN 1 ELSE 0 END) AS stuffed_runs,
            SUM(CASE WHEN pc.explosive_rush THEN 1 ELSE 0 END) AS rush_explosive,
            SUM(CASE WHEN pc.explosive_pass THEN 1 ELSE 0 END) AS pass_explosive,
            COUNT(*) AS play_count
        FROM (
            SELECT
                season,
                run_id,
                game_id,
                offense AS team_name,
                opponent,
                home_away,
                week,
                schedule_home,
                schedule_away,
                play_type,
                yards_gained,
                is_dropback,
                is_pass_attempt,
                is_rush_attempt,
                completion,
                is_interception,
                is_td,
                is_defensive_td,
                is_sack,
                is_success,
                is_stuffed,
                explosive_rush,
                explosive_pass
            FROM v_play_context_current
            WHERE offense IS NOT NULL
              AND offense <> ''
        ) pc
        GROUP BY 1,2,3,4
        ) base
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
            SUM(pass_successes) AS pass_successes,
            SUM(pass_comp_10_plus) AS pass_comp_10_plus,
            SUM(pass_comp_20_plus) AS pass_comp_20_plus,
            SUM(rush_att) AS rush_att,
            SUM(rush_yds) AS rush_yds,
            SUM(rush_td) AS rush_td,
            SUM(rush_successes) AS rush_successes,
            SUM(rush_10_plus) AS rush_10_plus,
            SUM(rush_20_plus) AS rush_20_plus,
            SUM(stuffed_runs) AS stuffed_runs,
            SUM(rush_explosive) AS rush_explosive,
            SUM(pass_explosive) AS pass_explosive,
            SUM(sacks) AS sacks,
            SUM(dropbacks) AS dropbacks,
            SUM(play_count) AS play_count
        FROM v_team_game_offense_current
        GROUP BY 1,2,3
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_game_defense_current AS
        SELECT
            *,
            ROUND(
                (8.4 * opp_pass_yds + 330 * opp_pass_td + 100 * opp_pass_comp - 200 * interceptions_forced)
                / NULLIF(opp_pass_att, 0),
                1
            ) AS opp_passer_rating
        FROM (
        SELECT
            pc.season,
            pc.run_id,
            pc.game_id,
            pc.defense AS team_name,
            MAX(pc.offense) AS opponent,
            MAX(
                CASE
                    WHEN pc.defense = pc.schedule_home THEN 'home'
                    WHEN pc.defense = pc.schedule_away THEN 'away'
                    ELSE NULL
                END
            ) AS home_away,
            MAX(pc.schedule_home) AS schedule_home,
            MAX(pc.schedule_away) AS schedule_away,
            SUM(CASE WHEN pc.is_pass_attempt THEN 1 ELSE 0 END) AS opp_pass_att,
            SUM(CASE WHEN pc.completion THEN 1 ELSE 0 END) AS opp_pass_comp,
            SUM(
                CASE
                    WHEN pc.play_type = 'pass'
                     AND NOT COALESCE(pc.is_sack, FALSE)
                     AND NOT COALESCE(pc.is_interception, FALSE)
                    THEN COALESCE(pc.yards_gained, 0)
                    ELSE 0
                END
            ) AS opp_pass_yds,
            SUM(CASE WHEN pc.is_interception THEN 1 ELSE 0 END) AS interceptions_forced,
            -- Same is_defensive_td guard as v_team_game_offense_current: if
            -- WE (this row's defense) recovered a fumble and returned it for
            -- a score, that's not a touchdown the opponent's offense should
            -- get credit for allowing/throwing -- it's our own defensive TD.
            SUM(
                CASE
                    WHEN pc.play_type = 'pass'
                     AND pc.is_td
                     AND NOT COALESCE(pc.is_defensive_td, FALSE)
                    THEN 1
                    ELSE 0
                END
            ) AS opp_pass_td,
            SUM(CASE WHEN pc.is_dropback THEN 1 ELSE 0 END) AS opp_dropbacks,
            SUM(CASE WHEN pc.is_sack THEN 1 ELSE 0 END) AS sacks_forced,
            SUM(CASE WHEN pc.is_pass_attempt AND pc.is_success THEN 1 ELSE 0 END) AS opp_pass_successes,
            SUM(CASE WHEN pc.completion AND COALESCE(pc.yards_gained, 0) >= 10 THEN 1 ELSE 0 END) AS opp_pass_comp_10_plus,
            SUM(CASE WHEN pc.completion AND COALESCE(pc.yards_gained, 0) >= 20 THEN 1 ELSE 0 END) AS opp_pass_comp_20_plus,
            SUM(CASE WHEN pc.is_rush_attempt THEN 1 ELSE 0 END) AS opp_rush_att,
            SUM(CASE WHEN pc.is_rush_attempt THEN COALESCE(pc.yards_gained, 0) ELSE 0 END) AS opp_rush_yds,
            SUM(
                CASE
                    WHEN pc.is_rush_attempt
                     AND pc.is_td
                     AND NOT COALESCE(pc.is_defensive_td, FALSE)
                    THEN 1
                    ELSE 0
                END
            ) AS opp_rush_td,
            SUM(CASE WHEN pc.is_rush_attempt AND pc.is_success THEN 1 ELSE 0 END) AS opp_rush_successes,
            SUM(CASE WHEN pc.is_rush_attempt AND COALESCE(pc.yards_gained, 0) >= 10 THEN 1 ELSE 0 END) AS opp_rush_10_plus,
            SUM(CASE WHEN pc.is_rush_attempt AND COALESCE(pc.yards_gained, 0) >= 20 THEN 1 ELSE 0 END) AS opp_rush_20_plus,
            SUM(CASE WHEN pc.is_stuffed THEN 1 ELSE 0 END) AS stuffed_runs_forced,
            SUM(CASE WHEN pc.explosive_rush THEN 1 ELSE 0 END) AS opp_rush_explosive,
            SUM(CASE WHEN pc.explosive_pass THEN 1 ELSE 0 END) AS opp_pass_explosive,
            COUNT(*) AS play_count
        FROM v_play_context_current pc
        WHERE pc.defense IS NOT NULL
          AND pc.defense <> ''
        GROUP BY 1,2,3,4
        ) base
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_defense_current AS
        SELECT
            season,
            run_id,
            team_name,
            COUNT(DISTINCT game_id) AS games,
            SUM(opp_pass_att) AS opp_pass_att,
            SUM(opp_pass_comp) AS opp_pass_comp,
            SUM(opp_pass_yds) AS opp_pass_yds,
            SUM(interceptions_forced) AS interceptions_forced,
            SUM(opp_pass_td) AS opp_pass_td,
            SUM(opp_dropbacks) AS opp_dropbacks,
            SUM(sacks_forced) AS sacks_forced,
            SUM(opp_pass_successes) AS opp_pass_successes,
            SUM(opp_pass_comp_10_plus) AS opp_pass_comp_10_plus,
            SUM(opp_pass_comp_20_plus) AS opp_pass_comp_20_plus,
            SUM(opp_rush_att) AS opp_rush_att,
            SUM(opp_rush_yds) AS opp_rush_yds,
            SUM(opp_rush_td) AS opp_rush_td,
            SUM(opp_rush_successes) AS opp_rush_successes,
            SUM(opp_rush_10_plus) AS opp_rush_10_plus,
            SUM(opp_rush_20_plus) AS opp_rush_20_plus,
            SUM(stuffed_runs_forced) AS stuffed_runs_forced,
            SUM(opp_rush_explosive) AS opp_rush_explosive,
            SUM(opp_pass_explosive) AS opp_pass_explosive,
            SUM(play_count) AS play_count
        FROM v_team_game_defense_current
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
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_game_situation_offense_current AS
        WITH plays_by_situation AS (
            SELECT *, 'early_down' AS situation FROM v_play_context_current WHERE is_early_down
            UNION ALL
            SELECT *, 'passing_down' AS situation FROM v_play_context_current WHERE is_passing_down
            UNION ALL
            SELECT *, 'third_down' AS situation FROM v_play_context_current WHERE down = 3
            UNION ALL
            SELECT *, 'fourth_down' AS situation FROM v_play_context_current WHERE down = 4
        )
        SELECT
            season,
            run_id,
            game_id,
            offense AS team_name,
            situation,
            MAX(opponent) AS opponent,
            MAX(home_away) AS home_away,
            MAX(week) AS week,
            SUM(CASE WHEN is_pass_attempt THEN 1 ELSE 0 END) AS pass_att,
            SUM(CASE WHEN completion THEN 1 ELSE 0 END) AS pass_comp,
            SUM(
                CASE
                    WHEN play_type = 'pass'
                     AND NOT COALESCE(is_sack, FALSE)
                     AND NOT COALESCE(is_interception, FALSE)
                    THEN COALESCE(yards_gained, 0)
                    ELSE 0
                END
            ) AS pass_yds,
            SUM(CASE WHEN play_type = 'pass' AND is_td THEN 1 ELSE 0 END) AS pass_td,
            SUM(CASE WHEN is_rush_attempt THEN 1 ELSE 0 END) AS rush_att,
            SUM(CASE WHEN is_rush_attempt THEN COALESCE(yards_gained, 0) ELSE 0 END) AS rush_yds,
            SUM(CASE WHEN is_rush_attempt AND is_td THEN 1 ELSE 0 END) AS rush_td,
            SUM(CASE WHEN (is_pass_attempt OR is_rush_attempt) AND is_success THEN 1 ELSE 0 END) AS successes,
            SUM(CASE WHEN is_explosive THEN 1 ELSE 0 END) AS explosive_plays,
            SUM(CASE WHEN is_stuffed THEN 1 ELSE 0 END) AS stuffed_runs,
            SUM(CASE WHEN is_sack THEN 1 ELSE 0 END) AS sacks,
            SUM(CASE WHEN distance IS NOT NULL THEN distance ELSE 0 END) AS distance_sum,
            SUM(CASE WHEN distance IS NOT NULL THEN 1 ELSE 0 END) AS distance_n,
            COUNT(*) AS play_count
        FROM plays_by_situation
        WHERE offense IS NOT NULL
          AND offense <> ''
        GROUP BY 1,2,3,4,5
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_game_situation_defense_current AS
        WITH plays_by_situation AS (
            SELECT *, 'early_down' AS situation FROM v_play_context_current WHERE is_early_down
            UNION ALL
            SELECT *, 'passing_down' AS situation FROM v_play_context_current WHERE is_passing_down
            UNION ALL
            SELECT *, 'third_down' AS situation FROM v_play_context_current WHERE down = 3
            UNION ALL
            SELECT *, 'fourth_down' AS situation FROM v_play_context_current WHERE down = 4
        )
        SELECT
            season,
            run_id,
            game_id,
            defense AS team_name,
            situation,
            MAX(offense) AS opponent,
            MAX(
                CASE
                    WHEN defense = schedule_home THEN 'home'
                    WHEN defense = schedule_away THEN 'away'
                    ELSE NULL
                END
            ) AS home_away,
            SUM(CASE WHEN is_pass_attempt THEN 1 ELSE 0 END) AS opp_pass_att,
            SUM(CASE WHEN completion THEN 1 ELSE 0 END) AS opp_pass_comp,
            SUM(
                CASE
                    WHEN play_type = 'pass'
                     AND NOT COALESCE(is_sack, FALSE)
                     AND NOT COALESCE(is_interception, FALSE)
                    THEN COALESCE(yards_gained, 0)
                    ELSE 0
                END
            ) AS opp_pass_yds,
            SUM(CASE WHEN play_type = 'pass' AND is_td THEN 1 ELSE 0 END) AS opp_pass_td,
            SUM(CASE WHEN is_rush_attempt THEN 1 ELSE 0 END) AS opp_rush_att,
            SUM(CASE WHEN is_rush_attempt THEN COALESCE(yards_gained, 0) ELSE 0 END) AS opp_rush_yds,
            SUM(CASE WHEN is_rush_attempt AND is_td THEN 1 ELSE 0 END) AS opp_rush_td,
            SUM(CASE WHEN (is_pass_attempt OR is_rush_attempt) AND is_success THEN 1 ELSE 0 END) AS opp_successes,
            SUM(CASE WHEN is_explosive THEN 1 ELSE 0 END) AS opp_explosive_plays,
            SUM(CASE WHEN is_stuffed THEN 1 ELSE 0 END) AS stuffed_runs_forced,
            SUM(CASE WHEN is_sack THEN 1 ELSE 0 END) AS sacks_forced,
            SUM(CASE WHEN distance IS NOT NULL THEN distance ELSE 0 END) AS distance_sum,
            SUM(CASE WHEN distance IS NOT NULL THEN 1 ELSE 0 END) AS distance_n,
            COUNT(*) AS play_count
        FROM plays_by_situation
        WHERE defense IS NOT NULL
          AND defense <> ''
        GROUP BY 1,2,3,4,5
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_situation_offense_current AS
        SELECT
            season,
            run_id,
            team_name,
            situation,
            COUNT(DISTINCT game_id) AS games,
            SUM(pass_att) AS pass_att,
            SUM(pass_comp) AS pass_comp,
            SUM(pass_yds) AS pass_yds,
            SUM(pass_td) AS pass_td,
            SUM(rush_att) AS rush_att,
            SUM(rush_yds) AS rush_yds,
            SUM(rush_td) AS rush_td,
            SUM(successes) AS successes,
            SUM(explosive_plays) AS explosive_plays,
            SUM(stuffed_runs) AS stuffed_runs,
            SUM(sacks) AS sacks,
            SUM(distance_sum) AS distance_sum,
            SUM(distance_n) AS distance_n,
            SUM(play_count) AS play_count
        FROM v_team_game_situation_offense_current
        GROUP BY 1,2,3,4
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_situation_defense_current AS
        SELECT
            season,
            run_id,
            team_name,
            situation,
            COUNT(DISTINCT game_id) AS games,
            SUM(opp_pass_att) AS opp_pass_att,
            SUM(opp_pass_comp) AS opp_pass_comp,
            SUM(opp_pass_yds) AS opp_pass_yds,
            SUM(opp_pass_td) AS opp_pass_td,
            SUM(opp_rush_att) AS opp_rush_att,
            SUM(opp_rush_yds) AS opp_rush_yds,
            SUM(opp_rush_td) AS opp_rush_td,
            SUM(opp_successes) AS opp_successes,
            SUM(opp_explosive_plays) AS opp_explosive_plays,
            SUM(stuffed_runs_forced) AS stuffed_runs_forced,
            SUM(sacks_forced) AS sacks_forced,
            SUM(distance_sum) AS distance_sum,
            SUM(distance_n) AS distance_n,
            SUM(play_count) AS play_count
        FROM v_team_game_situation_defense_current
        GROUP BY 1,2,3,4
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_offense_ranked_current AS
        SELECT
            *,
            RANK() OVER (PARTITION BY season ORDER BY pass_pct DESC) AS pass_pct_rank,
            RANK() OVER (PARTITION BY season ORDER BY pass_yds DESC) AS pass_yds_rank,
            RANK() OVER (PARTITION BY season ORDER BY pass_ypa DESC) AS pass_ypa_rank,
            RANK() OVER (PARTITION BY season ORDER BY pass_td DESC) AS pass_td_rank,
            RANK() OVER (PARTITION BY season ORDER BY comp_pct DESC) AS comp_pct_rank,
            RANK() OVER (PARTITION BY season ORDER BY pass_comp_10_plus DESC) AS pass_comp_10_plus_rank,
            RANK() OVER (PARTITION BY season ORDER BY pass_comp_20_plus DESC) AS pass_comp_20_plus_rank,
            RANK() OVER (PARTITION BY season ORDER BY pass_success_rate DESC) AS pass_success_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY rush_pct DESC) AS rush_pct_rank,
            RANK() OVER (PARTITION BY season ORDER BY rush_yds DESC) AS rush_yds_rank,
            RANK() OVER (PARTITION BY season ORDER BY rush_ypa DESC) AS rush_ypa_rank,
            RANK() OVER (PARTITION BY season ORDER BY rush_td DESC) AS rush_td_rank,
            RANK() OVER (PARTITION BY season ORDER BY rush_10_plus DESC) AS rush_10_plus_rank,
            RANK() OVER (PARTITION BY season ORDER BY rush_20_plus DESC) AS rush_20_plus_rank,
            RANK() OVER (PARTITION BY season ORDER BY rush_success_rate DESC) AS rush_success_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY passer_rating DESC) AS passer_rating_rank,
            RANK() OVER (PARTITION BY season ORDER BY success_rate DESC) AS success_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY explosive_rate DESC) AS explosive_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY rush_explosive_rate DESC) AS rush_explosive_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY pass_explosive_rate DESC) AS pass_explosive_rate_rank,
            -- Lower is better for the offense (fewer of its own rushes get stuffed).
            RANK() OVER (PARTITION BY season ORDER BY run_stuff_rate ASC) AS run_stuff_rate_rank,
            -- Lower is better for the offense (its QB gets sacked less).
            RANK() OVER (PARTITION BY season ORDER BY sack_rate ASC) AS sack_rate_rank
        FROM (
            SELECT
                season,
                run_id,
                team_name,
                games,
                pass_att,
                pass_comp,
                pass_yds,
                pass_int,
                pass_td,
                pass_successes,
                pass_comp_10_plus,
                pass_comp_20_plus,
                rush_att,
                rush_yds,
                rush_td,
                rush_successes,
                rush_10_plus,
                rush_20_plus,
                stuffed_runs,
                rush_explosive,
                pass_explosive,
                sacks,
                dropbacks,
                play_count,
                -- % pass / % rush are shares of scrimmage plays (pass_att +
                -- rush_att), not of play_count -- play_count also includes
                -- non-scrimmage rows (punts, kickoffs, PAT/two-point, drive
                -- markers) that would otherwise dilute both percentages.
                ROUND(100.0 * dropbacks / NULLIF(pass_att + rush_att, 0), 1) AS pass_pct,
                ROUND(pass_yds / NULLIF(pass_att, 0), 2) AS pass_ypa,
                ROUND(100.0 * pass_comp / NULLIF(pass_att, 0), 1) AS comp_pct,
                ROUND(100.0 * pass_successes / NULLIF(pass_att, 0), 1) AS pass_success_rate,
                ROUND(100.0 * rush_att / NULLIF(pass_att + rush_att, 0), 1) AS rush_pct,
                ROUND(rush_yds / NULLIF(rush_att, 0), 2) AS rush_ypa,
                ROUND(100.0 * rush_successes / NULLIF(rush_att, 0), 1) AS rush_success_rate,
                -- Combined (pass + rush) success/explosive rate, plus the
                -- rush-only/pass-only splits -- distinct from pass_success_rate/
                -- rush_success_rate above, which are each relative to their own
                -- attempt count rather than to all scrimmage plays.
                ROUND(100.0 * (pass_successes + rush_successes) / NULLIF(pass_att + rush_att, 0), 1) AS success_rate,
                ROUND(100.0 * (rush_explosive + pass_explosive) / NULLIF(pass_att + rush_att, 0), 1) AS explosive_rate,
                ROUND(100.0 * rush_explosive / NULLIF(rush_att, 0), 1) AS rush_explosive_rate,
                ROUND(100.0 * pass_explosive / NULLIF(pass_att, 0), 1) AS pass_explosive_rate,
                ROUND(100.0 * stuffed_runs / NULLIF(rush_att, 0), 1) AS run_stuff_rate,
                -- Sacks as a share of dropbacks (pass_att + sacks -- see the
                -- is_dropback convention documented in README.md), not of
                -- pass_att alone.
                ROUND(100.0 * sacks / NULLIF(dropbacks, 0), 1) AS sack_rate,
                -- NCAA college passer-efficiency formula (no clamps, unlike
                -- the NFL rating): (8.4*Yds + 330*TD + 100*Comp - 200*Int) / Att.
                ROUND(
                    (8.4 * pass_yds + 330 * pass_td + 100 * pass_comp - 200 * pass_int)
                    / NULLIF(pass_att, 0),
                    1
                ) AS passer_rating
            FROM v_team_season_offense_current
        ) rates
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_defense_ranked_current AS
        SELECT
            *,
            -- pass_pct/rush_pct kept higher-better for consistency with the
            -- original CSV pipeline's direction table, which treated "% of
            -- plays opponent passed/ran" as a neutral/context stat rather
            -- than grading it -- not a claim that facing more pass plays is
            -- actually good defense.
            RANK() OVER (PARTITION BY season ORDER BY opp_pass_pct DESC) AS opp_pass_pct_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_pass_yds ASC) AS opp_pass_yds_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_pass_ypa ASC) AS opp_pass_ypa_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_pass_td ASC) AS opp_pass_td_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_comp_pct ASC) AS opp_comp_pct_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_pass_comp_10_plus ASC) AS opp_pass_comp_10_plus_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_pass_comp_20_plus ASC) AS opp_pass_comp_20_plus_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_pass_success_rate ASC) AS opp_pass_success_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_rush_pct DESC) AS opp_rush_pct_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_rush_yds ASC) AS opp_rush_yds_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_rush_ypa ASC) AS opp_rush_ypa_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_rush_td ASC) AS opp_rush_td_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_rush_10_plus ASC) AS opp_rush_10_plus_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_rush_20_plus ASC) AS opp_rush_20_plus_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_rush_success_rate ASC) AS opp_rush_success_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_passer_rating ASC) AS opp_passer_rating_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_success_rate ASC) AS opp_success_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_explosive_rate ASC) AS opp_explosive_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_rush_explosive_rate ASC) AS opp_rush_explosive_rate_rank,
            RANK() OVER (PARTITION BY season ORDER BY opp_pass_explosive_rate ASC) AS opp_pass_explosive_rate_rank,
            -- Higher is better for the defense (more of the opponent's rushes get stuffed).
            RANK() OVER (PARTITION BY season ORDER BY opp_run_stuff_rate DESC) AS opp_run_stuff_rate_rank,
            -- Higher is better for the defense (sacking the opposing QB more).
            RANK() OVER (PARTITION BY season ORDER BY opp_sack_rate DESC) AS opp_sack_rate_rank
        FROM (
            SELECT
                season,
                run_id,
                team_name,
                games,
                opp_pass_att,
                opp_pass_comp,
                opp_pass_yds,
                interceptions_forced,
                opp_pass_td,
                opp_dropbacks,
                sacks_forced,
                opp_pass_successes,
                opp_pass_comp_10_plus,
                opp_pass_comp_20_plus,
                opp_rush_att,
                opp_rush_yds,
                opp_rush_td,
                opp_rush_successes,
                opp_rush_10_plus,
                opp_rush_20_plus,
                stuffed_runs_forced,
                opp_rush_explosive,
                opp_pass_explosive,
                play_count,
                ROUND(100.0 * opp_dropbacks / NULLIF(opp_pass_att + opp_rush_att, 0), 1) AS opp_pass_pct,
                ROUND(opp_pass_yds / NULLIF(opp_pass_att, 0), 2) AS opp_pass_ypa,
                ROUND(100.0 * opp_pass_comp / NULLIF(opp_pass_att, 0), 1) AS opp_comp_pct,
                ROUND(100.0 * opp_pass_successes / NULLIF(opp_pass_att, 0), 1) AS opp_pass_success_rate,
                ROUND(100.0 * opp_rush_att / NULLIF(opp_pass_att + opp_rush_att, 0), 1) AS opp_rush_pct,
                ROUND(opp_rush_yds / NULLIF(opp_rush_att, 0), 2) AS opp_rush_ypa,
                ROUND(100.0 * opp_rush_successes / NULLIF(opp_rush_att, 0), 1) AS opp_rush_success_rate,
                ROUND(100.0 * (opp_pass_successes + opp_rush_successes) / NULLIF(opp_pass_att + opp_rush_att, 0), 1) AS opp_success_rate,
                ROUND(100.0 * (opp_rush_explosive + opp_pass_explosive) / NULLIF(opp_pass_att + opp_rush_att, 0), 1) AS opp_explosive_rate,
                ROUND(100.0 * opp_rush_explosive / NULLIF(opp_rush_att, 0), 1) AS opp_rush_explosive_rate,
                ROUND(100.0 * opp_pass_explosive / NULLIF(opp_pass_att, 0), 1) AS opp_pass_explosive_rate,
                ROUND(100.0 * stuffed_runs_forced / NULLIF(opp_rush_att, 0), 1) AS opp_run_stuff_rate,
                ROUND(100.0 * sacks_forced / NULLIF(opp_dropbacks, 0), 1) AS opp_sack_rate,
                ROUND(
                    (8.4 * opp_pass_yds + 330 * opp_pass_td + 100 * opp_pass_comp - 200 * interceptions_forced)
                    / NULLIF(opp_pass_att, 0),
                    1
                ) AS opp_passer_rating
            FROM v_team_season_defense_current
        ) rates
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_situation_offense_ranked_current AS
        SELECT
            *,
            RANK() OVER (PARTITION BY season, situation ORDER BY pass_pct DESC) AS pass_pct_rank,
            RANK() OVER (PARTITION BY season, situation ORDER BY rush_pct DESC) AS rush_pct_rank,
            RANK() OVER (PARTITION BY season, situation ORDER BY yards_per_play DESC) AS yards_per_play_rank,
            RANK() OVER (PARTITION BY season, situation ORDER BY success_rate DESC) AS success_rate_rank,
            RANK() OVER (PARTITION BY season, situation ORDER BY explosive_rate DESC) AS explosive_rate_rank
        FROM (
            SELECT
                season,
                run_id,
                team_name,
                situation,
                games,
                pass_att,
                pass_comp,
                pass_yds,
                pass_td,
                rush_att,
                rush_yds,
                rush_td,
                successes,
                explosive_plays,
                stuffed_runs,
                sacks,
                play_count,
                -- avg_distance is descriptive context (yards to go), not a
                -- graded metric, so it deliberately has no _rank column.
                ROUND(distance_sum / NULLIF(distance_n, 0), 1) AS avg_distance,
                -- Rates are relative to scrimmage plays (pass_att + rush_att),
                -- not play_count, for the same reason as the non-situational
                -- ranked views: play_count also includes non-scrimmage rows.
                ROUND(100.0 * pass_att / NULLIF(pass_att + rush_att, 0), 1) AS pass_pct,
                ROUND(100.0 * rush_att / NULLIF(pass_att + rush_att, 0), 1) AS rush_pct,
                ROUND((pass_yds + rush_yds) / NULLIF(pass_att + rush_att, 0), 2) AS yards_per_play,
                ROUND(100.0 * successes / NULLIF(pass_att + rush_att, 0), 1) AS success_rate,
                ROUND(100.0 * explosive_plays / NULLIF(pass_att + rush_att, 0), 1) AS explosive_rate
            FROM v_team_season_situation_offense_current
        ) rates
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_team_season_situation_defense_ranked_current AS
        SELECT
            *,
            RANK() OVER (PARTITION BY season, situation ORDER BY opp_pass_pct DESC) AS opp_pass_pct_rank,
            RANK() OVER (PARTITION BY season, situation ORDER BY opp_rush_pct DESC) AS opp_rush_pct_rank,
            RANK() OVER (PARTITION BY season, situation ORDER BY opp_yards_per_play ASC) AS opp_yards_per_play_rank,
            RANK() OVER (PARTITION BY season, situation ORDER BY opp_success_rate ASC) AS opp_success_rate_rank,
            RANK() OVER (PARTITION BY season, situation ORDER BY opp_explosive_rate ASC) AS opp_explosive_rate_rank
        FROM (
            SELECT
                season,
                run_id,
                team_name,
                situation,
                games,
                opp_pass_att,
                opp_pass_comp,
                opp_pass_yds,
                opp_pass_td,
                opp_rush_att,
                opp_rush_yds,
                opp_rush_td,
                opp_successes,
                opp_explosive_plays,
                stuffed_runs_forced,
                sacks_forced,
                play_count,
                ROUND(distance_sum / NULLIF(distance_n, 0), 1) AS opp_avg_distance,
                ROUND(100.0 * opp_pass_att / NULLIF(opp_pass_att + opp_rush_att, 0), 1) AS opp_pass_pct,
                ROUND(100.0 * opp_rush_att / NULLIF(opp_pass_att + opp_rush_att, 0), 1) AS opp_rush_pct,
                ROUND((opp_pass_yds + opp_rush_yds) / NULLIF(opp_pass_att + opp_rush_att, 0), 2) AS opp_yards_per_play,
                ROUND(100.0 * opp_successes / NULLIF(opp_pass_att + opp_rush_att, 0), 1) AS opp_success_rate,
                ROUND(100.0 * opp_explosive_plays / NULLIF(opp_pass_att + opp_rush_att, 0), 1) AS opp_explosive_rate
            FROM v_team_season_situation_defense_current
        ) rates
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_player_game_passing_current AS
        -- Per-player, per-game passing stats keyed on the raw `passer` text
        -- field -- no player-name crosswalk join, unlike a cross-team
        -- leaderboard would need. That makes this reliable for a single
        -- team's own name-spelling consistency (typically 1-2 QBs per
        -- season), but it will NOT deduplicate genuine name variants for
        -- the same player across games. See METRICS.md.
        SELECT
            *,
            ROUND(
                (8.4 * pass_yds + 330 * pass_td + 100 * pass_comp - 200 * pass_int)
                / NULLIF(pass_att, 0),
                1
            ) AS passer_rating
        FROM (
            SELECT
                season,
                run_id,
                game_id,
                offense AS team_name,
                MAX(opponent) AS opponent,
                passer,
                SUM(CASE WHEN is_pass_attempt THEN 1 ELSE 0 END) AS pass_att,
                SUM(CASE WHEN completion THEN 1 ELSE 0 END) AS pass_comp,
                SUM(
                    CASE
                        WHEN play_type = 'pass'
                         AND NOT COALESCE(is_sack, FALSE)
                         AND NOT COALESCE(is_interception, FALSE)
                        THEN COALESCE(yards_gained, 0)
                        ELSE 0
                    END
                ) AS pass_yds,
                -- is_defensive_td guard: see v_team_game_offense_current.
                SUM(
                    CASE
                        WHEN play_type = 'pass'
                         AND is_td
                         AND NOT COALESCE(is_defensive_td, FALSE)
                        THEN 1
                        ELSE 0
                    END
                ) AS pass_td,
                SUM(CASE WHEN is_interception THEN 1 ELSE 0 END) AS pass_int
            FROM v_play_context_current
            WHERE is_pass_attempt
              AND passer IS NOT NULL
              AND passer <> ''
            GROUP BY season, run_id, game_id, offense, passer
        ) base
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_player_season_passing_current AS
        SELECT
            *,
            ROUND(
                (8.4 * pass_yds + 330 * pass_td + 100 * pass_comp - 200 * pass_int)
                / NULLIF(pass_att, 0),
                1
            ) AS passer_rating
        FROM (
            SELECT
                season,
                run_id,
                team_name,
                passer,
                COUNT(DISTINCT game_id) AS games,
                SUM(pass_att) AS pass_att,
                SUM(pass_comp) AS pass_comp,
                SUM(pass_yds) AS pass_yds,
                SUM(pass_td) AS pass_td,
                SUM(pass_int) AS pass_int
            FROM v_player_game_passing_current
            GROUP BY season, run_id, team_name, passer
        ) base
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
        -- Bronze layer for the PrestoSports official season-stats source
        -- (discovered 2026-07-05, see LOGS.md). Unlike raw_pbp_html, this is
        -- NOT per-game: a single `players_json` fetch covers every team in
        -- the conference in one file (the site's own JS filters it
        -- client-side per team), so one row per `source_kind` per run is
        -- expected, not one row per team/game.
        --   source_kind = 'players_json'          -> the shared per-player
        --                                             season-stats JSON
        --                                             (all 66 teams)
        --   source_kind = 'metadata_legend_json'   -> the abbreviated-stat-
        --                                             key legend (maps
        --                                             e.g. "ra" -> rush
        --                                             attempts) for the
        --                                             current sport code
        CREATE TABLE IF NOT EXISTS raw_lineup_json (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            fetched_at TIMESTAMP NOT NULL,
            source_url TEXT NOT NULL,
            json_text TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        -- Silver layer parsed from raw_lineup_json's 'players_json' rows
        -- (see LOGS.md, 2026-07-05/2026-07-06). One row per player per parse
        -- run, append-only and run_id-keyed like every other silver table
        -- here. All stat columns are populated for every player regardless
        -- of position_group -- e.g. a QB's rushing stats still land in
        -- rush_* -- so a leaderboard query can filter by position_group or
        -- just sort the raw column across everyone, caller's choice.
        -- Deliberately does not include kicking/punting/return categories;
        -- not needed for Team Leaders (Passing/Rushing/Receiving/Tackles/Sacks).
        CREATE TABLE IF NOT EXISTS player_lineup_stats (
            run_id TEXT NOT NULL,
            season TEXT NOT NULL,
            player_id TEXT,
            page_name TEXT,
            full_name TEXT,
            first_name TEXT,
            last_name TEXT,
            team TEXT,
            team_id TEXT,
            position TEXT,
            position_group TEXT,
            uniform TEXT,
            year TEXT,
            active BOOLEAN,
            games_played DOUBLE,
            pass_att DOUBLE,
            pass_comp DOUBLE,
            pass_pct DOUBLE,
            pass_yds DOUBLE,
            pass_ypg DOUBLE,
            pass_ypa DOUBLE,
            pass_td DOUBLE,
            pass_int DOUBLE,
            pass_lg DOUBLE,
            pass_rating DOUBLE,
            rush_att DOUBLE,
            rush_yds DOUBLE,
            rush_ypg DOUBLE,
            rush_ypc DOUBLE,
            rush_td DOUBLE,
            rush_lg DOUBLE,
            fumbles DOUBLE,
            fumbles_lost DOUBLE,
            rec DOUBLE,
            rec_ypg DOUBLE,
            rec_yds DOUBLE,
            rec_ypc DOUBLE,
            rec_td DOUBLE,
            rec_lg DOUBLE,
            tackles_solo DOUBLE,
            tackles_ast DOUBLE,
            tackles_total DOUBLE,
            tackles_pg DOUBLE,
            sacks DOUBLE,
            sack_yds DOUBLE,
            tfl DOUBLE,
            tfl_yds DOUBLE,
            forced_fumbles DOUBLE,
            fumble_rec DOUBLE,
            fumble_rec_yds DOUBLE,
            interceptions DOUBLE,
            int_yds DOUBLE,
            pass_breakups DOUBLE,
            blocked_kicks DOUBLE
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
            is_safety BOOLEAN,
            is_defensive_td BOOLEAN,
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
            stage TEXT,
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
    _ensure_column(conn, "plays", "is_safety", "BOOLEAN")
    _ensure_column(conn, "plays", "is_defensive_td", "BOOLEAN")
    _ensure_column(conn, "pipeline_runs", "stage", "TEXT")
    _backfill_pipeline_run_stages(conn)
    _backfill_plays_safety_and_defensive_td(conn)
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
