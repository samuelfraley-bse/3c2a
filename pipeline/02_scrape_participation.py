"""
Scrape participation pages for all games and write participation.csv.

For each game in games.csv, fetches ?view=participation and extracts
both the participants and did-not-participate lists for both teams.

Output: outputs/{season}/participation.csv
    game_id, team_name, jersey, player_name, participated

Usage:
    python pipeline/09_scrape_participation.py --season 2025-26 [--delay 1.0] [--out outputs/]
"""

import argparse
import csv
import os
import time

import requests
from bs4 import BeautifulSoup

FIELDS = ['game_id', 'team_name', 'jersey', 'player_name', 'participated']


RATE_LIMIT_CODES = {429, 459}
SERVER_ERROR_CODES = {500, 502, 503, 504, 520, 521, 522, 524}


def fetch(url: str, delay: float, session: requests.Session, retries: int = 8) -> str | None:
    time.sleep(delay)
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=60)
            if r.status_code in RATE_LIMIT_CODES or not r.text.strip():
                wait = 120 * (2 ** attempt)
                reason = f'{r.status_code} rate limited' if r.status_code in RATE_LIMIT_CODES else f'{r.status_code} empty'
                print(f'  [{reason}] waiting {wait}s then retrying ({attempt+1}/{retries})')
                time.sleep(wait)
                continue
            if r.status_code in SERVER_ERROR_CODES:
                wait = 30 * (2 ** attempt)
                print(f'  [{r.status_code} server error] waiting {wait}s then retrying ({attempt+1}/{retries})')
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.text
        except requests.HTTPError as e:
            print(f'  [ERR] {url} - {e}')
            return None
        except Exception as e:
            wait = 30 * (2 ** attempt)
            print(f'  [ERR] {url} - {e} (attempt {attempt+1}/{retries}, retrying in {wait}s)')
            time.sleep(wait)
    print(f'  [FAIL] {url} - gave up after {retries} retries')
    return None


def _parse_player_table(nested_table) -> list[tuple[str, str]]:
    """Return [(jersey, player_name), ...] from a nested player table."""
    results = []
    for tr in nested_table.find_all('tr')[1:]:
        cells = tr.find_all('td')
        if len(cells) < 2:
            continue
        jersey = cells[0].get_text(strip=True)
        player_name = cells[1].get_text(strip=True)
        if player_name and player_name.upper() != 'TEAM':
            results.append((jersey, player_name))
    return results


def parse_participation_html(html: str, game_id: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')

    # PARTICIPANTS and DID NOT PARTICIPATE are row groups within the same outer table.
    # Find all <tr> rows in that table and locate each section header by index.
    header_th = soup.find('th', string=lambda s: s and 'PARTICIPANTS' in s)
    if not header_th:
        return []
    t = header_th.parent
    while t and t.name != 'table':
        t = t.parent
    if not t:
        return []

    tbody = t.find('tbody')
    all_rows = (tbody if tbody else t).find_all('tr', recursive=False)
    if len(all_rows) < 3:
        all_rows = t.find_all('tr')

    # Index rows by section header
    section_starts = {}
    for i, tr in enumerate(all_rows):
        text = tr.get_text(strip=True)
        if 'PARTICIPANTS' == text:
            section_starts['PARTICIPANTS'] = i
        elif 'DID NOT PARTICIPATE' == text:
            section_starts['DID NOT PARTICIPATE'] = i

    rows = []
    for section, participated in [('PARTICIPANTS', True), ('DID NOT PARTICIPATE', False)]:
        start = section_starts.get(section)
        if start is None or start + 2 >= len(all_rows):
            continue

        team_names = [th.get_text(strip=True) for th in all_rows[start + 1].find_all('th')]
        data_tds = all_rows[start + 2].find_all('td', recursive=False) or all_rows[start + 2].find_all('td')

        for td, team_name in zip(data_tds, team_names):
            nested = td.find('table')
            if not nested:
                continue
            for jersey, player_name in _parse_player_table(nested):
                rows.append({
                    'game_id': game_id,
                    'team_name': team_name,
                    'jersey': jersey,
                    'player_name': player_name,
                    'participated': 'true' if participated else 'false',
                })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--delay', type=float, default=1.0)
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    games_path = os.path.join(out_dir, 'games.csv')
    out_path = os.path.join(out_dir, 'participation.csv')

    with open(games_path, newline='', encoding='utf-8') as f:
        games = list(csv.DictReader(f))

    # Load already-scraped game_ids so we can resume after an interruption
    done_ids: set[str] = set()
    file_exists = os.path.exists(out_path)
    if file_exists:
        with open(out_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                done_ids.add(row['game_id'])
        print(f'Resuming — {len(done_ids)} games already in {out_path}')

    session = requests.Session()
    session.headers['User-Agent'] = 'foothill-cv-research/1.0'

    # Append mode if resuming, write mode if starting fresh
    out_file = open(out_path, 'a', newline='', encoding='utf-8') if file_exists else open(out_path, 'w', newline='', encoding='utf-8')
    writer = csv.DictWriter(out_file, fieldnames=FIELDS)
    if not file_exists:
        writer.writeheader()

    ok = 0
    warn = 0
    try:
        for game in games:
            game_id = game['game_id']
            if game_id in done_ids:
                continue
            pbp_url = game.get('pbp_url', '')
            if not pbp_url:
                continue
            url = pbp_url.replace('?view=plays', '?view=participation')

            html = fetch(url, args.delay, session)
            if not html:
                print(f'  [WARN] No data for {game_id}')
                warn += 1
                continue

            rows = parse_participation_html(html, game_id)
            if not rows:
                print(f'  [WARN] Parsed 0 players for {game_id} ({url})')
                warn += 1
            else:
                teams = sorted(set(r['team_name'] for r in rows))
                print(f'  [OK]   {game_id}: {len(rows)} players ({", ".join(teams)})')
                ok += 1
            writer.writerows(rows)
            out_file.flush()
    finally:
        out_file.close()

    print(f'\nDone: {ok} new games scraped ({warn} warnings) -> {out_path}')


if __name__ == '__main__':
    main()
