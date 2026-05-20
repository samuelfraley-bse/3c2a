"""
Scrape a full 3C2A football season into three CSVs.

Usage:
    python scrape_season.py --season 2025-26 [--delay 1.5] [--out outputs/]
    python scrape_season.py --standings-url https://3c2asports.org/sports/fball/2025-26/standings
    python scrape_season.py --season 2025-26 --schedule-url <url1> --schedule-url <url2>
    python scrape_season.py --season 2025-26 --plays-only [--delay 2.0] [--out outputs/]

Outputs (under --out/{season}/):
    standings.csv   - one row per team
    schedule.csv    - one row per team-game pair
    games.csv       - one row per unique game slug, derived from schedule rows
    plays.csv       - all play-by-play rows across all games

Game ids use the stable boxscore slug only, e.g. `20251018_1561`.
"""

import argparse
import csv
import os
import re
import time
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from parse_pbp import FIELDS, parse_html

BASE = 'https://3c2asports.org'
DEFAULT_SEASON = '2025-26'

STANDINGS_FIELDS = [
    'season', 'conference', 'team_name', 'team_id', 'schedule_url',
    'conf_gp', 'conf_w', 'conf_l', 'conf_t', 'conf_pct',
    'overall_gp', 'overall_w', 'overall_l', 'overall_t', 'overall_pct',
]

SCHEDULE_FIELDS = [
    'season', 'team_name', 'team_id',
    'game_id', 'game_date', 'home_away', 'opponent', 'result', 'pbp_url',
    'schedule_home', 'schedule_away',
]

GAMES_FIELDS = [
    'season', 'game_id', 'game_date', 'pbp_url',
    'schedule_home', 'schedule_away',
    'home_team_canonical', 'away_team_canonical',
    'team_1', 'team_2',
    'schedule_row_count', 'unique_team_count', 'pairing_status',
]


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def fetch(url: str, delay: float, session: requests.Session, retries: int = 4) -> str | None:
    time.sleep(delay)
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 429:
                wait = 60 * (2 ** attempt)  # 60s, 120s, 240s, 480s
                print(f'  [429] rate limited - waiting {wait}s then retrying ({attempt+1}/{retries})')
                time.sleep(wait)
                continue
            r.raise_for_status()
            print(f'  [OK]  {url}')
            return r.text
        except requests.HTTPError as e:
            print(f'  [ERR] {url} - {e}')
            return None
        except Exception as e:
            print(f'  [ERR] {url} - {e}')
            return None
    print(f'  [FAIL] {url} - gave up after {retries} retries')
    return None


# ---------------------------------------------------------------------------
# Phase 1: Standings
# ---------------------------------------------------------------------------

def scrape_standings(standings_url: str, season: str, delay: float, session: requests.Session) -> list[dict]:
    html = fetch(standings_url, delay, session)
    if not html:
        raise SystemExit('Could not fetch standings page.')

    soup = BeautifulSoup(html, 'html.parser')
    teams = []

    for table in soup.select('table.table.bg-white'):
        conf_th = table.select_one('thead th[colspan]')
        conference = conf_th.get_text(strip=True) if conf_th else 'Unknown'

        for row in table.select('tbody tr'):
            link = row.select_one('a[href*="schedule?teamId"]')
            if not link:
                continue

            href = link['href']
            if not href.startswith('http'):
                href = BASE + href
            qs = parse_qs(urlparse(href).query)
            team_id = qs.get('teamId', [None])[0]
            team_name = (link.select_one('span.team-name') or link).get_text(strip=True)

            cells = row.select('td.stats-col')

            def cell(i):
                return cells[i].get_text(strip=True) if i < len(cells) else ''

            def split_wlt(s):
                parts = s.split('-')
                w = parts[0] if len(parts) > 0 else ''
                l = parts[1] if len(parts) > 1 else ''
                t = parts[2] if len(parts) > 2 else '0'
                return w, l, t

            conf_w, conf_l, conf_t = split_wlt(cell(1))
            overall_w, overall_l, overall_t = split_wlt(cell(4))

            teams.append({
                'season': season,
                'conference': conference,
                'team_name': team_name,
                'team_id': team_id,
                'schedule_url': href,
                'conf_gp': cell(0),
                'conf_w': conf_w,
                'conf_l': conf_l,
                'conf_t': conf_t,
                'conf_pct': cell(2),
                'overall_gp': cell(3),
                'overall_w': overall_w,
                'overall_l': overall_l,
                'overall_t': overall_t,
                'overall_pct': cell(5),
            })

    print(f'Phase 1: found {len(teams)} teams.')
    return teams


# ---------------------------------------------------------------------------
# Phase 2: Schedules
# ---------------------------------------------------------------------------

def canonicalize_schedule_url(url: str) -> str:
    parsed = urlparse(url)
    team_id = parse_qs(parsed.query).get('teamId', [''])[0]
    if not team_id:
        return url.strip().rstrip('/')
    return f'{parsed.scheme}://{parsed.netloc}{parsed.path}?teamId={team_id}'

def scrape_schedule(team: dict, season: str, delay: float, session: requests.Session) -> list[dict]:
    html = fetch(team['schedule_url'], delay, session)
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    games = []

    for row in soup.select('tr.event-row'):
        link = row.select_one('a[href*="/boxscores/"]')
        if not link:
            continue

        href = link['href']
        if not href.startswith('http'):
            href = BASE + href

        m = re.search(r'boxscores/(\d{8}_\w+)\.xml', href)
        if not m:
            continue
        slug = m.group(1)
        game_date = slug[:8]

        classes = row.get('class', [])
        home_away = 'home' if 'home' in classes else 'away'

        opp_cell = row.select_one('td.team.opponent span.team-name')
        opponent = opp_cell.get_text(strip=True) if opp_cell else ''

        result_cell = row.select_one('td.result')
        result = result_cell.get_text(strip=True) if result_cell else ''

        pbp_url = href.rstrip('?') + '?view=plays'

        if home_away == 'home':
            home_name, away_name = team['team_name'], opponent
        else:
            home_name, away_name = opponent, team['team_name']
        game_id = slug

        games.append({
            'season': season,
            'team_name': team['team_name'],
            'team_id': team['team_id'],
            'game_id': game_id,
            'game_date': game_date,
            'home_away': home_away,
            'opponent': opponent,
            'result': result,
            'pbp_url': pbp_url,
            'schedule_home': home_name,
            'schedule_away': away_name,
        })

    return games


# ---------------------------------------------------------------------------
# Phase 3: Play-by-play
# ---------------------------------------------------------------------------

def scrape_plays(game: dict, delay: float, session: requests.Session) -> list[dict]:
    html = fetch(game['pbp_url'], delay, session)
    if not html:
        return []
    return parse_html(
        html,
        game_id_override=game['game_id'],
        schedule_home=game.get('home_team_canonical') or game.get('schedule_home'),
        schedule_away=game.get('away_team_canonical') or game.get('schedule_away'),
    )


def load_schedule_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        raise SystemExit(f'Missing schedule file for --plays-only: {path}')

    with open(path, encoding='utf-8', newline='') as f:
        games = list(csv.DictReader(f))

    if not games:
        raise SystemExit(f'Schedule file is empty: {path}')

    return games


def load_games_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        raise SystemExit(f'Missing games file for --plays-only: {path}')

    with open(path, encoding='utf-8', newline='') as f:
        games = list(csv.DictReader(f))

    if not games:
        raise SystemExit(f'Games file is empty: {path}')

    return games


def resolve_entrypoint(season_arg: str | None, standings_url_arg: str | None) -> tuple[str, str]:
    if standings_url_arg:
        match = re.search(r'/sports/fball/([^/]+)/standings/?$', standings_url_arg)
        if not match:
            raise SystemExit(f'Could not parse season from standings URL: {standings_url_arg}')
        season_from_url = match.group(1)
        season = season_arg or season_from_url
        return season, standings_url_arg

    season = season_arg or DEFAULT_SEASON
    standings_url = f'{BASE}/sports/fball/{season}/standings'
    return season, standings_url


def build_games_rows(schedule_rows: list[dict], season: str) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in schedule_rows:
        game_id = (row.get('game_id') or '').strip()
        if not game_id:
            continue
        grouped.setdefault(game_id, []).append(row)

    games = []
    for game_id, rows in sorted(grouped.items()):
        canonical_names = []
        seen_names = set()
        home_candidates = []
        away_candidates = []
        for row in rows:
            team_name = (row.get('team_name') or '').strip()
            if team_name and team_name not in seen_names:
                seen_names.add(team_name)
                canonical_names.append(team_name)
            home_away = (row.get('home_away') or '').strip().lower()
            if home_away == 'home' and team_name:
                home_candidates.append(team_name)
            elif home_away == 'away' and team_name:
                away_candidates.append(team_name)

        team_1 = canonical_names[0] if len(canonical_names) > 0 else ''
        team_2 = canonical_names[1] if len(canonical_names) > 1 else ''
        unique_team_count = len(canonical_names)
        row_count = len(rows)
        home_team_canonical = home_candidates[0] if len(home_candidates) == 1 else ''
        away_team_canonical = away_candidates[0] if len(away_candidates) == 1 else ''

        if unique_team_count == 2 and row_count == 2:
            pairing_status = 'paired'
        elif unique_team_count == 2:
            pairing_status = 'duplicate-rows'
        elif unique_team_count == 1:
            pairing_status = 'single-sided'
        elif unique_team_count > 2:
            pairing_status = 'over-paired'
        else:
            pairing_status = 'incomplete'

        first = rows[0]
        games.append({
            'season': season,
            'game_id': game_id,
            'game_date': first.get('game_date', ''),
            'pbp_url': first.get('pbp_url', ''),
            'schedule_home': first.get('schedule_home', ''),
            'schedule_away': first.get('schedule_away', ''),
            'home_team_canonical': home_team_canonical,
            'away_team_canonical': away_team_canonical,
            'team_1': team_1,
            'team_2': team_2,
            'schedule_row_count': row_count,
            'unique_team_count': unique_team_count,
            'pairing_status': pairing_status,
        })

    return games


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default=None)
    parser.add_argument('--standings-url')
    parser.add_argument('--schedule-url', action='append', default=[])
    parser.add_argument('--delay', type=float, default=5.0)
    parser.add_argument('--out', default='outputs')
    parser.add_argument('--schedule-only', action='store_true')
    parser.add_argument('--plays-only', action='store_true')
    args = parser.parse_args()

    season, standings_url = resolve_entrypoint(args.season, args.standings_url)

    out_dir = os.path.join(args.out, season)
    os.makedirs(out_dir, exist_ok=True)

    standings_path = os.path.join(out_dir, 'standings.csv')
    schedule_path = os.path.join(out_dir, 'schedule.csv')
    games_path = os.path.join(out_dir, 'games.csv')
    plays_path = os.path.join(out_dir, 'plays.csv')

    session = requests.Session()
    session.headers['User-Agent'] = 'foothill-cv-research/1.0'

    if args.plays_only:
        print('\n=== Phase 3 Prep: Load Existing Games ===')
        games_rows = load_games_csv(games_path)
        print(f'Loaded {len(games_rows)} canonical games <- {games_path}')
    else:
        if args.schedule_url:
            print('\n=== Phase 1: Standings (Filtered to Target Schedule URLs) ===')
            all_teams = scrape_standings(standings_url, season, args.delay, session)
            wanted_urls = {canonicalize_schedule_url(url) for url in args.schedule_url}
            teams = [
                team for team in all_teams
                if canonicalize_schedule_url(team['schedule_url']) in wanted_urls
            ]
            found_urls = {canonicalize_schedule_url(team['schedule_url']) for team in teams}
            missing_urls = sorted(wanted_urls - found_urls)
            if missing_urls:
                for schedule_url in missing_urls:
                    print(f'  [WARN] No standings team matched schedule URL: {schedule_url}')
            if not teams:
                raise SystemExit('Could not match any --schedule-url inputs to standings teams.')
        else:
            print('\n=== Phase 1: Standings ===')
            teams = scrape_standings(standings_url, season, args.delay, session)

        with open(standings_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=STANDINGS_FIELDS)
            w.writeheader()
            w.writerows(teams)
        print(f'Wrote {len(teams)} rows -> {standings_path}')

        print('\n=== Phase 2: Schedules ===')
        all_games = []
        seen_game_ids = set()

        for team in teams:
            print(f'  Schedule: {team["team_name"]}')
            games = scrape_schedule(team, season, args.delay, session)
            all_games.extend(games)
            for game in games:
                seen_game_ids.add(game['game_id'])

        with open(schedule_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=SCHEDULE_FIELDS)
            w.writeheader()
            w.writerows(all_games)
        print(f'Wrote {len(all_games)} rows ({len(seen_game_ids)} unique games) -> {schedule_path}')

        games_rows = build_games_rows(all_games, season)
        with open(games_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=GAMES_FIELDS)
            w.writeheader()
            w.writerows(games_rows)
        paired = sum(1 for row in games_rows if row['pairing_status'] == 'paired')
        print(f'Wrote {len(games_rows)} rows ({paired} fully paired) -> {games_path}')

    if args.schedule_only:
        print('\nDone.')
        return

    print('\n=== Phase 3: Play-by-Play ===')

    existing_game_ids = set()
    if os.path.exists(plays_path):
        with open(plays_path, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                gid = row.get('game_id', '')
                if gid:
                    existing_game_ids.add(gid)
        print(f'  Resuming - {len(existing_game_ids)} games already in plays.csv')

    with open(plays_path, 'a', newline='', encoding='utf-8') as plays_file:
        writer = csv.DictWriter(plays_file, fieldnames=FIELDS, extrasaction='ignore')
        if not existing_game_ids:
            writer.writeheader()

        total_plays = 0
        for game in games_rows:
            game_id = game['game_id']
            if game_id in existing_game_ids:
                print(f'  [SKIP] {game_id}')
                continue
            print(f'  PBP: {game_id}')
            plays = scrape_plays(game, args.delay, session)
            writer.writerows(plays)
            plays_file.flush()
            total_plays += len(plays)

    print(f'Wrote {total_plays} new play rows -> {plays_path}')
    print('\nDone.')


if __name__ == '__main__':
    main()
