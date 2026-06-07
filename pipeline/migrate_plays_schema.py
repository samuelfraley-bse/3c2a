"""
One-time migration: rename ball_carrier/targeted_receiver to passer/rusher/receiver.

Usage:
    python pipeline/migrate_plays_schema.py --season 2025-26
"""

import argparse
import csv
import os

from parse_pbp import FIELDS

PASS_TYPES = {'pass'}
CARRIER_TYPES = {'rush', 'kickoff', 'punt', 'field_goal', 'pat', 'two_point'}


def migrate(plays_path: str) -> None:
    with open(plays_path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    migrated = []
    for row in rows:
        play_type = row.get('play_type', '')
        ball_carrier = row.pop('ball_carrier', '') or ''
        targeted_receiver = row.pop('targeted_receiver', '') or ''

        if play_type in PASS_TYPES:
            row['passer'] = ball_carrier
            row['rusher'] = ''
            row['receiver'] = targeted_receiver
        else:
            row['passer'] = ''
            row['rusher'] = ball_carrier
            row['receiver'] = ''

        migrated.append(row)

    with open(plays_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(migrated)

    print(f'Migrated {len(migrated)} rows → {plays_path}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    plays_path = os.path.join(args.out, args.season, 'plays.csv')
    migrate(plays_path)


if __name__ == '__main__':
    main()
