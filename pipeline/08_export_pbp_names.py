"""
Export unique player names from plays.csv with their roles, for name normalization.

Output: outputs/{season}/pbp_names.csv
    team, role, pbp_name, canonical_name, position, flagged, review_flag

canonical_name and position are left blank — to be filled by LLM or manually.
flagged is set to 'no_roster' for teams with no participation data.

Primary name source: participation.csv (per-game rosters, full coverage).
Supplementary source: players.csv (for position field only).

Usage:
    python pipeline/08_export_pbp_names.py --season 2025-26
"""

import argparse
import csv
import os
from collections import defaultdict

FIELDS = ['team', 'role', 'pbp_name', 'canonical_name', 'position', 'flagged', 'review_flag']

ROLE_COLUMNS = [
    ('passer', 'offense'),
    ('rusher', 'offense'),
    ('receiver', 'offense'),
    ('tackler_1', 'defense'),
    ('tackler_2', 'defense'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    plays_path = os.path.join(out_dir, 'plays.csv')
    participation_path = os.path.join(out_dir, 'participation.csv')
    players_path = os.path.join(out_dir, 'players.csv')
    out_path = os.path.join(out_dir, 'pbp_names.csv')

    # Teams with participation data (primary source)
    teams_with_participation: set[str] = set()
    if os.path.exists(participation_path):
        with open(participation_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                teams_with_participation.add(row['team_name'])
    else:
        print(f'[WARN] {participation_path} not found — falling back to players.csv for coverage')

    # Fall back to players.csv for coverage if participation not available
    teams_with_roster: set[str] = set()
    if os.path.exists(players_path):
        with open(players_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                teams_with_roster.add(row['team_name'])

    teams_with_data = teams_with_participation or teams_with_roster

    # Collect unique (team, role, pbp_name) — role = most common role seen for that name/team
    seen: dict[tuple[str, str], set[str]] = defaultdict(set)  # (team, pbp_name) -> set of roles
    with open(plays_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            for col, side in ROLE_COLUMNS:
                name = row.get(col, '').strip()
                team = row.get(side, '').strip()
                if name and team:
                    role = 'defender' if col.startswith('tackler') else col
                    seen[(team, name)].add(role)

    # Build output rows, sorted by team then name
    rows = []
    for (team, pbp_name), roles in sorted(seen.items()):
        role = '/'.join(sorted(roles))
        rows.append({
            'team': team,
            'role': role,
            'pbp_name': pbp_name,
            'canonical_name': '',
            'position': '',
            'flagged': '' if team in teams_with_data else 'no_roster',
            'review_flag': '',
        })

    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    flagged = sum(1 for r in rows if r['flagged'])
    source = 'participation' if teams_with_participation else 'players roster'
    print(f'Wrote {len(rows)} unique names across {len({r["team"] for r in rows})} teams -> {out_path}')
    print(f'  {len(rows) - flagged} with {source} data, {flagged} flagged (no_roster)')


if __name__ == '__main__':
    main()
