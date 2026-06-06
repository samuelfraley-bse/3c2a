"""
Probe unverified roster URLs in roster_urls.csv and update their notes in-place.

Usage:
    python pipeline/find_prestosports_rosters.py --season 2025-26 [--delay 1.0] [--out outputs/]
"""

import argparse
import csv
import os
import time

import requests

DEFAULT_SEASON = '2025-26'


def check_url(url: str, session: requests.Session) -> bool:
    try:
        r = session.head(url, timeout=15, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default=DEFAULT_SEASON)
    parser.add_argument('--delay', type=float, default=1.0)
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    roster_urls_path = os.path.join(args.out, args.season, 'roster_urls.csv')
    with open(roster_urls_path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    session = requests.Session()
    session.headers['User-Agent'] = 'foothill-cv-research/1.0'

    to_check = [r for r in rows if r['notes'] == 'presto-unverified']
    print(f'Checking {len(to_check)} unverified URLs...\n')

    for row in to_check:
        exists = check_url(row['roster_url'], session)
        if exists:
            row['notes'] = 'presto'
            print(f'  [OK]   {row["team_name"]:30s}  {row["roster_url"]}')
        else:
            row['notes'] = 'presto-dead'
            print(f'  [DEAD] {row["team_name"]:30s}  {row["roster_url"]}')
        time.sleep(args.delay)

    with open(roster_urls_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['team_name', 'roster_url', 'notes'])
        w.writeheader()
        w.writerows(rows)

    confirmed = sum(1 for r in rows if r['notes'] == 'presto')
    dead = sum(1 for r in rows if r['notes'] == 'presto-dead')
    print(f'\nDone. {confirmed} confirmed presto, {dead} dead guesses.')
    if dead:
        print('\nDead (need manual lookup):')
        for r in rows:
            if r['notes'] == 'presto-dead':
                print(f'  {r["team_name"]}')


if __name__ == '__main__':
    main()
