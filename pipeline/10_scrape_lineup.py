"""
Scrape per-team season stats pages to get canonical player names and slugs.

For each team and each position group, fetches the static (non-JS) stats page
and extracts player profile links: canonical name + player slug (contains ID).

Output: outputs/{season}/lineup.csv
    team_name, team_slug, player_name, player_slug, pos_group

player_slug e.g. 'drakemissamore7nfq' — stable player ID is the suffix after
the normalized name portion.

Requires manual/print-teams-dec-printer-decorator.html (save the printer-
decorator page from 3c2asports.org/sports/fball/{season}/teams?dec=printer-decorator).

Usage:
    python pipeline/10_scrape_lineup.py --season 2025-26
    python pipeline/10_scrape_lineup.py --season 2025-26 --request-delay 20 --team-delay 60
"""

import argparse
import csv
import os
import random
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = 'https://cccaa.prestosports.com'
POS_GROUPS = ['qb', 'rb', 'wr', 'd', 'k', 'p', 'kr']
RATE_LIMIT_CODES = {429, 459}
BLOCK_PHRASES = ['rate limited', 'bot traffic', 'temporarily', 'please wait']
FIELDS = ['team_name', 'team_slug', 'player_name', 'player_slug', 'pos_group']

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15',
]


def jitter(base: float, pct: float = 0.5) -> float:
    return base + random.uniform(0, base * pct)


def fetch(url: str, session: requests.Session, delay: float, retries: int = 8) -> str | None:
    time.sleep(jitter(delay))
    for attempt in range(retries):
        # Rotate user agent on each attempt
        session.headers['User-Agent'] = random.choice(USER_AGENTS)
        try:
            r = session.get(url, timeout=60)

            if r.status_code in RATE_LIMIT_CODES:
                wait = jitter(300 * (2 ** attempt))
                print(f'  [{r.status_code} rate limited] waiting {wait:.0f}s (attempt {attempt+1}/{retries})')
                time.sleep(wait)
                continue

            if not r.text.strip():
                wait = jitter(120 * (2 ** attempt))
                print(f'  [empty response] waiting {wait:.0f}s (attempt {attempt+1}/{retries})')
                time.sleep(wait)
                continue

            if any(p in r.text.lower() for p in BLOCK_PHRASES):
                wait = jitter(300 * (2 ** attempt))
                print(f'  [blocked] waiting {wait:.0f}s (attempt {attempt+1}/{retries})')
                time.sleep(wait)
                continue

            r.raise_for_status()
            return r.text

        except requests.HTTPError as e:
            print(f'  [ERR] {url} - {e}')
            return None
        except Exception as e:
            wait = jitter(60 * (2 ** attempt))
            print(f'  [ERR] {url} - {e} (attempt {attempt+1}/{retries}, retrying in {wait:.0f}s)')
            time.sleep(wait)

    print(f'  [FAIL] {url} - gave up after {retries} retries')
    return None


def get_team_slugs(teams_html_path: str, season: str) -> list[tuple[str, str]]:
    with open(teams_html_path, encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    prefix = f'/sports/fball/{season}/teams/'
    seen = {}
    for a in soup.find_all('a', href=lambda h: h and prefix in h):
        href = a['href'].split('#')[0].split('?')[0]
        slug = href.split(prefix)[-1].strip('/')
        name = a.get_text(strip=True)
        if slug and name and '/' not in slug and '@' not in slug and '.' not in slug:
            seen[slug] = name

    return sorted(seen.items(), key=lambda x: x[1])


def parse_players(html: str) -> list[tuple[str, str]]:
    """Return [(player_name, player_slug), ...] from a stats page."""
    soup = BeautifulSoup(html, 'html.parser')
    seen = {}
    for a in soup.find_all('a', href=lambda h: h and '/players/' in h):
        href = a['href'].split('?')[0].split('#')[0]
        slug = href.split('/players/')[-1].strip('/')
        name = ' '.join(a.get_text().split())
        if slug and name:
            seen[slug] = name
    return [(name, slug) for slug, name in seen.items()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--request-delay', type=float, default=15.0,
                        help='Base seconds between each page request (default 15)')
    parser.add_argument('--team-delay', type=float, default=45.0,
                        help='Extra seconds to pause between teams (default 45)')
    parser.add_argument('--out', default='outputs')
    parser.add_argument('--teams-html', default='manual/print-teams-dec-printer-decorator.html')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    out_path = os.path.join(out_dir, 'lineup.csv')

    teams = get_team_slugs(args.teams_html, args.season)
    print(f'Loaded {len(teams)} teams')
    print(f'Request delay: {args.request_delay}s (+up to {args.request_delay*0.5:.0f}s jitter)')
    print(f'Team pause:    {args.team_delay}s (+up to {args.team_delay*0.5:.0f}s jitter)')
    est = len(teams) * (len(POS_GROUPS) * args.request_delay * 1.25 + args.team_delay * 1.25) / 60
    print(f'Estimated time: ~{est:.0f} min')

    # Resume: track (team_slug, pos_group) already done
    done: set[tuple[str, str]] = set()
    if os.path.exists(out_path):
        with open(out_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                done.add((row['team_slug'], row['pos_group']))
        teams_done = len(set(s for s, _ in done))
        print(f'Resuming — {teams_done} teams already done ({len(done)} pos combos)')

    out_file = open(out_path, 'a' if done else 'w', newline='', encoding='utf-8')
    writer = csv.DictWriter(out_file, fieldnames=FIELDS)
    if not done:
        writer.writeheader()

    session = requests.Session()
    session.headers['User-Agent'] = random.choice(USER_AGENTS)

    total = 0
    try:
        for i, (team_slug, team_name) in enumerate(teams):
            remaining_pos = [p for p in POS_GROUPS if (team_slug, p) not in done]
            if not remaining_pos:
                print(f'  [SKIP]  {team_name}')
                continue

            print(f'  [{i+1}/{len(teams)}] {team_name} — {len(remaining_pos)} positions')
            team_rows = 0

            for pos in remaining_pos:
                url = f'{BASE_URL}/sports/fball/{args.season}/teams/{team_slug}?view=season&pos={pos}'
                html = fetch(url, session, args.request_delay)
                if not html:
                    print(f'    [WARN] {pos} failed')
                    continue

                players = parse_players(html)
                for player_name, player_slug in players:
                    writer.writerow({
                        'team_name': team_name,
                        'team_slug': team_slug,
                        'player_name': player_name,
                        'player_slug': player_slug,
                        'pos_group': pos,
                    })
                    team_rows += 1

                out_file.flush()
                print(f'    {pos}: {len(players)} players')

            total += team_rows
            print(f'    -> {team_rows} rows, pausing...')
            time.sleep(jitter(args.team_delay))

    finally:
        out_file.close()

    print(f'\nDone: {total} rows written -> {out_path}')


if __name__ == '__main__':
    main()
