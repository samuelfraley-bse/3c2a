"""
Scrape player rosters from PrestoSports team sites and write players.csv.

Usage:
    python pipeline/07_scrape_player_rosters.py --season 2025-26 [--delay 2.0] [--out outputs/] [--team Foothill]
"""

import argparse
import csv
import os
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_SEASON = '2025-26'
SKIP_NOTES = {'non-presto', 'pdf-only', ''}

PLAYER_FIELDS = [
    'season', 'team_name', 'player_id', 'jersey', 'player_name',
    'pos', 'height', 'weight', 'hometown', 'headshot_url',
]


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


def parse_roster_html(html: str, base_url: str, team_name: str, season: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    parsed_base = urlparse(base_url)
    site_root = f"{parsed_base.scheme}://{parsed_base.netloc}"

    rows = []
    for tr in soup.select('tr'):
        name_th = tr.select_one('th.name a') or tr.select_one('th[scope="row"] a')
        if not name_th:
            continue

        href = name_th.get('href', '')
        player_id = href.rstrip('/').split('_')[-1] if href else ''

        player_name = ' '.join(name_th.get_text(' ').split())

        num_td = tr.select_one('td.number')
        jersey = num_td.get_text(strip=True) if num_td else ''

        labeled = {}
        for td in tr.find_all('td'):
            label_el = td.find('span', class_='label')
            if label_el:
                key = label_el.get_text(strip=True).rstrip(':').strip()
                val = td.get_text(strip=True)
                label_text = label_el.get_text(strip=True)
                val = val[len(label_text):].strip()
                labeled[key] = val

        pos = labeled.get('Pos.', '')
        height = labeled.get('Ht.', '').replace('&quot;', '"')
        weight = labeled.get('Wt.', '')

        hometown = (
            labeled.get('Hometown')
            or labeled.get('High School/HS City', '').split('/')[-1].strip()
            or labeled.get('High School', '')
        )

        img = tr.select_one('img.headshot')
        headshot_url = ''
        if img:
            src = img.get('data-src', '')
            if src:
                if src.startswith('/'):
                    src = site_root + src
                headshot_url = src.split('?')[0]

        rows.append({
            'season': season,
            'team_name': team_name,
            'player_id': player_id,
            'jersey': jersey,
            'player_name': player_name,
            'pos': pos,
            'height': height,
            'weight': weight,
            'hometown': hometown,
            'headshot_url': headshot_url,
        })

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default=DEFAULT_SEASON)
    parser.add_argument('--delay', type=float, default=2.0)
    parser.add_argument('--out', default='outputs')
    parser.add_argument('--team', default=None, help='Scrape only this team name (for testing)')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    roster_urls_path = os.path.join(out_dir, 'roster_urls.csv')
    players_path = os.path.join(out_dir, 'players.csv')

    with open(roster_urls_path, newline='', encoding='utf-8') as f:
        roster_urls = list(csv.DictReader(f))

    if args.team:
        roster_urls = [r for r in roster_urls if r['team_name'].lower() == args.team.lower()]
        if not roster_urls:
            print(f'No team matching "{args.team}" found in roster_urls.csv')
            return

    session = requests.Session()
    session.headers['User-Agent'] = 'foothill-cv-research/1.0'

    all_players = []
    skipped = []

    for row in roster_urls:
        team_name = row['team_name']
        url = row['roster_url']
        notes = row['notes']

        if notes in SKIP_NOTES:
            print(f'  [SKIP] {team_name} ({notes})')
            skipped.append(team_name)
            continue

        print(f'  Fetching {team_name}')
        html = fetch(url, args.delay, session)
        if not html:
            print(f'  [WARN] No data for {team_name}')
            continue

        players = parse_roster_html(html, url, team_name, args.season)
        if not players:
            print(f'  [WARN] Parsed 0 players for {team_name}')
        else:
            print(f'  [OK]   {team_name}: {len(players)} players')
        all_players.extend(players)

    with open(players_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=PLAYER_FIELDS)
        w.writeheader()
        w.writerows(all_players)

    print(f'\nWrote {len(all_players)} players across {len(roster_urls) - len(skipped)} teams → {players_path}')
    if skipped:
        print(f'Skipped ({len(skipped)}): {", ".join(skipped)}')


if __name__ == '__main__':
    main()
