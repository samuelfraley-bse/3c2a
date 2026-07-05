"""Pure query layer for the analyst dashboard.

Mirrors `report_data.py`'s separation of concerns: no Streamlit import here,
just SQL against `v_play_context_current`. See `DASHBOARD_SPEC.md` for the
content spec this implements, and `METRICS.md` for the canonical metric
formulas.

The `SUM(CASE WHEN ...)` expressions below are **re-expressions** of the
formulas already established in `db.py`'s `v_team_game_offense_current` /
`v_team_season_offense_ranked_current` (and their `_defense_` mirrors) --
not references to those views. Filters like quarter/down/distance/score
margin have to be applied at the play level, before aggregation, which a
pre-built season/game view can't do after the fact (it's already summed).
`tests/test_dashboard_data.py` guards against these two implementations
drifting apart: with no situational filters applied, this module's output
must match the existing views exactly.
"""

from __future__ import annotations

SIDES = ("offense", "defense")
GRAINS = ("season", "game")
FAMILIES = ("passing", "rushing")

# Direction of "better" for each metric column, from the OFFENSE side's
# perspective: True = higher is better, False = lower is better, None = no
# inherent direction (context/count stats like attempts, dropbacks, games).
# Same conventions already established by the RANK() columns in db.py's
# v_team_season_offense_ranked_current -- ported here, not reinvented.
# Defense inverts every non-neutral entry (see `metric_direction_for_side`)
# since the same column name means "allowed"/"forced" on Defense tabs
# instead of "gained"/"taken" on Offense tabs.
OFFENSE_METRIC_DIRECTION: dict[str, bool | None] = {
    "games": None,
    "pass_att": None,
    "pass_comp": True,
    "comp_pct": True,
    "pass_yds": True,
    "pass_ypa": True,
    "pass_td": True,
    "pass_int": False,
    "dropbacks": None,
    "sacks": False,
    "sack_rate": False,
    "pass_success_rate": True,
    "pass_explosive_rate": True,
    "pass_comp_10_plus": True,
    "pass_comp_20_plus": True,
    "passer_rating": True,
    "rush_att": None,
    "rush_yds": True,
    "rush_ypa": True,
    "rush_td": True,
    "rush_success_rate": True,
    "rush_explosive_rate": True,
    "run_stuff_rate": False,
    "rush_10_plus": True,
    "rush_20_plus": True,
}


def metric_direction_for_side(side: str) -> dict[str, bool | None]:
    """Direction map (True=higher-is-better, False=lower-is-better,
    None=neutral) for whichever side is being displayed.
    """
    if side == "offense":
        return dict(OFFENSE_METRIC_DIRECTION)
    if side == "defense":
        return {key: (None if value is None else not value) for key, value in OFFENSE_METRIC_DIRECTION.items()}
    raise ValueError(f"side must be one of {SIDES}, got {side!r}")

_PASSING_BASE_SUMS = """
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
    SUM(CASE WHEN is_interception THEN 1 ELSE 0 END) AS pass_int,
    -- is_defensive_td guard: a fumble recovered and returned for a score by
    -- the DEFENSE can carry a misleading raw is_td=True (see METRICS.md's
    -- is_defensive_td section) -- without this, that defensive touchdown
    -- gets miscredited as this offense's own passing TD. Same fix as
    -- db.py's v_team_game_offense_current/_defense_current.
    SUM(CASE WHEN play_type = 'pass' AND is_td AND NOT COALESCE(is_defensive_td, FALSE) THEN 1 ELSE 0 END) AS pass_td,
    SUM(CASE WHEN is_dropback THEN 1 ELSE 0 END) AS dropbacks,
    SUM(CASE WHEN is_sack THEN 1 ELSE 0 END) AS sacks,
    SUM(CASE WHEN is_pass_attempt AND is_success THEN 1 ELSE 0 END) AS pass_successes,
    SUM(CASE WHEN explosive_pass THEN 1 ELSE 0 END) AS pass_explosive,
    SUM(CASE WHEN completion AND COALESCE(yards_gained, 0) >= 10 THEN 1 ELSE 0 END) AS pass_comp_10_plus,
    SUM(CASE WHEN completion AND COALESCE(yards_gained, 0) >= 20 THEN 1 ELSE 0 END) AS pass_comp_20_plus
"""

_PASSING_OUTER = """
    team_name,
    {extra_cols}
    games,
    pass_att,
    pass_comp,
    ROUND(100.0 * pass_comp / NULLIF(pass_att, 0), 1) AS comp_pct,
    pass_yds,
    ROUND(pass_yds / NULLIF(pass_att, 0), 2) AS pass_ypa,
    pass_td,
    pass_int,
    dropbacks,
    sacks,
    -- Sacks as a share of dropbacks (pass_att + sacks -- is_dropback is
    -- true for both pass attempts and sacks, per this project's own
    -- convention documented in README.md), not of pass_att alone.
    ROUND(100.0 * sacks / NULLIF(dropbacks, 0), 1) AS sack_rate,
    ROUND(100.0 * pass_successes / NULLIF(pass_att, 0), 1) AS pass_success_rate,
    ROUND(100.0 * pass_explosive / NULLIF(pass_att, 0), 1) AS pass_explosive_rate,
    pass_comp_10_plus,
    pass_comp_20_plus,
    ROUND(
        (8.4 * pass_yds + 330 * pass_td + 100 * pass_comp - 200 * pass_int) / NULLIF(pass_att, 0),
        1
    ) AS passer_rating
"""

_RUSHING_BASE_SUMS = """
    SUM(CASE WHEN is_rush_attempt THEN 1 ELSE 0 END) AS rush_att,
    SUM(CASE WHEN is_rush_attempt THEN COALESCE(yards_gained, 0) ELSE 0 END) AS rush_yds,
    -- is_defensive_td guard: see pass_td above.
    SUM(CASE WHEN is_rush_attempt AND is_td AND NOT COALESCE(is_defensive_td, FALSE) THEN 1 ELSE 0 END) AS rush_td,
    SUM(CASE WHEN is_rush_attempt AND is_success THEN 1 ELSE 0 END) AS rush_successes,
    SUM(CASE WHEN explosive_rush THEN 1 ELSE 0 END) AS rush_explosive,
    SUM(CASE WHEN is_stuffed THEN 1 ELSE 0 END) AS stuffed_runs,
    SUM(CASE WHEN is_rush_attempt AND COALESCE(yards_gained, 0) >= 10 THEN 1 ELSE 0 END) AS rush_10_plus,
    SUM(CASE WHEN is_rush_attempt AND COALESCE(yards_gained, 0) >= 20 THEN 1 ELSE 0 END) AS rush_20_plus
"""

_RUSHING_OUTER = """
    team_name,
    {extra_cols}
    games,
    rush_att,
    rush_yds,
    ROUND(rush_yds / NULLIF(rush_att, 0), 2) AS rush_ypa,
    rush_td,
    ROUND(100.0 * rush_successes / NULLIF(rush_att, 0), 1) AS rush_success_rate,
    ROUND(100.0 * rush_explosive / NULLIF(rush_att, 0), 1) AS rush_explosive_rate,
    ROUND(100.0 * stuffed_runs / NULLIF(rush_att, 0), 1) AS run_stuff_rate,
    rush_10_plus,
    rush_20_plus
"""

_FAMILY_SQL = {
    "passing": (_PASSING_BASE_SUMS, _PASSING_OUTER),
    "rushing": (_RUSHING_BASE_SUMS, _RUSHING_OUTER),
}


def _side_columns(side: str) -> tuple[str, str]:
    if side == "offense":
        return "offense", "defense"
    if side == "defense":
        return "defense", "offense"
    raise ValueError(f"side must be one of {SIDES}, got {side!r}")


def _filter_clause(column: str, value: object) -> tuple[str, list[object]]:
    """Builds one bare condition (no `AND`/`WHERE` keyword) for an optional
    filter value.

    `value` may be a scalar (equality) or a list/tuple (IN (...)) to support
    multi-select filters (quarter, down). `None` means "no filter" and
    contributes nothing -- callers should skip calling this for unset filters
    rather than relying on a sentinel.
    """
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        placeholders = ", ".join(["?"] * len(values))
        return f"{column} IN ({placeholders})", values
    return f"{column} = ?", [value]


def load_team_stats(
    conn,
    *,
    side: str,
    grain: str,
    family: str,
    season: str,
    week: object = None,
    offense: str | None = None,
    defense: str | None = None,
    quarter: object = None,
    score_margin_bucket: str | None = None,
    drive_id: int | None = None,
    down: object = None,
    distance_bucket: str | None = None,
) -> list[dict[str, object]]:
    """One row per team (`grain="season"`) or per team per game
    (`grain="game"`), for whichever `side`/`family` tab is selected, with all
    of `DASHBOARD_SPEC.md`'s filters applied at the play level before
    aggregation.
    """
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, got {side!r}")
    if grain not in GRAINS:
        raise ValueError(f"grain must be one of {GRAINS}, got {grain!r}")
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {FAMILIES}, got {family!r}")

    team_col, opp_col = _side_columns(side)
    base_sums, outer_cols = _FAMILY_SQL[family]

    where_clauses = ["season = ?", f"{team_col} IS NOT NULL", f"{team_col} <> ''"]
    params: list[object] = [season]

    optional_filters = [
        ("week", week),
        ("offense", offense),
        ("defense", defense),
        ("quarter", quarter),
        ("score_margin_bucket", score_margin_bucket),
        ("drive_id", drive_id),
        ("down", down),
        ("distance_bucket", distance_bucket),
    ]
    for column, value in optional_filters:
        if value is None:
            continue
        clause, clause_params = _filter_clause(column, value)
        where_clauses.append(clause)
        params.extend(clause_params)

    where_sql = " AND ".join(where_clauses)

    group_cols = [team_col]
    inner_select_extra = ""
    extra_cols = ""
    if grain == "game":
        group_cols.append("game_id")
        # `opponent` only means one specific thing on a per-game row (the
        # other team in that game) -- on Season grain a team faces many
        # different opponents across weeks, so there's no single value to
        # show and this stays Game-grain-only.
        inner_select_extra = f"game_id,\n                MAX({opp_col}) AS opponent,\n            "
        extra_cols = "game_id,\n    opponent,\n    "

    sql = f"""
        SELECT
            {outer_cols.format(extra_cols=extra_cols)}
        FROM (
            SELECT
                {team_col} AS team_name,
                {inner_select_extra}COUNT(DISTINCT game_id) AS games,
                {base_sums}
            FROM v_play_context_current
            WHERE {where_sql}
            GROUP BY {", ".join(["team_name"] + (["game_id"] if grain == "game" else []))}
        ) base
    """
    cursor = conn.execute(sql, params)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def list_seasons(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT DISTINCT season FROM v_play_context_current ORDER BY 1").fetchall()]


def list_weeks(conn, season: str) -> list[int]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT week FROM v_play_context_current WHERE season = ? AND week IS NOT NULL ORDER BY 1",
            [season],
        ).fetchall()
    ]


def list_teams(conn, season: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT team_name FROM (
            SELECT offense AS team_name FROM v_play_context_current WHERE season = ? AND offense IS NOT NULL AND offense <> ''
            UNION
            SELECT defense AS team_name FROM v_play_context_current WHERE season = ? AND defense IS NOT NULL AND defense <> ''
        )
        ORDER BY 1
        """,
        [season, season],
    ).fetchall()
    return [row[0] for row in rows]
