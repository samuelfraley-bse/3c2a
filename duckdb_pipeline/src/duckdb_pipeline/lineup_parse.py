from __future__ import annotations

import json

# Canonical position-group mapping, decoded from metaData/0.json's `positions`
# key (see LOGS.md, 2026-07-05): {"fb":"rb","hb":"rb","sb":"rb","tb":"rb",
# "te":"wr","d":"d","k":"k","kr":"kr","p":"p","qb":"qb","rb":"rb","wr":"wr", ...}.
# Hardcoded here (not read from the stored metadata_legend_json at parse time)
# since it's small and stable -- keeps this parser self-contained and simple
# to test. Raw `position` values observed on real rosters are 2-3 letter
# codes (QB, RB, WR, TE, FB, DL, LB, DB, OL, K, P); anything not recognized
# (e.g. OL, which has no individual stat category at all) maps to "other"
# rather than raising.
POSITION_GROUP_MAP: dict[str, str] = {
    "QB": "qb",
    "RB": "rb",
    "FB": "rb",
    "HB": "rb",
    "SB": "rb",
    "TB": "rb",
    "WR": "wr",
    "TE": "wr",
    "DL": "d",
    "LB": "d",
    "DB": "d",
    "D": "d",
    "K": "k",
    "P": "p",
    "KR": "kr",
}


def _position_group(position: object) -> str:
    return POSITION_GROUP_MAP.get(str(position or "").strip().upper(), "other")


def _num(stats: dict[str, object], key: str) -> float | None:
    """Best-effort numeric coercion for a raw stats value.

    Values in this source are all strings (e.g. "169", "6.4", null for
    categories a player never recorded), some with trailing "%" (e.g. "62.1%").
    Returns None for missing/unparseable values rather than raising --
    absence of a stat category for a given player is normal, not an error.
    """
    value = stats.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%")
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_players_json(json_text: str, season: str, run_id: str) -> list[dict[str, object]]:
    """Parse a `players_json` blob (the conference-wide player-season-stats
    source, see LOGS.md 2026-07-05) into rows for `player_lineup_stats`.

    One row per individual, regardless of team -- callers filter by `team`
    downstream (matches how the source itself is a single shared file).
    """
    data = json.loads(json_text)
    rows: list[dict[str, object]] = []
    for individual in data.get("individuals", []):
        stats = individual.get("stats") or {}
        rows.append(
            {
                "run_id": run_id,
                "season": season,
                "player_id": individual.get("playerId"),
                "page_name": individual.get("pageName"),
                "full_name": individual.get("fullName"),
                "first_name": individual.get("firstName"),
                "last_name": individual.get("lastName"),
                "team": individual.get("team"),
                "team_id": individual.get("teamId"),
                "position": individual.get("position"),
                "position_group": _position_group(individual.get("position")),
                "uniform": individual.get("uniform"),
                "year": individual.get("year"),
                "active": individual.get("active"),
                "games_played": _num(stats, "gp"),
                # Passing
                "pass_att": _num(stats, "pa"),
                "pass_comp": _num(stats, "pc"),
                "pass_pct": _num(stats, "ppt"),
                "pass_yds": _num(stats, "pyd"),
                "pass_ypg": _num(stats, "pyg"),
                "pass_ypa": _num(stats, "pya"),
                "pass_td": _num(stats, "ptd"),
                "pass_int": _num(stats, "pin"),
                "pass_lg": _num(stats, "plg"),
                "pass_rating": _num(stats, "peff"),
                # Rushing
                "rush_att": _num(stats, "rat"),
                "rush_yds": _num(stats, "ryd"),
                "rush_ypg": _num(stats, "ryg"),
                "rush_ypc": _num(stats, "rya"),
                "rush_td": _num(stats, "rtd"),
                "rush_lg": _num(stats, "rlg"),
                "fumbles": _num(stats, "fum"),
                "fumbles_lost": _num(stats, "fuml"),
                # Receiving
                "rec": _num(stats, "wat"),
                "rec_ypg": _num(stats, "wyg"),
                "rec_yds": _num(stats, "wyd"),
                "rec_ypc": _num(stats, "wya"),
                "rec_td": _num(stats, "wtd"),
                "rec_lg": _num(stats, "wlg"),
                # Defense
                "tackles_solo": _num(stats, "dtu"),
                "tackles_ast": _num(stats, "dta"),
                "tackles_total": _num(stats, "dtt"),
                "tackles_pg": _num(stats, "dtpg"),
                "sacks": _num(stats, "dst"),
                "sack_yds": _num(stats, "dsyd"),
                "tfl": _num(stats, "tfl"),
                "tfl_yds": _num(stats, "tfly"),
                "forced_fumbles": _num(stats, "dff"),
                "fumble_rec": _num(stats, "dfr"),
                "fumble_rec_yds": _num(stats, "dfry"),
                "interceptions": _num(stats, "di"),
                "int_yds": _num(stats, "diyd"),
                "pass_breakups": _num(stats, "dbru"),
                "blocked_kicks": _num(stats, "dblk"),
            }
        )
    return rows
