"""Query/shaping layer for the weekly coach report.

Deliberately has no docx/matplotlib imports -- keeps this module lightweight
and unit-testable with the same fixture pattern as the rest of
`duckdb_pipeline`. Presentation (rank formatting, chart rendering, docx
assembly) lives in `report_build.py`.
"""

from __future__ import annotations


def _rows_as_dicts(cursor) -> list[dict[str, object]]:
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _fetchone_dict(conn, sql: str, params: list[object]) -> dict[str, object] | None:
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [c[0] for c in cursor.description]
    return dict(zip(columns, row))


def _pct(numerator: object, denominator: object) -> float | None:
    if not denominator:
        return None
    return round(100.0 * float(numerator) / float(denominator), 1)


def load_schedule_recap(conn, season: str, team: str) -> dict[str, object]:
    """Season standings + full schedule (with results) for one team."""
    standings = _fetchone_dict(
        conn,
        """
        SELECT team_name, wins, losses, ties, conference_wins, conference_losses, conference_ties
        FROM v_standings_current
        WHERE season = ? AND team_name = ?
        """,
        [season, team],
    )
    games = _rows_as_dicts(
        conn.execute(
            """
            SELECT game_date, opponent, home_away, result
            FROM v_schedule_current
            WHERE season = ? AND team_name = ?
            ORDER BY game_date
            """,
            [season, team],
        )
    )
    return {"team": team, "standings": standings, "games": games}


# (offense_column, defense_column, label, kind)
# kind is a display hint for report_build.py: "pct" / "int" / "f1" / "f2"
# (matches the format-spec vocabulary already used by analysis/build_preview_docx.py::fmt())
PRODUCTION_METRIC_PAIRS: list[tuple[str, str, str, str] | tuple[None, str]] = [
    (None, "Passing"),
    ("pass_pct", "opp_pass_pct", "% Plays Pass", "pct"),
    ("pass_yds", "opp_pass_yds", "Total Yards", "int"),
    ("pass_ypa", "opp_pass_ypa", "Yards per Attempt", "f2"),
    ("pass_td", "opp_pass_td", "TD", "int"),
    ("comp_pct", "opp_comp_pct", "Comp Pct", "pct"),
    ("pass_comp_10_plus", "opp_pass_comp_10_plus", "10+ Yd Completions", "int"),
    ("pass_comp_20_plus", "opp_pass_comp_20_plus", "20+ Yd Completions", "int"),
    ("pass_success_rate", "opp_pass_success_rate", "Success Rate", "pct"),
    (None, "Rushing"),
    ("rush_pct", "opp_rush_pct", "% Plays Run", "pct"),
    ("rush_yds", "opp_rush_yds", "Total Yards", "int"),
    ("rush_ypa", "opp_rush_ypa", "Yards Per Attempt", "f2"),
    ("rush_td", "opp_rush_td", "TD", "int"),
    ("rush_10_plus", "opp_rush_10_plus", "10+ Yard Rushes", "int"),
    ("rush_20_plus", "opp_rush_20_plus", "20+ Yard Rushes", "int"),
    ("rush_success_rate", "opp_rush_success_rate", "Success Rate", "pct"),
]


def _build_matchup_rows(
    off_row: dict[str, object] | None,
    def_row: dict[str, object] | None,
    metric_pairs,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for entry in metric_pairs:
        if entry[0] is None:
            rows.append({"section": entry[1]})
            continue
        off_key, def_key, label, kind = entry
        rows.append(
            {
                "label": label,
                "kind": kind,
                "off_value": off_row.get(off_key) if off_row else None,
                "off_rank": off_row.get(f"{off_key}_rank") if off_row else None,
                "def_value": def_row.get(def_key) if def_row else None,
                "def_rank": def_row.get(f"{def_key}_rank") if def_row else None,
            }
        )
    return rows


def load_production_matchup(conn, season: str, team: str, opponent: str) -> dict[str, object]:
    """Season-aggregate O-vs-D matchup, both directions."""
    team_off = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_offense_ranked_current WHERE season = ? AND team_name = ?",
        [season, team],
    )
    opp_def = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_defense_ranked_current WHERE season = ? AND team_name = ?",
        [season, opponent],
    )
    opp_off = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_offense_ranked_current WHERE season = ? AND team_name = ?",
        [season, opponent],
    )
    team_def = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_defense_ranked_current WHERE season = ? AND team_name = ?",
        [season, team],
    )
    return {
        "team_offense_vs_opponent_defense": _build_matchup_rows(team_off, opp_def, PRODUCTION_METRIC_PAIRS),
        "opponent_offense_vs_team_defense": _build_matchup_rows(opp_off, team_def, PRODUCTION_METRIC_PAIRS),
    }


SITUATION_METRIC_PAIRS = [
    ("early_down", "success_rate", "opp_success_rate", "Early-Down Success Rate %", "pct"),
    ("early_down", "rush_pct", "opp_rush_pct", "Early-Down Rush %", "pct"),
    ("early_down", "explosive_rate", "opp_explosive_rate", "Early-Down Explosive %", "pct"),
    ("third_down", "success_rate", "opp_success_rate", "Third-Down Conversion %", "pct"),
    ("third_down", "avg_distance", "opp_avg_distance", "Third-Down Avg Distance to Go", "f1"),
    ("third_down", "explosive_rate", "opp_explosive_rate", "Third-Down Explosive %", "pct"),
]


def load_situation_trimmed(conn, season: str, team: str, opponent: str) -> dict[str, object]:
    """Trimmed early-down/third-down matchup table (both directions) plus
    success-rate-by-down chart data.
    """
    cache: dict[tuple[str, str, str], dict[str, object] | None] = {}

    def get(team_name: str, situation: str, view: str) -> dict[str, object] | None:
        key = (team_name, situation, view)
        if key not in cache:
            cache[key] = _fetchone_dict(
                conn,
                f"SELECT * FROM {view} WHERE season = ? AND team_name = ? AND situation = ?",
                [season, team_name, situation],
            )
        return cache[key]

    def build_direction(off_team: str, def_team: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for situation, off_key, def_key, label, kind in SITUATION_METRIC_PAIRS:
            off_row = get(off_team, situation, "v_team_season_situation_offense_ranked_current")
            def_row = get(def_team, situation, "v_team_season_situation_defense_ranked_current")
            rows.append(
                {
                    "label": label,
                    "kind": kind,
                    "off_value": off_row.get(off_key) if off_row else None,
                    "off_rank": off_row.get(f"{off_key}_rank") if off_row else None,
                    "def_value": def_row.get(def_key) if def_row else None,
                    "def_rank": def_row.get(f"{def_key}_rank") if def_row else None,
                }
            )
        return rows

    down_rows = _rows_as_dicts(
        conn.execute(
            """
            SELECT
                down,
                SUM(CASE WHEN offense = ? AND (is_pass_attempt OR is_rush_attempt) THEN 1 ELSE 0 END) AS team_off_att,
                SUM(CASE WHEN offense = ? AND is_success THEN 1 ELSE 0 END) AS team_off_success,
                SUM(CASE WHEN defense = ? AND (is_pass_attempt OR is_rush_attempt) THEN 1 ELSE 0 END) AS opp_def_att,
                SUM(CASE WHEN defense = ? AND is_success THEN 1 ELSE 0 END) AS opp_def_success
            FROM v_play_context_current
            WHERE season = ?
              AND down BETWEEN 1 AND 4
              AND (offense = ? OR defense = ?)
            GROUP BY down
            ORDER BY down
            """,
            [team, team, opponent, opponent, season, team, opponent],
        )
    )
    for row in down_rows:
        row["team_off_success_rate"] = _pct(row["team_off_success"], row["team_off_att"])
        row["opp_def_success_rate"] = _pct(row["opp_def_success"], row["opp_def_att"])

    return {
        "team_offense_vs_opponent_defense": build_direction(team, opponent),
        "opponent_offense_vs_team_defense": build_direction(opponent, team),
        "success_rate_by_down": down_rows,
    }


# (kind of stat -> (offense_view_col, offense_rank_col, defense_view_col, defense_rank_col, label))
# Offense pulls from v_team_season_offense_ranked_current / v_team_season_points_ranked_current;
# defense mirrors from v_team_season_defense_ranked_current / the same points view
# (points_allowed lives on the same row as points_scored).
QUICK_HITTERS_METRICS = [
    ("ppg", "ppg_rank", "ppg_allowed", "ppg_allowed_rank", "PPG"),
    ("success_rate", "success_rate_rank", "opp_success_rate", "opp_success_rate_rank", "Success Rate"),
    ("explosive_rate", "explosive_rate_rank", "opp_explosive_rate", "opp_explosive_rate_rank", "Explosive Play Rate"),
    ("rush_ypa", "rush_ypa_rank", "opp_rush_ypa", "opp_rush_ypa_rank", "Yards per Carry"),
    ("pass_ypa", "pass_ypa_rank", "opp_pass_ypa", "opp_pass_ypa_rank", "Yards per Pass"),
]


def load_quick_hitters(conn, season: str, team: str) -> dict[str, object]:
    """Team-season summary stats with conference rank, split Offense/Defense
    -- the template's "Quick Hitters" box. PPG comes from
    `v_team_season_points_ranked_current` (this session's new points view);
    everything else already lives on the offense/defense ranked views.
    """
    offense = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_offense_ranked_current WHERE season = ? AND team_name = ?",
        [season, team],
    )
    defense = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_defense_ranked_current WHERE season = ? AND team_name = ?",
        [season, team],
    )
    points = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_points_ranked_current WHERE season = ? AND team_name = ?",
        [season, team],
    )
    third_down_offense = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_situation_offense_ranked_current WHERE season = ? AND team_name = ? AND situation = 'third_down'",
        [season, team],
    )
    third_down_defense = _fetchone_dict(
        conn,
        "SELECT * FROM v_team_season_situation_defense_ranked_current WHERE season = ? AND team_name = ? AND situation = 'third_down'",
        [season, team],
    )
    merged_offense = {**(offense or {}), **(points or {})}
    merged_defense = {**(defense or {}), **(points or {})}

    def build_side(source: dict[str, object], is_offense: bool) -> list[dict[str, object]]:
        rows = []
        for off_key, off_rank_key, def_key, def_rank_key, label in QUICK_HITTERS_METRICS:
            key = off_key if is_offense else def_key
            rank_key = off_rank_key if is_offense else def_rank_key
            rows.append({"label": label, "value": source.get(key), "rank": source.get(rank_key)})
        third_down = third_down_offense if is_offense else third_down_defense
        third_down_key = "success_rate" if is_offense else "opp_success_rate"
        rows.append(
            {
                "label": "3rd Down Conversion",
                "value": (third_down or {}).get(third_down_key),
                "rank": (third_down or {}).get(f"{third_down_key}_rank"),
            }
        )
        return rows

    return {
        "team": team,
        "offense": build_side(merged_offense, is_offense=True),
        "defense": build_side(merged_defense, is_offense=False),
    }


def load_weekly_trends(conn, season: str, team: str) -> list[dict[str, object]]:
    """Per-game trend rows for one team, ordered by week.

    Returns a superset of candidate trend metrics (success rate, explosive
    rate, 3rd-down conversion, offense and defense-faced); the report layer
    picks which 2-3 to actually plot via its own config list.
    """
    rows = _rows_as_dicts(
        conn.execute(
            """
            SELECT
                week,
                game_id,
                -- Derived directly from schedule_home/schedule_away relative
                -- to `team`, not from pc.opponent -- that column is always
                -- relative to *that row's own offense*, so reusing it here
                -- would return `team` itself on the rows where `team` is on
                -- defense instead of the actual opponent.
                MAX(CASE WHEN schedule_home = ? THEN schedule_away WHEN schedule_away = ? THEN schedule_home ELSE NULL END) AS opponent,
                SUM(CASE WHEN offense = ? AND (is_pass_attempt OR is_rush_attempt) THEN 1 ELSE 0 END) AS off_att,
                SUM(CASE WHEN offense = ? AND is_success THEN 1 ELSE 0 END) AS off_success,
                SUM(CASE WHEN offense = ? AND is_explosive THEN 1 ELSE 0 END) AS off_explosive,
                SUM(CASE WHEN defense = ? AND (is_pass_attempt OR is_rush_attempt) THEN 1 ELSE 0 END) AS def_att,
                SUM(CASE WHEN defense = ? AND is_success THEN 1 ELSE 0 END) AS def_success,
                SUM(CASE WHEN defense = ? AND is_explosive THEN 1 ELSE 0 END) AS def_explosive,
                SUM(CASE WHEN offense = ? AND down = 3 THEN 1 ELSE 0 END) AS off_third_att,
                SUM(CASE WHEN offense = ? AND down = 3 AND is_success THEN 1 ELSE 0 END) AS off_third_conv,
                SUM(CASE WHEN defense = ? AND down = 3 THEN 1 ELSE 0 END) AS def_third_att,
                SUM(CASE WHEN defense = ? AND down = 3 AND is_success THEN 1 ELSE 0 END) AS def_third_conv
            FROM v_play_context_current
            WHERE season = ?
              AND week IS NOT NULL
              AND (offense = ? OR defense = ?)
            GROUP BY week, game_id
            ORDER BY week
            """,
            [team] * 12 + [season, team, team],
        )
    )
    for row in rows:
        row["success_rate_off"] = _pct(row["off_success"], row["off_att"])
        row["success_rate_def"] = _pct(row["def_success"], row["def_att"])
        row["explosive_rate_off"] = _pct(row["off_explosive"], row["off_att"])
        row["explosive_rate_def"] = _pct(row["def_explosive"], row["def_att"])
        row["third_down_conv_off"] = _pct(row["off_third_conv"], row["off_third_att"])
        row["third_down_conv_def"] = _pct(row["def_third_conv"], row["def_third_att"])
    return rows


# (position_group, order_by_column, limit, output key) -- counts match the
# template's Team Leaders box (2 QB / 2 RB / 3 WR / 2 tacklers / 2 sackers).
TEAM_LEADERS_CATEGORIES = [
    ("qb", "pass_yds", 2, "passing"),
    ("rb", "rush_yds", 2, "rushing"),
    ("wr", "rec_yds", 3, "receiving"),
    ("d", "tackles_total", 2, "tackles"),
    ("d", "sacks", 2, "sacks"),
]


def load_team_leaders(conn, season: str, team: str) -> dict[str, list[dict[str, object]]]:
    """Team Leaders box: top players per category from `player_lineup_stats`
    (official, conference-wide source -- see `METRICS.md`), not derived from
    `plays` (no player-name crosswalk needed).
    """
    result: dict[str, list[dict[str, object]]] = {}
    for position_group, order_col, limit, key in TEAM_LEADERS_CATEGORIES:
        rows = _rows_as_dicts(
            conn.execute(
                f"""
                SELECT *
                FROM v_player_lineup_stats_current
                WHERE season = ? AND team = ? AND position_group = ? AND {order_col} IS NOT NULL
                ORDER BY {order_col} DESC
                LIMIT {limit}
                """,
                [season, team, position_group],
            )
        )
        result[key] = rows
    return result


def _conference_weekly_success_rate(conn, season: str) -> list[dict[str, object]]:
    """Pooled offensive success rate per week across every team tracked this
    season (not filtered to one team) -- the "Avg (CA)" comparison line for
    the Identity page's success-rate-by-game chart. Confirmed with the user:
    "state average" means every team in this database for the season, not a
    narrower subset.
    """
    rows = _rows_as_dicts(
        conn.execute(
            """
            SELECT
                week,
                SUM(CASE WHEN is_pass_attempt OR is_rush_attempt THEN 1 ELSE 0 END) AS att,
                SUM(CASE WHEN is_success THEN 1 ELSE 0 END) AS successes
            FROM v_play_context_current
            WHERE season = ?
              AND week IS NOT NULL
            GROUP BY week
            ORDER BY week
            """,
            [season],
        )
    )
    for row in rows:
        row["success_rate"] = _pct(row["successes"], row["att"])
    return rows


# (offense_col, defense_col, rank_off, rank_def, label) for the rushing/passing
# identity bullets -- reuses columns already on the ranked views from this
# session's gold-view work, nothing new to compute.
IDENTITY_RUSHING_METRICS = [
    ("rush_yds", "opp_rush_yds", "rush_yds_rank", "opp_rush_yds_rank", "Yards"),
    ("rush_ypa", "opp_rush_ypa", "rush_ypa_rank", "opp_rush_ypa_rank", "Yards per Carry"),
    ("rush_success_rate", "opp_rush_success_rate", "rush_success_rate_rank", "opp_rush_success_rate_rank", "Success Rate"),
    ("rush_explosive_rate", "opp_rush_explosive_rate", "rush_explosive_rate_rank", "opp_rush_explosive_rate_rank", "Explosive Rate"),
    ("run_stuff_rate", "opp_run_stuff_rate", "run_stuff_rate_rank", "opp_run_stuff_rate_rank", "Run Stuff Rate"),
]
IDENTITY_PASSING_METRICS = [
    ("pass_yds", "opp_pass_yds", "pass_yds_rank", "opp_pass_yds_rank", "Yards"),
    ("comp_pct", "opp_comp_pct", "comp_pct_rank", "opp_comp_pct_rank", "Comp Pct"),
    ("pass_success_rate", "opp_pass_success_rate", "pass_success_rate_rank", "opp_pass_success_rate_rank", "Success Rate"),
    ("pass_explosive_rate", "opp_pass_explosive_rate", "pass_explosive_rate_rank", "opp_pass_explosive_rate_rank", "Explosive Rate"),
    ("sack_rate", "opp_sack_rate", "sack_rate_rank", "opp_sack_rate_rank", "Sack Rate"),
]
IDENTITY_FIELD_POSITION_METRICS = [
    ("avg_start_yardline_100", "avg_start_yardline_100_rank", "Avg Starting Field Position"),
    ("pct_drives_scored", "pct_drives_scored_rank", "% Drives Score"),
    ("pct_drives_three_and_out", "pct_drives_three_and_out_rank", "% Drives 3-and-Out"),
]
IDENTITY_TEMPO_METRICS = [
    ("plays_per_game", "Plays per Game"),
    ("avg_plays_per_drive", "Plays per Drive"),
]


def _identity_side(
    conn,
    season: str,
    team: str,
    *,
    is_offense: bool,
    stats_view: str,
    drives_view: str,
    situation_view: str,
    rush_pct_col: str,
    pass_pct_col: str,
    rush_ypa_col: str,
    pass_ypa_col: str,
    success_rate_col: str,
    rush_pct_situation_col: str,
) -> dict[str, object]:
    stats = _fetchone_dict(conn, f"SELECT * FROM {stats_view} WHERE season = ? AND team_name = ?", [season, team])
    drives = _fetchone_dict(conn, f"SELECT * FROM {drives_view} WHERE season = ? AND team_name = ?", [season, team])
    early_down = _fetchone_dict(
        conn, f"SELECT * FROM {situation_view} WHERE season = ? AND team_name = ? AND situation = 'early_down'", [season, team],
    )
    third_down = _fetchone_dict(
        conn, f"SELECT * FROM {situation_view} WHERE season = ? AND team_name = ? AND situation = 'third_down'", [season, team],
    )
    conference_avg = _fetchone_dict(
        conn,
        f"SELECT AVG({rush_ypa_col}) AS avg_rush_ypa, AVG({pass_ypa_col}) AS avg_pass_ypa FROM {stats_view} WHERE season = ?",
        [season],
    )
    stats = stats or {}
    drives = drives or {}
    conference_avg = conference_avg or {}

    def metric_rows(metrics):
        rows = []
        for off_col, def_col, off_rank, def_rank, label in metrics:
            col, rank_col = (off_col, off_rank) if is_offense else (def_col, def_rank)
            rows.append({"label": label, "value": stats.get(col), "rank": stats.get(rank_col)})
        return rows

    return {
        "team": team,
        "rush_pct": stats.get(rush_pct_col),
        "pass_pct": stats.get(pass_pct_col),
        "rush_ypa": stats.get(rush_ypa_col),
        "pass_ypa": stats.get(pass_ypa_col),
        "conference_avg_rush_ypa": round(conference_avg["avg_rush_ypa"], 2) if conference_avg.get("avg_rush_ypa") is not None else None,
        "conference_avg_pass_ypa": round(conference_avg["avg_pass_ypa"], 2) if conference_avg.get("avg_pass_ypa") is not None else None,
        "field_position": [
            {"label": label, "value": drives.get(col), "rank": drives.get(rank_col)}
            for col, rank_col, label in IDENTITY_FIELD_POSITION_METRICS
        ],
        "tempo": [{"label": label, "value": drives.get(col)} for col, label in IDENTITY_TEMPO_METRICS],
        "rushing": metric_rows(IDENTITY_RUSHING_METRICS),
        "passing": metric_rows(IDENTITY_PASSING_METRICS),
        "situation_run_rate": {
            "early_down_rush_pct": (early_down or {}).get(rush_pct_situation_col),
            "early_down_success_rate": (early_down or {}).get(success_rate_col),
            "third_down_rush_pct": (third_down or {}).get(rush_pct_situation_col),
            "third_down_success_rate": (third_down or {}).get(success_rate_col),
        },
    }


def load_identity(conn, season: str, team: str) -> dict[str, object]:
    """Offense + Defense Identity page raw data: rush/pass split, yards per
    play (with conference average), field position/tempo (from this
    session's drive-rollup views), rushing/passing bullets, situation run
    rate, and the weekly success-rate trend (with conference average).
    """
    offense = _identity_side(
        conn, season, team,
        is_offense=True,
        stats_view="v_team_season_offense_ranked_current",
        drives_view="v_team_season_drives_offense_ranked_current",
        situation_view="v_team_season_situation_offense_ranked_current",
        rush_pct_col="rush_pct", pass_pct_col="pass_pct",
        rush_ypa_col="rush_ypa", pass_ypa_col="pass_ypa",
        success_rate_col="success_rate", rush_pct_situation_col="rush_pct",
    )
    defense = _identity_side(
        conn, season, team,
        is_offense=False,
        stats_view="v_team_season_defense_ranked_current",
        drives_view="v_team_season_drives_defense_ranked_current",
        situation_view="v_team_season_situation_defense_ranked_current",
        rush_pct_col="opp_rush_pct", pass_pct_col="opp_pass_pct",
        rush_ypa_col="opp_rush_ypa", pass_ypa_col="opp_pass_ypa",
        success_rate_col="opp_success_rate", rush_pct_situation_col="opp_rush_pct",
    )

    team_weekly = load_weekly_trends(conn, season, team)
    conference_weekly = _conference_weekly_success_rate(conn, season)
    conference_by_week = {row["week"]: row["success_rate"] for row in conference_weekly}
    weekly_success_rate = [
        {
            "week": row["week"],
            "opponent": row["opponent"],
            "team_success_rate_off": row["success_rate_off"],
            "team_success_rate_def": row["success_rate_def"],
            "conference_avg_success_rate": conference_by_week.get(row["week"]),
        }
        for row in team_weekly
    ]

    return {"team": team, "offense": offense, "defense": defense, "weekly_success_rate": weekly_success_rate}
