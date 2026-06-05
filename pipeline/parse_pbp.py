"""
Parse a PrestoSports football play-by-play HTML file into a flat CSV.
Usage: python parse_pbp.py hill-pbp-example.html output.csv
"""

import re
import csv
import sys
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Regex patterns for play description parsing
# ---------------------------------------------------------------------------

RE_DOWN_DIST = re.compile(
    r'(\d+)(?:st|nd|rd|th)\s+and\s+(\d+|goal)\s+at\s+([A-Z][A-Z0-9\s\.\-\_\~]*?\d+)',
    re.IGNORECASE
)
RE_DRIVE_START = re.compile(r'drive start at (\d+:\d+)', re.IGNORECASE)
RE_QUARTER_START = re.compile(r'Start of (\d+)(?:st|nd|rd|th) quarter', re.IGNORECASE)
RE_DRIVE_HEADER = re.compile(r'^(.+?)\s+at\s+(\d+:\d+)$')

# Play type patterns
RE_RUSH = re.compile(r'(\w[\w\s\-\'\.]+?)\s+rush for', re.IGNORECASE)
# Format A: "QB pass complete to Receiver for N yards"
RE_PASS_COMPLETE_A = re.compile(
    r'(\w[\w\s\-\'\.]+?)\s+pass complete to\s+(\w[\w\s\-\'\.]+?)\s+for', re.IGNORECASE
)
# Format B: "QB pass complete for N yards to the LOCATION" (no named receiver)
RE_PASS_COMPLETE_B = re.compile(
    r'(\w[\w\s\-\'\.]+?)\s+pass complete(?:\s+for|\s+to)', re.IGNORECASE
)
# Incomplete: with or without named receiver, with or without trailing comma/PENALTY
RE_PASS_INCOMPLETE = re.compile(
    r'(\w[\w\s\-\'\.]+?)\s+pass incomplete(?:\s+to\s+(\w[\w\s\-\'\.]+?))?'
    r'(?:\s*[,(]|,\s*PENALTY|\.|$)', re.IGNORECASE
)
RE_PASS_INT = re.compile(
    r'(\w[\w\s\-\'\.]+?)\s+pass intercept', re.IGNORECASE
)
RE_SACK = re.compile(r'(\w[\w\s\-\'\.]+?)\s+sacked for', re.IGNORECASE)
RE_PUNT = re.compile(r'(\w[\w\s\-\'\.]+?)\s+punt(?:\s+(\d+)\s+yards)?', re.IGNORECASE)
RE_KICKOFF = re.compile(r'(\w[\w\s\-\'\.]+?)\s+kickoff\s+(\d+)\s+yards', re.IGNORECASE)
RE_FG = re.compile(
    r'(\w[\w\s\-\'\.]+?)\s+field goal attempt from\s+(\d+)\s+(GOOD|MISSED)', re.IGNORECASE
)
RE_PAT = re.compile(r'(\w[\w\s\-\'\.]+?)\s+kick attempt\s+(GOOD|FAILED)', re.IGNORECASE)
RE_TWO_PT = re.compile(r'(\w[\w\s\-\'\.]+?)\s+(?:rush|pass)\s+attempt\s+(good|failed)', re.IGNORECASE)
# Team token in penalties = sequence of ALL-CAPS words before the lowercase penalty type
_TEAM_TOK = r'((?:[A-Z]+\s+)*[A-Z]+)'
# Penalty with named player: "PENALTY TEAM type (Player) N yards"
RE_PENALTY_NAMED = re.compile(
    r'PENALTY\s+' + _TEAM_TOK + r'\s+([a-z][\w\s]*?)\s*\(([^)]+)\)\s+(\d+)\s+yards',
)
# Penalty without named player: "PENALTY TEAM type N yards"
RE_PENALTY_ANON = re.compile(
    r'PENALTY\s+' + _TEAM_TOK + r'\s+([a-z][\w\s]+?)\s+(\d+)\s+yards',
)
RE_YARDS = re.compile(r'for\s+(loss of\s+)?(\d+)\s+yards?', re.IGNORECASE)
RE_NO_GAIN = re.compile(r'for no gain', re.IGNORECASE)
RE_TD = re.compile(r'touchdown', re.IGNORECASE)
RE_INT = re.compile(r'intercept', re.IGNORECASE)
RE_TIMEOUT = re.compile(r'^Timeout\s', re.IGNORECASE)
RE_CLOCK_ONLY = re.compile(r'^clock\s+\d+:\d+\.$', re.IGNORECASE)
RE_FUMBLE = re.compile(
    r'fumble by\s+(\w[\w\s\-\'\.]+?)\s+recovered by\s+(\w+)\s+(\w[\w\s\-\'\.]+?)\s+at\s+([A-Z][A-Z0-9\s\.\-\_]*?\d+)',
    re.IGNORECASE
)
RE_FIELD_POS = re.compile(r'^([A-Z][A-Z0-9\s\.\-\_]*?)(\d+)$')
RE_TACKLERS = re.compile(r'\(([^)]+)\)\s*\.?\s*$')


def normalize_team(name: str) -> str:
    """Shorten team names to a consistent token."""
    return name.strip().upper().replace(' ', '_')


def normalize_field_position(token: str | None) -> str | None:
    """Uppercase a field-position token, collapse whitespace, and strip PrestoSports
    truncation artifacts.

    PrestoSports sometimes emits a tilde in field position tokens:
      - 3-digit suffix (e.g. SADDLE~139): the leading digit is a truncation artifact;
        strip ~+digit to recover the real yardline  -> SADDLE39
      - 2-digit suffix (e.g. SBCC~45): tilde is just a separator; strip ~ only -> SBCC45
    """
    if not token:
        return None
    t = token.strip().upper()
    t = re.sub(r'~\d(?=\d{2})|~', '', t)
    return re.sub(r'\s+', ' ', t)


def field_pos_to_abs(token: str, offense: str) -> int | None:
    """Convert e.g. FOOTHILL18 or MONTEREY33 to yards from offense's own goal line."""
    norm_token = normalize_field_position(token)
    if not norm_token:
        return None
    m = RE_FIELD_POS.match(norm_token)
    if not m:
        return None
    prefix, n = m.group(1), int(m.group(2))
    # If the prefix is a substring of the offense team name, it's the offense's side
    if _norm(prefix) in _norm(offense):
        return n
    return 100 - n


def parse_yards(text: str):
    """Return net yards as int, or None."""
    if RE_NO_GAIN.search(text):
        return 0
    m = RE_YARDS.search(text)
    if m:
        yards = int(m.group(2))
        return -yards if m.group(1) else yards
    return None


def clean_player(name: str | None) -> str | None:
    """Return None for TEAM placeholders or empty strings."""
    if not name:
        return None
    return None if name.strip().upper() == 'TEAM' else name.strip()


def parse_tacklers(text: str):
    """Return (tackler_1, tackler_2) from trailing parenthetical, skipping TEAM."""
    m = RE_TACKLERS.search(text)
    if not m:
        return None, None
    parts = [clean_player(p) for p in m.group(1).split(';')]
    parts = [p for p in parts if p]  # drop None/TEAM entries
    t1 = parts[0] if len(parts) > 0 else None
    t2 = parts[1] if len(parts) > 1 else None
    return t1, t2


def parse_play(text: str, offense: str, defense: str) -> dict:
    """Extract structured fields from a single play description string."""
    p = {
        'play_type': None,
        'ball_carrier': None,
        'targeted_receiver': None,
        'pass_result': None,
        'yards_gained': None,
        'is_td': False,
        'is_sack': False,
        'is_fumble': False,
        'fumble_recovered_by': None,
        'is_penalty': False,
        'penalty_team': None,
        'penalty_type': None,
        'penalty_player': None,
        'penalty_yards': None,
        'fg_result': None,
        'tackler_1': None,
        'tackler_2': None,
    }

    # TD is true only when the offense scores — interception/fumble returns that end
    # in a touchdown contain "TOUCHDOWN" in the text but the score belongs to the defense.
    _is_int = bool(RE_INT.search(text))
    p['is_td'] = bool(RE_TD.search(text)) and not _is_int

    # Penalty details — try named player first, fall back to anonymous
    p['is_penalty'] = bool(RE_PENALTY_NAMED.search(text) or RE_PENALTY_ANON.search(text))
    pen = RE_PENALTY_NAMED.search(text)
    if pen:
        p['penalty_team'] = pen.group(1).strip().upper()
        p['penalty_type'] = pen.group(2).strip().lower()
        p['penalty_player'] = pen.group(3).strip()
        p['penalty_yards'] = int(pen.group(4))
    else:
        pen = RE_PENALTY_ANON.search(text)
        if pen:
            p['penalty_team'] = pen.group(1).strip().upper()
            p['penalty_type'] = pen.group(2).strip().lower()
            p['penalty_yards'] = int(pen.group(3))

    # Fumble
    fm = RE_FUMBLE.search(text)
    if fm:
        p['is_fumble'] = True
        p['fumble_recovered_by'] = fm.group(2).strip().upper()
        p['_fumble_recovery_loc'] = fm.group(4).strip().upper()

    # Sack
    sk = RE_SACK.search(text)
    if sk:
        p['play_type'] = 'pass'
        p['is_sack'] = True
        p['ball_carrier'] = clean_player(sk.group(1))
        p['yards_gained'] = parse_yards(text)
        p['tackler_1'], p['tackler_2'] = parse_tacklers(text)
        return p

    # Field goal
    fg = RE_FG.search(text)
    if fg:
        p['play_type'] = 'field_goal'
        p['ball_carrier'] = clean_player(fg.group(1))
        p['fg_result'] = fg.group(3).lower()
        return p

    # PAT (kick)
    pat = RE_PAT.search(text)
    if pat:
        p['play_type'] = 'pat'
        p['ball_carrier'] = clean_player(pat.group(1))
        p['fg_result'] = pat.group(2).lower()
        return p

    # 2-point conversion
    two = RE_TWO_PT.search(text)
    if two:
        p['play_type'] = 'two_point'
        p['ball_carrier'] = clean_player(two.group(1))
        p['fg_result'] = two.group(2).lower()
        return p

    # Kickoff
    ko = RE_KICKOFF.search(text)
    if ko:
        p['play_type'] = 'kickoff'
        p['ball_carrier'] = clean_player(ko.group(1))
        p['yards_gained'] = int(ko.group(2))
        return p

    # Punt (may have no yardage if blocked)
    pu = RE_PUNT.search(text)
    if pu:
        p['play_type'] = 'punt'
        p['ball_carrier'] = clean_player(pu.group(1))
        p['yards_gained'] = int(pu.group(2)) if pu.group(2) else parse_yards(text)
        return p

    # Interception (some formats put "pass intercepted" before any completion phrase)
    pi_int = RE_PASS_INT.search(text)
    if pi_int:
        p['play_type'] = 'pass'
        p['ball_carrier'] = clean_player(pi_int.group(1))
        p['pass_result'] = 'int'
        p['yards_gained'] = 0
        p['tackler_1'], p['tackler_2'] = parse_tacklers(text)
        return p

    # Pass complete — Format A: named receiver ("pass complete to X for")
    pc = RE_PASS_COMPLETE_A.search(text)
    if pc:
        p['play_type'] = 'pass'
        p['ball_carrier'] = clean_player(pc.group(1))
        p['targeted_receiver'] = clean_player(pc.group(2))
        p['pass_result'] = 'complete'
        p['yards_gained'] = parse_yards(text)
        p['tackler_1'], p['tackler_2'] = parse_tacklers(text)
        return p

    # Pass complete — Format B: no named receiver ("pass complete for N yards")
    pc2 = RE_PASS_COMPLETE_B.search(text)
    if pc2:
        p['play_type'] = 'pass'
        p['ball_carrier'] = clean_player(pc2.group(1))
        p['pass_result'] = 'complete'
        p['yards_gained'] = parse_yards(text)
        p['tackler_1'], p['tackler_2'] = parse_tacklers(text)
        return p

    # Pass incomplete
    pi = RE_PASS_INCOMPLETE.search(text)
    if pi:
        p['play_type'] = 'pass'
        p['ball_carrier'] = clean_player(pi.group(1))
        p['targeted_receiver'] = clean_player(pi.group(2)) if pi.group(2) else None
        p['pass_result'] = 'incomplete'
        p['yards_gained'] = 0
        p['tackler_1'], p['tackler_2'] = parse_tacklers(text)
        return p

    # Rush
    ru = RE_RUSH.search(text)
    if ru:
        p['play_type'] = 'rush'
        p['ball_carrier'] = clean_player(ru.group(1))
        p['yards_gained'] = parse_yards(text)
        # fumble return TDs score for the defense, not the offense
        p['is_td'] = bool(RE_TD.search(text)) and not p['is_fumble']
        p['tackler_1'], p['tackler_2'] = parse_tacklers(text)
        return p

    # Penalty-only play
    if p['is_penalty']:
        p['play_type'] = 'penalty'
        return p

    return p


def make_game_id(date_str: str, home: str, away: str) -> str:
    """YYYYMMDD_HOME_AWAY"""
    h = normalize_team(home)
    a = normalize_team(away)
    return f"{date_str}_{h}_{a}"


def parse_html(html: str, game_id_override: str = None, schedule_home: str = None, schedule_away: str = None, crosswalk_map: dict = None) -> list[dict]:
    """Parse raw HTML string (for use by scrapers)."""
    return _parse_soup(BeautifulSoup(html, 'html.parser'), game_id_override, schedule_home, schedule_away, crosswalk_map)


def parse_file(html_path: str) -> list[dict]:
    with open(html_path, encoding='utf-8', errors='replace') as f:
        soup = BeautifulSoup(f, 'html.parser')
    return _parse_soup(soup)


def _norm(s: str) -> str:
    """Normalize for fuzzy team matching: lowercase, strip spaces."""
    return s.lower().replace(' ', '').replace('.', '')


def _team_matches(team_name: str, drive_token: str) -> bool:
    """True if team_name and drive_token refer to the same team."""
    t = _norm(team_name)
    d = _norm(drive_token)
    return t in d or d in t


def _parse_soup(soup, game_id_override: str = None, schedule_home: str = None, schedule_away: str = None, crosswalk_map: dict = None) -> list[dict]:

    # --- Game metadata ---
    title_tag = soup.find('meta', property='og:title')
    title = title_tag['content'] if title_tag else ''
    # "Foothill vs. Monterey Peninsula - Box Score - 8/30/2025"
    title_m = re.match(r'(.+?)\s+vs\.\s+(.+?)\s+-\s+Box Score', title)
    raw_pbp_home = title_m.group(1).strip() if title_m else 'HOME'
    raw_pbp_away = title_m.group(2).strip() if title_m else 'AWAY'

    url_tag = soup.find('link', rel='canonical')
    url = url_tag['href'] if url_tag else ''
    date_m = re.search(r'boxscores/(\d{8})', url)
    game_date = date_m.group(1) if date_m else '00000000'

    game_id = game_id_override if game_id_override else make_game_id(game_date, raw_pbp_home, raw_pbp_away)

    home_team = schedule_home or raw_pbp_home
    away_team = schedule_away or raw_pbp_away
    # When schedule names are available use them directly for drive-header matching —
    # og:title sometimes uses abbreviations or mascot names that mismatch drive headers.
    # Fall back to og:title names (with swap detection) only when schedule is absent.
    if schedule_home and schedule_away:
        match_home = home_team
        match_away = away_team
    elif (raw_pbp_home not in ('HOME',)
            and _team_matches(schedule_away or away_team, raw_pbp_home)
            and _team_matches(schedule_home or home_team, raw_pbp_away)):
        match_home = raw_pbp_away
        match_away = raw_pbp_home
    else:
        match_home = raw_pbp_home
        match_away = raw_pbp_away

    # --- Walk the play table rows ---
    rows = soup.select('table tr')

    plays = []
    play_id = 0
    drive_id = 0
    quarter = 1
    drive_start_time = None
    offense = None
    defense = None
    down = None
    distance = None
    field_position = None

    for row in rows:
        ths = row.find_all('th')
        tds = row.find_all('td')

        # Quarter header row  (id="qtr1" etc.)
        if tds and tds[0].get('id', '').startswith('qtr'):
            text = tds[0].get_text(' ', strip=True)
            qm = re.search(r'(\d+)', text)
            if qm:
                quarter = int(qm.group(1))
            continue

        # Drive header  <th colspan="2">Monterey Peninsula at 14:54</th>
        if ths and len(ths) == 1:
            header = ths[0].get_text(' ', strip=True)
            hm = RE_DRIVE_HEADER.match(header)
            if hm:
                drive_id += 1
                team_name = hm.group(1).strip()
                drive_start_time = hm.group(2).strip()
                # Determine offense/defense
                if _team_matches(match_home, team_name):
                    offense = home_team
                    defense = away_team
                elif _team_matches(match_away, team_name):
                    offense = away_team
                    defense = home_team
                else:
                    offense = team_name
                    defense = None
            continue

        # Play rows — must have exactly 2 <td>
        if len(tds) != 2:
            continue

        situation_text = tds[0].get_text(' ', strip=True)
        play_text = tds[1].get_text(' ', strip=True)

        # Skip non-play rows (drive start notices, clock notices)
        if RE_DRIVE_START.search(play_text):
            continue
        if RE_QUARTER_START.search(play_text):
            qm = RE_QUARTER_START.search(play_text)
            if qm:
                quarter = int(qm.group(1))
            continue
        # "FOOTHILL ball on MONTEREY25, clock 15:00." — tells us who has the ball
        # (appears in OT where there is no drive <th> header)
        ball_on = re.match(r'^([A-Z][A-Z\s]*?)\s+ball on', play_text)
        if ball_on:
            token = ball_on.group(1).strip().upper()
            if match_home.upper().startswith(token) or token in match_home.upper():
                offense = home_team; defense = away_team
            elif match_away.upper().startswith(token) or token in match_away.upper():
                offense = away_team; defense = home_team
            continue
        if not play_text or play_text == '\xa0':
            continue
        # Score updates like "Foothill 7, Monterey Peninsula 0" or "Mt. San Antonio 35"
        if re.match(r'^[A-Za-z\s\.]+\d+,\s*[A-Za-z\s\.]+\d+$', play_text):
            continue
        if re.match(r'^[A-Za-z\s\.]+ \d+$', play_text):
            continue
        if re.match(r'End of (half|game|quarter|overtime)', play_text, re.IGNORECASE):
            continue
        if RE_TIMEOUT.match(play_text):
            continue
        if RE_CLOCK_ONLY.match(play_text):
            continue
        if re.match(r'^\d+:\d+\s+TO$', play_text):  # two-minute warning "2:00 TO"
            continue
        if re.match(r'^Game clock', play_text, re.IGNORECASE):  # announcer notes
            continue
        if re.search(r',\s*NO PLAY', play_text, re.IGNORECASE):  # penalty-nullified play
            continue

        row_down = None
        row_distance = None
        row_field_position = None
        row_is_goal = False

        # Parse situation cell  "1st and 10 at MONTEREY17" or "1st and 10 at SAN MATE48"
        sit = RE_DOWN_DIST.search(situation_text)
        if sit:
            row_down = int(sit.group(1))
            dist_raw = sit.group(2)
            row_is_goal = dist_raw.lower() == 'goal'
            row_distance = None if row_is_goal else int(dist_raw)
            row_field_position = normalize_field_position(sit.group(3))

        play_id += 1
        parsed = parse_play(play_text, offense, defense)

        # Fumble: net yards = field position change from LOS to recovery spot
        if parsed.get('is_fumble') and row_field_position:
            rec_loc = parsed.pop('_fumble_recovery_loc', None)
            if rec_loc:
                start = field_pos_to_abs(row_field_position, offense)
                end = field_pos_to_abs(rec_loc, offense)
                if start is not None and end is not None:
                    parsed['yards_gained'] = end - start
        else:
            parsed.pop('_fumble_recovery_loc', None)

        # Enrich field position
        yardline_raw = None
        field_pos_side_val = None
        yardline_100_val = None
        if row_field_position:
            fp_m = RE_FIELD_POS.match(row_field_position)
            if fp_m:
                yardline_raw = int(fp_m.group(2))
                prefix = fp_m.group(1).strip()
                if crosswalk_map is not None:
                    owner = crosswalk_map.get(prefix)
                    if owner is not None and offense:
                        field_pos_side_val = 'own' if owner == offense else 'opponent'
                elif offense:
                    field_pos_side_val = 'own' if _norm(prefix) in _norm(offense) else 'opponent'
                if field_pos_side_val and yardline_raw is not None:
                    yardline_100_val = 100 - yardline_raw if field_pos_side_val == 'own' else yardline_raw

        # Goal-to-go: distance = yards to end zone (yardline_100)
        if row_is_goal and yardline_100_val is not None:
            row_distance = yardline_100_val

        plays.append({
            'game_id': game_id,
            'home_team': home_team,
            'away_team': away_team,
            'schedule_home': schedule_home or '',
            'schedule_away': schedule_away or '',
            'play_id': play_id,
            'drive_id': drive_id,
            'drive_start_time': drive_start_time,
            'quarter': quarter,
            'down': row_down,
            'distance': row_distance,
            'field_position': row_field_position,
            'yardline_raw': yardline_raw,
            'field_pos_side': field_pos_side_val or '',
            'yardline_100': yardline_100_val if yardline_100_val is not None else '',
            'offense': offense,
            'defense': defense,
            **parsed,
            'raw_text': play_text,
        })

    return plays


FIELDS = [
    'game_id', 'home_team', 'away_team', 'schedule_home', 'schedule_away',
    'play_id', 'drive_id', 'drive_start_time',
    'quarter', 'down', 'distance', 'field_position', 'yardline_raw', 'field_pos_side', 'yardline_100',
    'offense', 'defense',
    'play_type', 'ball_carrier', 'targeted_receiver',
    'pass_result', 'yards_gained',
    'is_td', 'is_sack', 'is_fumble', 'fumble_recovered_by',
    'is_penalty', 'penalty_team', 'penalty_type', 'penalty_player', 'penalty_yards',
    'fg_result',
    'tackler_1', 'tackler_2',
    'raw_text',
]


def main():
    html_path = sys.argv[1] if len(sys.argv) > 1 else 'hill-pbp-example.html'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'pbp_output.csv'

    plays = parse_file(html_path)

    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(plays)

    print(f"Wrote {len(plays)} plays to {out_path}")


if __name__ == '__main__':
    main()
