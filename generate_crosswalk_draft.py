"""
Generate a per-game prefix crosswalk draft from plays.csv and games.csv.
Outputs one row per game with the two field-position prefixes and the two team names.
canonical_a and canonical_b are left blank for manual/AI fill.

Usage:
    python generate_crosswalk_draft.py --season 2025-26
    python generate_crosswalk_draft.py --season 2025-26 --out outputs/
"""

import argparse
import csv
import os
import re

RE_FIELD_POS = re.compile(r'^([A-Z][A-Z0-9\s\.\-]*?)\d+$')

FIELDS = ['game_id', 'prefix_a', 'prefix_b', 'canonical_a', 'canonical_b', 'team_1', 'team_2', 'note']


def extract_prefix(field_position: str) -> str | None:
    if not field_position:
        return None
    m = RE_FIELD_POS.match(field_position.strip().upper())
    if not m:
        return None
    return m.group(1).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', default='2025-26')
    ap.add_argument('--out', default='outputs')
    args = ap.parse_args()

    out_dir = os.path.join(args.out, args.season)
    plays_path = os.path.join(out_dir, 'plays.csv')
    games_path = os.path.join(out_dir, 'games.csv')
    draft_path = os.path.join(out_dir, 'prefix_crosswalk_draft.csv')

    games = {}
    with open(games_path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            games[r['game_id']] = r

    prefixes_by_game: dict[str, set] = {}
    with open(plays_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            gid = row.get('game_id', '').strip()
            fp = row.get('field_position', '').strip()
            if not gid or not fp:
                continue
            p = extract_prefix(fp)
            if p:
                prefixes_by_game.setdefault(gid, set()).add(p)

    rows = []
    skipped = 0
    for game_id, prefixes in sorted(prefixes_by_game.items()):
        g = games.get(game_id, {})
        team_1 = g.get('team_1', '')
        team_2 = g.get('team_2', '')

        prefix_list = sorted(prefixes)
        if len(prefix_list) == 0:
            skipped += 1
            continue
        elif len(prefix_list) == 1:
            prefix_a = prefix_list[0]
            prefix_b = f'(only one prefix found — {team_2} inferred)'
        elif len(prefix_list) == 2:
            prefix_a, prefix_b = prefix_list[0], prefix_list[1]
        else:
            prefix_a = prefix_list[0]
            prefix_b = prefix_list[1]
            note = f'WARNING: {len(prefix_list)} prefixes found: {prefix_list}'
            rows.append({
                'game_id': game_id,
                'prefix_a': prefix_a,
                'prefix_b': prefix_b,
                'canonical_a': '',
                'canonical_b': '',
                'team_1': team_1,
                'team_2': team_2,
                'note': note,
            })
            continue

        rows.append({
            'game_id': game_id,
            'prefix_a': prefix_a,
            'prefix_b': prefix_b,
            'canonical_a': '',
            'canonical_b': '',
            'team_1': team_1,
            'team_2': team_2,
            'note': '',
        })

    with open(draft_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f'Wrote {len(rows)} rows -> {draft_path}')
    if skipped:
        print(f'Skipped {skipped} games with no field_position prefixes')


if __name__ == '__main__':
    main()
