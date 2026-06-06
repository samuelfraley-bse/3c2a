"""
Apply player_crosswalk.csv to plays.csv, normalizing player names in-place.

Usage:
    python pipeline/06_apply_player_crosswalk.py --season 2025-26 [--out outputs/]

Run 04_scrape_rosters.py and 05_build_player_crosswalk.py first, and review
player_crosswalk.csv before running this script.
"""

import argparse
import csv
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    crosswalk_path = os.path.join(out_dir, 'player_crosswalk.csv')
    plays_path = os.path.join(out_dir, 'plays.csv')

    # Load crosswalk: {(team_name, pbp_name): canonical_name} — only entries that actually change
    crosswalk: dict[tuple[str, str], str] = {}
    with open(crosswalk_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['pbp_name'] != row['canonical_name']:
                crosswalk[(row['team_name'], row['pbp_name'])] = row['canonical_name']

    print(f'Loaded {len(crosswalk)} name remappings')

    with open(plays_path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

    changes = 0
    for row in rows:
        offense = row.get('offense', '')
        defense = row.get('defense', '')

        for col, side in [('ball_carrier', offense), ('targeted_receiver', offense),
                          ('penalty_player', offense), ('tackler_1', defense), ('tackler_2', defense)]:
            name = row.get(col, '')
            if name and (side, name) in crosswalk:
                row[col] = crosswalk[(side, name)]
                changes += 1

    with open(plays_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f'Applied {changes} name changes across {len(rows)} plays → {plays_path}')


if __name__ == '__main__':
    main()
