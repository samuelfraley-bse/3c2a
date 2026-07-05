"""Streamlit UI for the analyst dashboard.

See `DASHBOARD_SPEC.md` for the content spec (tabs/filters/metrics) this
implements, and `dashboard_data.py` for the underlying queries -- no SQL
lives in this module, only widgets and rendering.

Run with:
    uv run streamlit run src/duckdb_pipeline/dashboard_app.py

Opens its own **read-only** connection directly (not via `db.py`'s
`connect()`/`init_db()`, which issues schema-mutating DDL that has no place
in a dashboard, and that a read-only connection couldn't run anyway).
"""

from __future__ import annotations

import json

import duckdb
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

from duckdb_pipeline import dashboard_data as dd
from duckdb_pipeline import report_data as rd
from duckdb_pipeline.constants import DEFAULT_DB_PATH

SCORE_MARGIN_BUCKETS = [
    "blowout_lead",
    "two_score_lead",
    "one_score_lead",
    "tied",
    "one_score_deficit",
    "two_score_deficit",
    "blowout_deficit",
]
DISTANCE_BUCKETS = ["short", "medium", "long"]

# Human-readable header text per raw column name. Anything not listed here
# falls back to a humanized default in render_grid rather than silently
# showing the raw variable name.
COLUMN_LABELS: dict[str, str] = {
    "game_id": "Game",
    "opponent": "Opponent",
    "games": "Games",
    "pass_att": "Att",
    "pass_comp": "Comp",
    "comp_pct": "Comp %",
    "pass_yds": "Yards",
    "pass_ypa": "Yards/Att",
    "pass_td": "TD",
    "pass_int": "INT",
    "dropbacks": "Dropbacks",
    "sacks": "Sacks",
    "sack_rate": "Sack %",
    "pass_success_rate": "Success %",
    "pass_explosive_rate": "Explosive %",
    "pass_comp_10_plus": "10+ Yd Comp",
    "pass_comp_20_plus": "20+ Yd Comp",
    "passer_rating": "Rating",
    "rush_att": "Att",
    "rush_yds": "Yards",
    "rush_ypa": "Yards/Carry",
    "rush_td": "TD",
    "rush_success_rate": "Success %",
    "rush_explosive_rate": "Explosive %",
    "run_stuff_rate": "Stuff %",
    "rush_10_plus": "10+ Yd Runs",
    "rush_20_plus": "20+ Yd Runs",
}

# Per-column pixel widths -- short count stats can be much narrower than the
# uniform 130px that was making every column too wide. Falls back to
# _DEFAULT_COLUMN_WIDTH for anything unlisted.
COLUMN_WIDTHS: dict[str, int] = {
    "game_id": 100,
    "opponent": 140,
    "games": 80,
    "pass_att": 80,
    "pass_comp": 80,
    "comp_pct": 90,
    "pass_yds": 90,
    "pass_ypa": 100,
    "pass_td": 70,
    "pass_int": 70,
    "dropbacks": 100,
    "sacks": 80,
    "sack_rate": 90,
    "pass_success_rate": 100,
    "pass_explosive_rate": 110,
    "pass_comp_10_plus": 110,
    "pass_comp_20_plus": 110,
    "passer_rating": 80,
    "rush_att": 80,
    "rush_yds": 90,
    "rush_ypa": 105,
    "rush_td": 70,
    "rush_success_rate": 100,
    "rush_explosive_rate": 110,
    "run_stuff_rate": 95,
    "rush_10_plus": 110,
    "rush_20_plus": 110,
}
_DEFAULT_COLUMN_WIDTH = 90

# Team Leaders: player_lineup_stats has ~50 columns, but any given position
# group only fills in a handful of them (a WR's passing/tackling columns are
# all None) -- show identity columns + only the stats relevant to that
# category, not every column that happens to exist on the row.
_TEAM_LEADERS_IDENTITY_COLUMNS = ["full_name", "uniform", "position", "year"]
TEAM_LEADERS_DISPLAY_COLUMNS: dict[str, list[str]] = {
    "passing": _TEAM_LEADERS_IDENTITY_COLUMNS + [
        "pass_att", "pass_comp", "pass_pct", "pass_yds", "pass_td", "pass_int", "pass_ypa", "pass_rating",
    ],
    "rushing": _TEAM_LEADERS_IDENTITY_COLUMNS + ["rush_att", "rush_yds", "rush_ypc", "rush_td", "rush_lg"],
    "receiving": _TEAM_LEADERS_IDENTITY_COLUMNS + ["rec", "rec_yds", "rec_ypc", "rec_td", "rec_lg"],
    "tackles": _TEAM_LEADERS_IDENTITY_COLUMNS + ["tackles_total", "tackles_solo", "tackles_ast", "tfl"],
    "sacks": _TEAM_LEADERS_IDENTITY_COLUMNS + ["sacks", "sack_yds", "tfl"],
}

_ROW_STRIPE_JS = JsCode(
    """
    function(params) {
        if (params.node.rowIndex % 2 === 1) {
            return {'background-color': '#f4f4f6'};
        }
        return null;
    }
    """
)

st.set_page_config(page_title="Foothill Analyst Dashboard", layout="wide")


@st.cache_resource
def get_connection(db_path: str):
    return duckdb.connect(db_path, read_only=True)


def _none_if_all(value: str) -> str | None:
    return None if value == "All" else value


def _column_label(column: str) -> str:
    return COLUMN_LABELS.get(column, column.replace("_", " ").title())


def _rank_value_getter(side: str) -> JsCode:
    """Rank column logic: 1 = best team by whichever column is currently
    sorted, regardless of sort direction. Sorting ascending on an
    interceptions column should put the *fewest* interceptions at rank 1,
    even though that row is now at the bottom of the visible list -- rank
    means "how good is this team at this metric," not "row position."

    Requires knowing each metric's direction of "better" (higher vs. lower),
    which flips between Offense and Defense tabs for the same column name
    (see `dashboard_data.metric_direction_for_side`) -- e.g. `pass_yds` is
    higher-is-better on Offense (yards gained) but lower-is-better on
    Defense (yards allowed).
    """
    direction_json = json.dumps(dd.metric_direction_for_side(side))
    return JsCode(
        f"""
        function(params) {{
            var colState = params.api.getColumnState();
            var sortedCol = null;
            for (var i = 0; i < colState.length; i++) {{
                if (colState[i].sort) {{ sortedCol = colState[i]; break; }}
            }}
            if (!sortedCol) {{ return params.node.rowIndex + 1; }}
            var directionMap = {direction_json};
            var higherIsBetter = directionMap[sortedCol.colId];
            if (higherIsBetter === undefined || higherIsBetter === null) {{
                return params.node.rowIndex + 1;
            }}
            var total = params.api.getDisplayedRowCount();
            var idx = params.node.rowIndex;
            var sortedDesc = sortedCol.sort === 'desc';
            var bestFirst = (higherIsBetter && sortedDesc) || (!higherIsBetter && !sortedDesc);
            return bestFirst ? idx + 1 : total - idx;
        }}
        """
    )


def render_grid(rows: list[dict[str, object]], side: str) -> None:
    if not rows:
        st.info("No plays match the current filters.")
        return

    df = pd.DataFrame(rows)
    gb = GridOptionsBuilder.from_dataframe(df)
    # wrapHeaderText/autoHeaderHeight lets long headers wrap onto a second
    # line instead of truncating at the now-narrower column widths.
    gb.configure_default_column(
        sortable=True,
        resizable=True,
        filter=True,
        minWidth=_DEFAULT_COLUMN_WIDTH,
        wrapHeaderText=True,
        autoHeaderHeight=True,
    )
    for column in df.columns:
        if column == "team_name":
            continue  # handled below: pinned, its own header.
        gb.configure_column(column, headerName=_column_label(column), width=COLUMN_WIDTHS.get(column, _DEFAULT_COLUMN_WIDTH))
    # Pinned so team identity stays visible while scrolling horizontally
    # through the stat columns -- otherwise you lose track of which row is
    # which team the moment you scroll past the first couple of columns.
    gb.configure_column("team_name", headerName="Team", pinned="left")
    grid_options = gb.build()

    # GridOptionsBuilder.build() always sets autoSizeStrategy to
    # "fitGridWidth" regardless of any AgGrid()-level argument -- this is
    # what was squeezing every column to fit the visible width (truncating
    # headers) and firing the "zero width" console warning for whichever
    # tab isn't currently visible. Override it to "none" so columns keep
    # their own width and the grid scrolls horizontally instead.
    grid_options["autoSizeStrategy"] = {"type": "none"}

    # Zebra striping -- AG-Grid doesn't do this by default in the
    # "streamlit" theme.
    grid_options["getRowStyle"] = _ROW_STRIPE_JS

    # Rank reflects "best by whatever's currently sorted," not raw row
    # position -- see _rank_value_getter. Deliberately not a precomputed
    # SQL column (that would be wrong the moment you sort by a different
    # metric or flip sort direction).
    rank_col = {
        "headerName": "Rank",
        "valueGetter": _rank_value_getter(side),
        "pinned": "left",
        "width": 80,
        "sortable": False,
        "filter": False,
    }
    grid_options["columnDefs"].insert(0, rank_col)

    # AG-Grid does not automatically re-invoke a column's valueGetter for
    # already-rendered row nodes when the sort changes -- only rows newly
    # drawn into view (e.g. via virtualization as you scroll) pick up the
    # fresh computation, leaving already-rendered rows showing whatever
    # Rank was computed under the *previous* sort. Force every cell to
    # recompute on every sort/filter change so Rank never goes stale.
    grid_options["onSortChanged"] = JsCode("function(params) { params.api.refreshCells({force: true}); }")
    grid_options["onFilterChanged"] = JsCode("function(params) { params.api.refreshCells({force: true}); }")

    AgGrid(
        df,
        gridOptions=grid_options,
        allow_unsafe_jscode=True,
        # This build of streamlit-aggrid doesn't use the older
        # `update_mode`/`fit_columns_on_grid_load` API at all (those are
        # silently absorbed/ignored) -- the real control is `update_on`, a
        # list of grid JS events that trigger a Streamlit rerun. It
        # defaults to include "sortChanged", so every sort click reran the
        # whole script, rebuilt a brand-new gridOptions dict, and made the
        # grid appear to "snap back" right after the sort took visible
        # effect. Sorting/filtering/resizing are pure client-side grid
        # state that never needs to round-trip through Python, so disable
        # all of it here.
        update_on=[],
    )


def _render_labeled_rows(rows: list[dict[str, object]]) -> None:
    """Renders a list of {"label", "value", "rank"} dicts as a plain 3-column
    table -- for reading/copying a handful of numbers, not sorting across
    many teams, so no AgGrid here (see `render_grid` for that treatment).
    """
    if not rows:
        st.info("No data.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')


def _render_matchup_rows(rows: list[dict[str, object]], team_label: str, opponent_label: str) -> None:
    """Renders report_data.py's matchup-shaped rows (a mix of {"section": ...}
    divider rows and {"label","off_value","off_rank","def_value","def_rank"}
    rows) as one table -- same shape used by load_production_matchup and
    load_situation_trimmed.
    """
    if not rows:
        st.info("No data.")
        return
    table_rows = []
    for row in rows:
        if "section" in row:
            table_rows.append({"Metric": f"— {row['section']} —"})
            continue
        table_rows.append(
            {
                "Metric": row["label"],
                team_label: row.get("off_value"),
                f"{team_label} Rank": row.get("off_rank"),
                opponent_label: row.get("def_value"),
                f"{opponent_label} Rank": row.get("def_rank"),
            }
        )
    st.dataframe(pd.DataFrame(table_rows), hide_index=True, width='stretch')


def _render_report_prep(conn, season: str) -> None:
    teams = dd.list_teams(conn, season)
    if len(teams) < 2:
        st.info("Need at least two teams with data this season.")
        return
    pick_row = st.columns(2)
    team = pick_row[0].selectbox("Team", teams, key="report_prep_team")
    opponent_options = [t for t in teams if t != team]
    opponent = pick_row[1].selectbox("Opponent", opponent_options, key="report_prep_opponent")

    recap_tab, quick_hitters_tab, leaders_tab, matchup_tab, identity_tab = st.tabs(
        ["Season Recap", "Quick Hitters", "Team Leaders", "Match-Up", "Identity"]
    )

    with recap_tab:
        for label, name in [(team, team), (opponent, opponent)]:
            recap = rd.load_schedule_recap(conn, season, name)
            st.subheader(name)
            standings = recap["standings"] or {}
            st.write(
                f"Overall: {standings.get('wins', '?')}-{standings.get('losses', '?')}"
                f"-{standings.get('ties', 0)}  |  "
                f"Conference: {standings.get('conference_wins', '?')}-{standings.get('conference_losses', '?')}"
                f"-{standings.get('conference_ties', 0)}"
            )
            st.dataframe(pd.DataFrame(recap["games"]), hide_index=True, width='stretch')

    with quick_hitters_tab:
        for name in [team, opponent]:
            qh = rd.load_quick_hitters(conn, season, name)
            st.subheader(name)
            off_col, def_col = st.columns(2)
            with off_col:
                st.caption("Offense")
                _render_labeled_rows(qh["offense"])
            with def_col:
                st.caption("Defense")
                _render_labeled_rows(qh["defense"])

    with leaders_tab:
        for name in [team, opponent]:
            leaders = rd.load_team_leaders(conn, season, name)
            st.subheader(name)
            for category_label, key in [
                ("Passing", "passing"), ("Rushing", "rushing"), ("Receiving", "receiving"),
                ("Tackles", "tackles"), ("Sacks", "sacks"),
            ]:
                st.caption(category_label)
                rows = leaders[key]
                if not rows:
                    st.info("No data.")
                    continue
                df = pd.DataFrame(rows)
                columns = [c for c in TEAM_LEADERS_DISPLAY_COLUMNS[key] if c in df.columns]
                st.dataframe(df[columns], hide_index=True, width='stretch')

    with matchup_tab:
        production = rd.load_production_matchup(conn, season, team, opponent)
        situation = rd.load_situation_trimmed(conn, season, team, opponent)
        st.subheader(f"{team} Offense vs {opponent} Defense")
        _render_matchup_rows(production["team_offense_vs_opponent_defense"], team, opponent)
        st.subheader(f"{opponent} Offense vs {team} Defense")
        _render_matchup_rows(production["opponent_offense_vs_team_defense"], opponent, team)
        st.subheader(f"Early & Third Down: {team} Offense vs {opponent} Defense")
        _render_matchup_rows(situation["team_offense_vs_opponent_defense"], team, opponent)
        st.subheader(f"Early & Third Down: {opponent} Offense vs {team} Defense")
        _render_matchup_rows(situation["opponent_offense_vs_team_defense"], opponent, team)

    with identity_tab:
        for name in [team, opponent]:
            identity = rd.load_identity(conn, season, name)
            st.subheader(name)
            for side_label, side_key in [("Offense", "offense"), ("Defense", "defense")]:
                side = identity[side_key]
                st.markdown(f"**{side_label} Identity**")
                st.write(
                    f"% Run: {side['rush_pct']}  |  % Pass: {side['pass_pct']}  |  "
                    f"Yards/Carry: {side['rush_ypa']} (conf. avg {side['conference_avg_rush_ypa']})  |  "
                    f"Yards/Att: {side['pass_ypa']} (conf. avg {side['conference_avg_pass_ypa']})"
                )
                fp_col, tempo_col = st.columns(2)
                with fp_col:
                    st.caption("Field Position")
                    _render_labeled_rows(side["field_position"])
                with tempo_col:
                    st.caption("Tempo")
                    _render_labeled_rows(side["tempo"])
                rush_col, pass_col = st.columns(2)
                with rush_col:
                    st.caption("Rushing")
                    _render_labeled_rows(side["rushing"])
                with pass_col:
                    st.caption("Passing")
                    _render_labeled_rows(side["passing"])
                st.caption("Situation Run Rate")
                st.dataframe(pd.DataFrame([side["situation_run_rate"]]), hide_index=True, width='stretch')
            st.caption("Weekly Success Rate (Offense/Defense vs. conference average)")
            st.dataframe(pd.DataFrame(identity["weekly_success_rate"]), hide_index=True, width='stretch')


def main() -> None:
    st.title("Foothill Analyst Dashboard")

    db_path = st.sidebar.text_input("Database path", value=DEFAULT_DB_PATH)
    conn = get_connection(db_path)

    seasons = dd.list_seasons(conn)
    if not seasons:
        st.error("No data found in this database.")
        return

    stats_tab, report_prep_tab = st.tabs(["Team Stats", "Report Prep"])

    with report_prep_tab:
        prep_season = st.selectbox("Season", seasons, index=len(seasons) - 1, key="report_prep_season")
        _render_report_prep(conn, prep_season)

    with stats_tab:
        _render_team_stats(conn, seasons)


def _render_team_stats(conn, seasons: list[str]) -> None:
    st.subheader("Filters")
    id_row = st.columns(4)
    season = id_row[0].selectbox("Season", seasons, index=len(seasons) - 1, key="team_stats_season")

    weeks = dd.list_weeks(conn, season)
    week = _none_if_all(id_row[1].selectbox("Week", ["All"] + [str(w) for w in weeks]))
    week = int(week) if week is not None else None

    teams = dd.list_teams(conn, season)
    offense_filter = _none_if_all(id_row[2].selectbox("Offense team", ["All"] + teams))
    defense_filter = _none_if_all(id_row[3].selectbox("Defense team", ["All"] + teams))

    situation_row = st.columns(5)
    quarter_sel = situation_row[0].multiselect("Quarter", [1, 2, 3, 4]) or None
    down_sel = situation_row[1].multiselect("Down", [1, 2, 3, 4]) or None
    score_margin_bucket = _none_if_all(situation_row[2].selectbox("Score margin", ["All"] + SCORE_MARGIN_BUCKETS))
    distance_bucket = _none_if_all(situation_row[3].selectbox("Distance", ["All"] + DISTANCE_BUCKETS))
    with situation_row[4]:
        drive_filter_on = st.checkbox("Filter by drive number")
        drive_id = st.number_input("Drive number", min_value=0, step=1, value=0) if drive_filter_on else None

    st.caption(
        "Drive number is the game's shared sequential counter across both "
        "teams' possessions, not each team's own possession count."
    )

    filters = dict(
        season=season,
        week=week,
        offense=offense_filter,
        defense=defense_filter,
        quarter=quarter_sel,
        score_margin_bucket=score_margin_bucket,
        drive_id=drive_id,
        down=down_sel,
        distance_bucket=distance_bucket,
    )

    offense_tab, defense_tab = st.tabs(["Offense", "Defense"])
    for side, side_tab in [("offense", offense_tab), ("defense", defense_tab)]:
        with side_tab:
            season_tab, game_tab = st.tabs(["Season", "Game"])
            for grain, grain_tab in [("season", season_tab), ("game", game_tab)]:
                with grain_tab:
                    passing_tab, rushing_tab = st.tabs(["Passing", "Rushing"])
                    with passing_tab:
                        rows = dd.load_team_stats(conn, side=side, grain=grain, family="passing", **filters)
                        render_grid(rows, side)
                    with rushing_tab:
                        rows = dd.load_team_stats(conn, side=side, grain=grain, family="rushing", **filters)
                        render_grid(rows, side)


if __name__ == "__main__":
    main()
