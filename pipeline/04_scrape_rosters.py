"""
Scrape per-team player rosters from 3C2A and write rosters.csv.

Usage:
    python pipeline/04_scrape_rosters.py --season 2025-26 [--delay 3.0] [--out outputs/]
"""

import argparse
import csv
import os
import re
import time

import requests

BASE = 'https://3c2asports.org'
DEFAULT_SEASON = '2025-26'

ROSTER_FIELDS = ['season', 'team_name', 'team_id', 'jersey', 'player_name']


def fetch(url: str, delay: float, session: requests.Session, retries: int = 6) -> str | None:
    time.sleep(delay)
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=60)
            if r.status_code in (429, 202) or not r.text.strip():
                wait = 60 * (2 ** attempt)
                reason = '429 rate limited' if r.status_code == 429 else f'{r.status_code} empty'
                print(f'  [{reason}] waiting {wait}s then retrying ({attempt+1}/{retries})')
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.text
        except requests.HTTPError as e:
            print(f'  [ERR] {url} - {e}')
            return None
        except Exception as e:
            wait = 15 * (2 ** attempt)
            print(f'  [ERR] {url} - {e} (attempt {attempt+1}/{retries}, retrying in {wait}s)')
            time.sleep(wait)
    print(f'  [FAIL] {url} - gave up after {retries} retries')
    return None


def parse_roster_line(line: str) -> tuple[str | None, str | None]:
    """Parse a single roster line into (jersey, player_name).

    Jersey can be digits, RS (redshirt), or TM (team placeholder).
    Trailing code is 6 digits + 2 chars (letters, digits, or dash).
    Skip the TEAM placeholder line.
    """
    m = re.match(r'^(\d+|RS|TM)\s*(.+?)\s*[0-9]{6}[A-Za-z0-9-]{2}$', line.strip())
    if m:
        jersey = m.group(1).strip()
        name = m.group(2).strip()
        if name.upper() == 'TEAM':
            return None, None
        return jersey, name
    return None, None


def scrape_team_roster(team_name: str, team_id: str, season: str,
                       delay: float, session: requests.Session) -> list[dict]:
    url = f'{BASE}/sports/fball/{season}/Conference/Overall/players?teamId={team_id}&view=ext'
    print(f'  Fetching {team_name} ({team_id})')
    text = fetch(url, delay, session)
    if not text:
        print(f'  [WARN] No data for {team_name}')
        return []

    rows = []
    for line in text.splitlines():
        jersey, name = parse_roster_line(line)
        if name:
            rows.append({
                'season': season,
                'team_name': team_name,
                'team_id': team_id,
                'jersey': jersey,
                'player_name': name,
            })

    if not rows:
        print(f'  [WARN] Parsed 0 players for {team_name}')
    else:
        print(f'  [OK]  {team_name}: {len(rows)} players')
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default=DEFAULT_SEASON)
    parser.add_argument('--delay', type=float, default=3.0)
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    standings_path = os.path.join(out_dir, 'standings.csv')
    rosters_path = os.path.join(out_dir, 'rosters.csv')

    with open(standings_path, newline='', encoding='utf-8') as f:
        standings = list(csv.DictReader(f))

    # Deduplicate by team_id
    seen = set()
    teams = []
    for row in standings:
        if row['team_id'] not in seen:
            seen.add(row['team_id'])
            teams.append((row['team_name'], row['team_id']))

    print(f'Scraping rosters for {len(teams)} teams (season {args.season})')

    session = requests.Session()
    session.headers['User-Agent'] = 'foothill-cv-research/1.0'

    all_rows = []
    for team_name, team_id in teams:
        all_rows.extend(scrape_team_roster(team_name, team_id, args.season, args.delay, session))

    with open(rosters_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=ROSTER_FIELDS)
        w.writeheader()
        w.writerows(all_rows)

    print(f'\nWrote {len(all_rows)} players across {len(teams)} teams → {rosters_path}')


if __name__ == '__main__':
    main()
