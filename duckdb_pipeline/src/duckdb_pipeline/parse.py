from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .constants import BASE_URL

RE_DOWN_DIST = re.compile(
    r"(\d+)(?:st|nd|rd|th)\s+and\s+(\d+|goal)\s+at\s+([A-Z][A-Z0-9\s\.\-_~]*?\d+)",
    re.IGNORECASE,
)
RE_DRIVE_HEADER = re.compile(r"^(.+?)\s+at\s+(\d+:\d+)$")
RE_QUARTER_START = re.compile(r"Start of (\d+)(?:st|nd|rd|th) quarter", re.IGNORECASE)
RE_DRIVE_START = re.compile(r"drive start at (\d+:\d+)", re.IGNORECASE)
RE_RUSH = re.compile(r"(\w[\w\s\-'\.]+?)\s+rush for", re.IGNORECASE)
RE_PASS_COMPLETE_A = re.compile(
    r"(\w[\w\s\-'\.]+?)\s+pass complete to\s+(\w[\w\s\-'\.]+?)\s+for",
    re.IGNORECASE,
)
RE_PASS_COMPLETE_B = re.compile(
    r"(\w[\w\s\-'\.]+?)\s+pass complete(?:\s+for|\s+to)",
    re.IGNORECASE,
)
RE_PASS_INCOMPLETE = re.compile(
    r"(\w[\w\s\-'\.]+?)\s+pass incomplete(?:\s+to\s+(\w[\w\s\-'\.]+?))?"
    r"(?:\s*[,(]|,\s*PENALTY|\.|$)",
    re.IGNORECASE,
)
RE_PASS_INT = re.compile(r"(\w[\w\s\-'\.]+?)\s+pass intercept", re.IGNORECASE)
RE_SACK = re.compile(r"(\w[\w\s\-'\.]+?)\s+sacked for", re.IGNORECASE)
RE_SACK_ALT = re.compile(
    r"(\w[\w\s\-'\.]+?)\s+sacked to\s+\w[\w\s\-'\.]+?\s+for loss of",
    re.IGNORECASE,
)
RE_FG_BLOCKED = re.compile(
    r"(\w[\w\s\-'\.]+?)\s+field goal attempt from \d+\s+BLOCKED",
    re.IGNORECASE,
)
RE_PASS_ATTEMPT = re.compile(
    r"(\w[\w\s\-'\.]+?)\s+pass attempt to\s+(\w[\w\s\-'\.]+?)\s+(good|failed)",
    re.IGNORECASE,
)
RE_PUNT = re.compile(r"(\w[\w\s\-'\.]+?)\s+punt(?:\s+(\d+)\s+yards)?", re.IGNORECASE)
RE_KICKOFF = re.compile(r"(\w[\w\s\-'\.]+?)\s+kickoff\s+(\d+)\s+yards", re.IGNORECASE)
RE_FG = re.compile(
    r"(\w[\w\s\-'\.]+?)\s+field goal attempt from\s+(\d+)\s+(GOOD|MISSED)",
    re.IGNORECASE,
)
RE_PAT = re.compile(r"(\w[\w\s\-'\.]+?)\s+kick attempt\s+(GOOD|FAILED)", re.IGNORECASE)
RE_TWO_PT = re.compile(r"(\w[\w\s\-'\.]+?)\s+(?:rush|pass)\s+attempt\s+(good|failed)", re.IGNORECASE)
_TEAM_TOK = r"((?:[A-Z]+\s+)*[A-Z]+)"
RE_PENALTY_NAMED = re.compile(
    r"PENALTY\s+" + _TEAM_TOK + r"\s+([a-z][\w\s]*?)\s*\(([^)]+)\)\s+(\d+)\s+yards"
)
RE_PENALTY_ANON = re.compile(
    r"PENALTY\s+" + _TEAM_TOK + r"\s+([a-z][\w\s]+?)\s+(\d+)\s+yards"
)
RE_YARDS = re.compile(r"for\s+(loss of\s+)?(\d+)\s+yards?", re.IGNORECASE)
RE_NO_GAIN = re.compile(r"for no gain", re.IGNORECASE)
RE_TD = re.compile(r"touchdown", re.IGNORECASE)
RE_INT = re.compile(r"intercept", re.IGNORECASE)
RE_TIMEOUT = re.compile(r"^Timeout\s", re.IGNORECASE)
RE_CLOCK_ONLY = re.compile(r"^clock\s+\d+:\d+\.$", re.IGNORECASE)
RE_FUMBLE = re.compile(
    r"fumble by\s+(\w[\w\s\-'\.]+?)\s+recovered by\s+(\w+)\s+(\w[\w\s\-'\.]+?)\s+at\s+([A-Z][A-Z0-9\s\.\-_]*?\d+)",
    re.IGNORECASE,
)
RE_FIELD_POS = re.compile(r"^([A-Z][A-Z0-9\s\.\-_]*?)(\d+)$")
RE_TACKLERS = re.compile(r"\(([^()]+)\)\s*\.?\s*$")
RE_LASTFIRST_TOKEN = re.compile(r"\b([A-Z][a-zA-Z\-']+),([A-Z][a-zA-Z\-']+)\b")


def _parse_matchup_teams_from_label(label: str) -> tuple[str, str] | None:
    match = re.search(r":\s+(.+?)\s+(?:vs\.|at)\s+(.+?)(?::\s+@|:\s+Box Score|$)", label)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _norm(value: str) -> str:
    return value.lower().replace(" ", "").replace(".", "")


def normalize_field_position(token: str | None) -> str | None:
    if not token:
        return None
    token = token.strip().upper()
    token = re.sub(r"~\d(?=\d{2})|~", "", token)
    return re.sub(r"\s+", " ", token)


def clean_player(name: str | None) -> str | None:
    if not name:
        return None
    name = name.strip()
    if name.upper() == "TEAM":
        return None
    if "," in name and " " not in name.split(",", 1)[0]:
        last, first = [part.strip() for part in name.split(",", 1)]
        if first:
            return f"{first} {last}"
    return name


def parse_yards(text: str) -> int | None:
    if RE_NO_GAIN.search(text):
        return 0
    match = RE_YARDS.search(text)
    if not match:
        return None
    yards = int(match.group(2))
    return -yards if match.group(1) else yards


def parse_tacklers(text: str) -> tuple[str | None, str | None]:
    match = RE_TACKLERS.search(text)
    if not match:
        return None, None
    parts = [clean_player(part) for part in match.group(1).split(";")]
    players = [part for part in parts if part]
    first = players[0] if len(players) > 0 else None
    second = players[1] if len(players) > 1 else None
    return first, second


def normalize_lastfirst(text: str) -> str:
    return RE_LASTFIRST_TOKEN.sub(lambda match: f"{match.group(2)} {match.group(1)}", text)


def normalize_play_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"&nbsp;?|&nbs\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", text)
    return text.strip()


def _stamp_pass_flags(play: dict[str, object]) -> None:
    play["is_dropback"] = True
    play["is_attempt"] = not play["is_sack"]
    play["completion"] = play["pass_result"] == "complete"
    play["is_interception"] = play["pass_result"] == "int"


def _team_matches(team_name: str, drive_token: str) -> bool:
    team = _norm(team_name)
    drive = _norm(drive_token)
    return bool(team) and bool(drive) and (team in drive or drive in team)


def field_pos_to_abs(token: str, offense: str | None) -> int | None:
    if not offense:
        return None
    normalized = normalize_field_position(token)
    if not normalized:
        return None
    match = RE_FIELD_POS.match(normalized)
    if not match:
        return None
    prefix, yard = match.group(1), int(match.group(2))
    if _norm(prefix) in _norm(offense):
        return yard
    return 100 - yard


def parse_play(text: str) -> dict[str, object]:
    text = normalize_lastfirst(normalize_play_text(text))
    play: dict[str, object] = {
        "play_type": None,
        "passer": None,
        "rusher": None,
        "receiver": None,
        "pass_result": None,
        "yards_gained": None,
        "is_dropback": False,
        "is_attempt": False,
        "completion": False,
        "is_interception": False,
        "is_td": bool(RE_TD.search(text)) and not bool(RE_INT.search(text)),
        "is_sack": False,
        "is_fumble": False,
        "fumble_recovered_by": None,
        "is_penalty": False,
        "penalty_team": None,
        "penalty_type": None,
        "penalty_player": None,
        "penalty_yards": None,
        "fg_result": None,
        "tackler_1": None,
        "tackler_2": None,
    }

    pen = RE_PENALTY_NAMED.search(text)
    if pen:
        play["is_penalty"] = True
        play["penalty_team"] = pen.group(1).strip().upper()
        play["penalty_type"] = pen.group(2).strip().lower()
        play["penalty_player"] = pen.group(3).strip()
        play["penalty_yards"] = int(pen.group(4))
    else:
        pen = RE_PENALTY_ANON.search(text)
        if pen:
            play["is_penalty"] = True
            play["penalty_team"] = pen.group(1).strip().upper()
            play["penalty_type"] = pen.group(2).strip().lower()
            play["penalty_yards"] = int(pen.group(3))

    fumble = RE_FUMBLE.search(text)
    if fumble:
        play["is_fumble"] = True
        play["fumble_recovered_by"] = fumble.group(2).strip().upper()
        play["_fumble_recovery_loc"] = fumble.group(4).strip().upper()

    sack = RE_SACK.search(text) or RE_SACK_ALT.search(text)
    if sack:
        play["play_type"] = "pass"
        play["is_sack"] = True
        play["passer"] = clean_player(sack.group(1))
        play["yards_gained"] = parse_yards(text)
        play["tackler_1"], play["tackler_2"] = parse_tacklers(text)
        _stamp_pass_flags(play)
        return play

    field_goal = RE_FG.search(text)
    if field_goal:
        play["play_type"] = "field_goal"
        play["rusher"] = clean_player(field_goal.group(1))
        play["fg_result"] = field_goal.group(3).lower()
        return play

    blocked_fg = RE_FG_BLOCKED.search(text)
    if blocked_fg:
        play["play_type"] = "field_goal"
        play["rusher"] = clean_player(blocked_fg.group(1))
        play["fg_result"] = "blocked"
        return play

    pat = RE_PAT.search(text)
    if pat:
        play["play_type"] = "pat"
        play["rusher"] = clean_player(pat.group(1))
        play["fg_result"] = pat.group(2).lower()
        return play

    two_point = RE_TWO_PT.search(text)
    if two_point:
        play["play_type"] = "two_point"
        play["rusher"] = clean_player(two_point.group(1))
        play["fg_result"] = two_point.group(2).lower()
        return play

    kickoff = RE_KICKOFF.search(text)
    if kickoff:
        play["play_type"] = "kickoff"
        play["rusher"] = clean_player(kickoff.group(1))
        play["yards_gained"] = int(kickoff.group(2))
        return play

    punt = RE_PUNT.search(text)
    if punt:
        play["play_type"] = "punt"
        play["rusher"] = clean_player(punt.group(1))
        play["yards_gained"] = int(punt.group(2)) if punt.group(2) else parse_yards(text)
        return play

    intercept = RE_PASS_INT.search(text)
    if intercept:
        play["play_type"] = "pass"
        play["passer"] = clean_player(intercept.group(1))
        play["pass_result"] = "int"
        play["yards_gained"] = 0
        play["tackler_1"], play["tackler_2"] = parse_tacklers(text)
        _stamp_pass_flags(play)
        return play

    complete_named = RE_PASS_COMPLETE_A.search(text)
    if complete_named:
        play["play_type"] = "pass"
        play["passer"] = clean_player(complete_named.group(1))
        play["receiver"] = clean_player(complete_named.group(2))
        play["pass_result"] = "complete"
        play["yards_gained"] = parse_yards(text)
        play["tackler_1"], play["tackler_2"] = parse_tacklers(text)
        _stamp_pass_flags(play)
        return play

    complete_unnamed = RE_PASS_COMPLETE_B.search(text)
    if complete_unnamed:
        play["play_type"] = "pass"
        play["passer"] = clean_player(complete_unnamed.group(1))
        play["pass_result"] = "complete"
        play["yards_gained"] = parse_yards(text)
        play["tackler_1"], play["tackler_2"] = parse_tacklers(text)
        _stamp_pass_flags(play)
        return play

    incomplete = RE_PASS_INCOMPLETE.search(text)
    if incomplete:
        play["play_type"] = "pass"
        play["passer"] = clean_player(incomplete.group(1))
        play["receiver"] = clean_player(incomplete.group(2)) if incomplete.group(2) else None
        play["pass_result"] = "incomplete"
        play["yards_gained"] = 0
        play["tackler_1"], play["tackler_2"] = parse_tacklers(text)
        _stamp_pass_flags(play)
        return play

    pass_attempt = RE_PASS_ATTEMPT.search(text)
    if pass_attempt:
        play["play_type"] = "pass"
        play["passer"] = clean_player(pass_attempt.group(1))
        play["receiver"] = clean_player(pass_attempt.group(2))
        if pass_attempt.group(3).lower() == "good":
            play["pass_result"] = "complete"
            play["yards_gained"] = parse_yards(text)
        elif "intercept" in text.lower():
            play["pass_result"] = "int"
            play["yards_gained"] = 0
        else:
            play["pass_result"] = "incomplete"
            play["yards_gained"] = 0
        play["tackler_1"], play["tackler_2"] = parse_tacklers(text)
        _stamp_pass_flags(play)
        return play

    rush = RE_RUSH.search(text)
    if rush:
        play["play_type"] = "rush"
        play["rusher"] = clean_player(rush.group(1))
        play["yards_gained"] = parse_yards(text)
        play["is_td"] = bool(RE_TD.search(text)) and not bool(play["is_fumble"])
        play["tackler_1"], play["tackler_2"] = parse_tacklers(text)
        return play

    if play["is_penalty"]:
        play["play_type"] = "penalty"
    return play


def parse_standings_html(html: str, season: str, run_id: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    teams: list[dict[str, str]] = []

    for table in soup.select("table.table.bg-white"):
        conf_th = table.select_one("thead th[colspan]")
        conference = conf_th.get_text(strip=True) if conf_th else "Unknown"

        for row in table.select("tbody tr"):
            link = row.select_one('a[href*="schedule?teamId"]')
            if not link:
                continue

            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = BASE_URL + href
            qs = parse_qs(urlparse(href).query)
            team_id = qs.get("teamId", [None])[0]
            team_name = (link.select_one("span.team-name") or link).get_text(strip=True)
            cells = row.select("td.stats-col")

            def cell(index: int) -> str:
                return cells[index].get_text(strip=True) if index < len(cells) else ""

            def split_wlt(value: str) -> tuple[str, str, str]:
                parts = value.split("-")
                wins = parts[0] if len(parts) > 0 else ""
                losses = parts[1] if len(parts) > 1 else ""
                ties = parts[2] if len(parts) > 2 else "0"
                return wins, losses, ties

            conf_w, conf_l, conf_t = split_wlt(cell(1))
            overall_w, overall_l, overall_t = split_wlt(cell(4))

            teams.append(
                {
                    "run_id": run_id,
                    "season": season,
                    "conference": conference,
                    "team_name": team_name,
                    "team_id": team_id or "",
                    "schedule_url": href,
                    "conf_gp": cell(0),
                    "conf_w": conf_w,
                    "conf_l": conf_l,
                    "conf_t": conf_t,
                    "conf_pct": cell(2),
                    "overall_gp": cell(3),
                    "overall_w": overall_w,
                    "overall_l": overall_l,
                    "overall_t": overall_t,
                    "overall_pct": cell(5),
                }
            )

    return teams


def parse_schedule_html(html: str, team: dict[str, str], season: str, run_id: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    games: list[dict[str, str]] = []

    for row in soup.select("tr.event-row"):
        link = row.select_one('a[href*="/boxscores/"]')
        if not link:
            continue

        href = link.get("href", "")
        if href and not href.startswith("http"):
            href = BASE_URL + href

        match = re.search(r"boxscores/(\d{8}_\w+)\.xml", href)
        if not match:
            continue

        game_id = match.group(1)
        game_date = game_id[:8]
        classes = row.get("class", [])
        home_away = "home" if "home" in classes else "away"

        opp_cell = row.select_one("td.team.opponent span.team-name")
        opponent = opp_cell.get_text(strip=True) if opp_cell else ""

        result_cell = row.select_one("td.result")
        result = result_cell.get_text(strip=True) if result_cell else ""

        pbp_url = href.rstrip("?") + "?view=plays"
        if "neutral" in classes:
            aria_label = link.get("aria-label", "")
            matchup = _parse_matchup_teams_from_label(aria_label)
            if matchup is not None:
                first_team, second_team = matchup
                if second_team == team["team_name"]:
                    home_away = "home"
                elif first_team == team["team_name"]:
                    home_away = "away"

        if home_away == "home":
            home_name, away_name = team["team_name"], opponent
        else:
            home_name, away_name = opponent, team["team_name"]

        games.append(
            {
                "run_id": run_id,
                "season": season,
                "team_name": team["team_name"],
                "team_id": team["team_id"],
                "game_id": game_id,
                "game_date": game_date,
                "home_away": home_away,
                "opponent": opponent,
                "result": result,
                "pbp_url": pbp_url,
                "schedule_home": home_name,
                "schedule_away": away_name,
            }
        )

    return games


def build_games_rows(schedule_rows: list[dict[str, str]], season: str, run_id: str) -> list[dict[str, str | int]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in schedule_rows:
        game_id = (row.get("game_id") or "").strip()
        if game_id:
            grouped.setdefault(game_id, []).append(row)

    games: list[dict[str, str | int]] = []
    for game_id, rows in sorted(grouped.items()):
        canonical_names: list[str] = []
        seen_names: set[str] = set()
        home_candidates: list[str] = []
        away_candidates: list[str] = []
        schedule_home_values: set[str] = set()
        schedule_away_values: set[str] = set()

        for row in rows:
            team_name = (row.get("team_name") or "").strip()
            if team_name and team_name not in seen_names:
                seen_names.add(team_name)
                canonical_names.append(team_name)
            home_away = (row.get("home_away") or "").strip().lower()
            if home_away == "home" and team_name:
                home_candidates.append(team_name)
            elif home_away == "away" and team_name:
                away_candidates.append(team_name)
            schedule_home = (row.get("schedule_home") or "").strip()
            schedule_away = (row.get("schedule_away") or "").strip()
            if schedule_home:
                schedule_home_values.add(schedule_home)
            if schedule_away:
                schedule_away_values.add(schedule_away)

        team_1 = canonical_names[0] if len(canonical_names) > 0 else ""
        team_2 = canonical_names[1] if len(canonical_names) > 1 else ""
        unique_team_count = len(canonical_names)
        row_count = len(rows)
        home_team_canonical = home_candidates[0] if len(home_candidates) == 1 else ""
        away_team_canonical = away_candidates[0] if len(away_candidates) == 1 else ""
        valid_teams = {team for team in (team_1, team_2) if team}

        if not home_team_canonical and len(schedule_home_values) == 1:
            only_home = next(iter(schedule_home_values))
            if only_home in valid_teams:
                home_team_canonical = only_home
        if not away_team_canonical and len(schedule_away_values) == 1:
            only_away = next(iter(schedule_away_values))
            if only_away in valid_teams:
                away_team_canonical = only_away

        if unique_team_count == 2 and row_count == 2:
            pairing_status = "paired"
        elif unique_team_count == 2:
            pairing_status = "duplicate-rows"
        elif unique_team_count == 1:
            pairing_status = "single-sided"
        elif unique_team_count > 2:
            pairing_status = "over-paired"
        else:
            pairing_status = "incomplete"

        first = rows[0]
        games.append(
            {
                "run_id": run_id,
                "season": season,
                "game_id": game_id,
                "game_date": first.get("game_date", ""),
                "pbp_url": first.get("pbp_url", ""),
                "schedule_home": first.get("schedule_home", ""),
                "schedule_away": first.get("schedule_away", ""),
                "home_team_canonical": home_team_canonical,
                "away_team_canonical": away_team_canonical,
                "team_1": team_1,
                "team_2": team_2,
                "schedule_row_count": row_count,
                "unique_team_count": unique_team_count,
                "pairing_status": pairing_status,
            }
        )

    return games


def parse_pbp_html(html: str, game: dict[str, str], season: str, run_id: str) -> list[dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tr")

    home_team = game.get("home_team_canonical") or game.get("schedule_home") or ""
    away_team = game.get("away_team_canonical") or game.get("schedule_away") or ""
    match_home = home_team
    match_away = away_team

    plays: list[dict[str, object]] = []
    play_id = 0
    drive_id = 0
    quarter = 1
    drive_start_time: str | None = None
    offense: str | None = None
    defense: str | None = None

    for row in rows:
        headers = row.find_all("th")
        cells = row.find_all("td")

        if cells and cells[0].get("id", "").startswith("qtr"):
            text = normalize_play_text(cells[0].get_text(" ", strip=True))
            match = re.search(r"(\d+)", text)
            if match:
                quarter = int(match.group(1))
            continue

        if headers and len(headers) == 1:
            header = normalize_play_text(headers[0].get_text(" ", strip=True))
            match = RE_DRIVE_HEADER.match(header)
            if match:
                drive_id += 1
                drive_team = match.group(1).strip()
                drive_start_time = match.group(2).strip()
                if _team_matches(match_home, drive_team):
                    offense = home_team
                    defense = away_team
                elif _team_matches(match_away, drive_team):
                    offense = away_team
                    defense = home_team
                else:
                    offense = drive_team
                    defense = None
            continue

        if len(cells) != 2:
            continue

        situation_text = normalize_play_text(cells[0].get_text(" ", strip=True))
        play_text = normalize_play_text(cells[1].get_text(" ", strip=True))

        if RE_DRIVE_START.search(play_text):
            continue
        quarter_match = RE_QUARTER_START.search(play_text)
        if quarter_match:
            quarter = int(quarter_match.group(1))
            continue
        ball_on = re.match(r"^([A-Z][A-Z\s]*?)\s+ball on", play_text)
        if ball_on:
            token = ball_on.group(1).strip().upper()
            if match_home.upper().startswith(token) or token in match_home.upper():
                offense, defense = home_team, away_team
            elif match_away.upper().startswith(token) or token in match_away.upper():
                offense, defense = away_team, home_team
            continue
        if not play_text or play_text == "\xa0":
            continue
        if re.match(r"^[A-Za-z\s\.]+\d+,\s*[A-Za-z\s\.]+\d+$", play_text):
            continue
        if re.match(r"^[A-Za-z\s\.]+ \d+$", play_text):
            continue
        if re.match(r"End of (half|game|quarter|overtime)", play_text, re.IGNORECASE):
            continue
        if RE_TIMEOUT.match(play_text) or RE_CLOCK_ONLY.match(play_text):
            continue
        if re.match(r"^\d+:\d+\s+TO$", play_text):
            continue
        if re.match(r"^Game clock", play_text, re.IGNORECASE):
            continue
        if re.search(r",\s*NO PLAY", play_text, re.IGNORECASE):
            continue

        down: int | None = None
        distance: int | None = None
        field_position: str | None = None

        situation = RE_DOWN_DIST.search(situation_text)
        if situation:
            down = int(situation.group(1))
            raw_distance = situation.group(2)
            field_position = normalize_field_position(situation.group(3))
            if raw_distance.lower() == "goal":
                abs_yardline = field_pos_to_abs(field_position or "", offense)
                distance = abs_yardline
            else:
                distance = int(raw_distance)

        play_id += 1
        parsed = parse_play(play_text)

        if parsed.get("is_fumble") and field_position:
            recovery_loc = parsed.pop("_fumble_recovery_loc", None)
            start = field_pos_to_abs(field_position, offense)
            end = field_pos_to_abs(recovery_loc, offense) if recovery_loc else None
            if start is not None and end is not None:
                parsed["yards_gained"] = end - start
        else:
            parsed.pop("_fumble_recovery_loc", None)

        yardline_raw = None
        if field_position:
            yardline_match = RE_FIELD_POS.match(field_position)
            if yardline_match:
                yardline_raw = int(yardline_match.group(2))

        plays.append(
            {
                "run_id": run_id,
                "season": season,
                "game_id": game["game_id"],
                "home_team": home_team,
                "away_team": away_team,
                "schedule_home": game.get("schedule_home", ""),
                "schedule_away": game.get("schedule_away", ""),
                "play_id": play_id,
                "drive_id": drive_id,
                "drive_start_time": drive_start_time or "",
                "quarter": quarter,
                "down": down,
                "distance": distance,
                "field_position": field_position or "",
                "yardline_raw": yardline_raw,
                "offense": offense or "",
                "defense": defense or "",
                **parsed,
                "raw_text": play_text,
            }
        )

    return plays
