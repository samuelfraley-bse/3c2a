"""
Scrape a full 3C2A football season into three CSVs.

Usage:
    python scrape_season.py --season 2025-26 [--delay 1.5] [--out outputs/]

Outputs (under --out/{season}/):
    standings.csv   - one row per team
    schedule.csv    - one row per team-game pair
    plays.csv       - all play-by-play rows across all games
"""

import argparse
import csv
import os
import re
import time
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from parse_pbp import parse_html, FIELDS

BASE = 'https://3c2asports.org'

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


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def fetch(url: str, delay: float, session: requests.Session, retries: int = 4) -> str | None:
    time.sleep(delay)
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 459:
                wait = 60 * (2 ** attempt)  # 60s, 120s, 240s, 480s
                print(f'  [429] rate limited — waiting {wait}s then retrying ({attempt+1}/{retries})')
                time.sleep(wait)
                continue
            r.raise_for_status()
            print(f'  [OK]  {url}')
            return r.text
        except requests.HTTPError as e:
            print(f'  [ERR] {url} — {e}')
            return None
        except Exception as e:
            print(f'  [ERR] {url} — {e}')
            return None
    print(f'  [FAIL] {url} — gave up after {retries} retries')
    return None


# ---------------------------------------------------------------------------
# Phase 1: Standings
# ---------------------------------------------------------------------------

def scrape_standings(season: str, delay: float, session: requests.Session) -> list[dict]:
    url = f'{BASE}/sports/fball/{season}/standings'
    html = fetch(url, delay, session)
    if not html:
        raise SystemExit('Could not fetch standings page.')

    soup = BeautifulSoup(html, 'html.parser')
    teams = []

    for table in soup.select('table.table.bg-white'):
        # Conference name is in the first th with colspan
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
            # Layout: conf_gp, conf_wlt, conf_pct, overall_gp, overall_wlt, overall_pct, streak, last10
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

        # slug = stem of the .xml filename, e.g. "20251018_1561"
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

        # canonical game_id: slug + home_away team names
        def norm(name): return name.strip().upper().replace(' ', '_')
        if home_away == 'home':
            home_name, away_name = team['team_name'], opponent
        else:
            home_name, away_name = opponent, team['team_name']
        game_id = f"{slug}_{norm(home_name)}_{norm(away_name)}"

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
        schedule_home=game.get('schedule_home'),
        schedule_away=game.get('schedule_away'),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--delay', type=float, default=5.0)
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    os.makedirs(out_dir, exist_ok=True)

    standings_path = os.path.join(out_dir, 'standings.csv')
    schedule_path  = os.path.join(out_dir, 'schedule.csv')
    plays_path     = os.path.join(out_dir, 'plays.csv')

    session = requests.Session()
    session.headers['User-Agent'] = 'foothill-cv-research/1.0'

    # ── Phase 1: Standings ──────────────────────────────────────────────────
    print('\n=== Phase 1: Standings ===')
    teams = scrape_standings(args.season, args.delay, session)

    with open(standings_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STANDINGS_FIELDS)
        w.writeheader()
        w.writerows(teams)
    print(f'Wrote {len(teams)} rows -> {standings_path}')

    # ── Phase 2: Schedules ──────────────────────────────────────────────────
    print('\n=== Phase 2: Schedules ===')
    all_games = []
    seen_game_ids = set()

    for team in teams:
        print(f'  Schedule: {team["team_name"]}')
        games = scrape_schedule(team, args.season, args.delay, session)
        all_games.extend(games)
        for g in games:
            seen_game_ids.add(g['game_id'])

    with open(schedule_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=SCHEDULE_FIELDS)
        w.writeheader()
        w.writerows(all_games)
    print(f'Wrote {len(all_games)} rows ({len(seen_game_ids)} unique games) -> {schedule_path}')

    # ── Phase 3: Play-by-play ───────────────────────────────────────────────
    print('\n=== Phase 3: Play-by-Play ===')

    # Load already-scraped game_ids to support resuming
    existing_game_ids = set()
    if os.path.exists(plays_path):
        with open(plays_path, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                gid = row.get('game_id', '')
                if gid:
                    existing_game_ids.add(gid)
        print(f'  Resuming — {len(existing_game_ids)} games already in plays.csv')

    # Build unique game_id -> pbp_url map
    game_map = {}
    for g in all_games:
        if g['game_id'] not in game_map:
            game_map[g['game_id']] = g

    plays_file = open(plays_path, 'a', newline='', encoding='utf-8')
    writer = csv.DictWriter(plays_file, fieldnames=FIELDS, extrasaction='ignore')
    if not existing_game_ids:
        writer.writeheader()

    total_plays = 0
    for game_id, pbp_url in game_map.items():
        if game_id in existing_game_ids:
            print(f'  [SKIP] {game_id}')
            continue
        print(f'  PBP: {game_id}')
        plays = scrape_plays(game_map[game_id], args.delay, session)
        writer.writerows(plays)
        plays_file.flush()
        total_plays += len(plays)

    plays_file.close()
    print(f'Wrote {total_plays} new play rows -> {plays_path}')
    print('\nDone.')


if __name__ == '__main__':
    main()
