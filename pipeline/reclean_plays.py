"""
Re-parse player name columns from raw_text for specific games without re-scraping.

Useful when parse_pbp.py logic is fixed and you want to patch plays.csv in-place.

Usage:
    python pipeline/reclean_plays.py --season 2025-26 --game-ids 20250913_vztg 20250906_6kr5
    python pipeline/reclean_plays.py --season 2025-26  # re-parse ALL games
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from parse_pbp import parse_play

NAME_COLS = ['passer', 'rusher', 'receiver', 'tackler_1', 'tackler_2', 'penalty_player']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--out', default='outputs')
    parser.add_argument('--game-ids', nargs='*')
    args = parser.parse_args()

    plays_path = os.path.join(args.out, args.season, 'plays.csv')

    with open(plays_path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    target_games = set(args.game_ids) if args.game_ids else None
    changed = 0

    for row in rows:
        if target_games and row['game_id'] not in target_games:
            continue
        raw = row.get('raw_text', '').strip()
        if not raw:
            continue

        parsed = parse_play(raw, row.get('offense', ''), row.get('defense', ''))

        for col in ['passer', 'rusher', 'receiver']:
            new = parsed.get(col) or ''
            if new and new != row.get(col, ''):
                row[col] = new
                changed += 1

        t1, t2 = parsed.get('tackler_1') or '', parsed.get('tackler_2') or ''
        if t1 and t1 != row.get('tackler_1', ''):
            row['tackler_1'] = t1
            changed += 1
        if t2 and t2 != row.get('tackler_2', ''):
            row['tackler_2'] = t2
            changed += 1

    with open(plays_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    scope = f'{len(target_games)} games' if target_games else 'all games'
    print(f'Recleaned {scope}: {changed} field updates -> {plays_path}')


if __name__ == '__main__':
    main()
