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
