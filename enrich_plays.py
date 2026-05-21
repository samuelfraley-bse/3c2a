"""
Add field_pos_side, yardline_raw, and yardline_100 to plays.csv.

Requires a completed crosswalk CSV with columns:
  game_id, prefix_a, prefix_b, canonical_a, canonical_b

Usage:
  python enrich_plays.py --season 2025-26
  python enrich_plays.py --season 2025-26 --crosswalk outputs/2025-26/prefix_crosswalk.csv
  python enrich_plays.py --plays outputs/2025-26/plays.csv \
                         --crosswalk outputs/2025-26/prefix_crosswalk.csv \
                         --out outputs/2025-26/plays_with_side.csv
"""

import re
import csv
import sys
import os
import argparse

RE_FIELD_POS = re.compile(r'^([A-Z][A-Z0-9\s\.\-]*?)(\d+)$')


def load_crosswalk(path: str) -> dict:
    crosswalk = {}
    missing = []
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            gid = row['game_id']
            ca, cb = row.get('canonical_a', '').strip(), row.get('canonical_b', '').strip()
            pa, pb = row.get('prefix_a', '').strip(), row.get('prefix_b', '').strip()
            if not ca or not cb:
                missing.append(gid)
                continue
            crosswalk[gid] = {}
            if pa:
                crosswalk[gid][pa] = ca
            if pb:
                crosswalk[gid][pb] = cb
    if missing:
        print(f'WARNING: {len(missing)} games in crosswalk have blank canonical_a/b — skipped: {missing[:5]}{"..." if len(missing)>5 else ""}', file=sys.stderr)
    return crosswalk


def field_pos_side(field_position: str, offense: str, game_map: dict) -> str | None:
    if not field_position or not offense or not game_map:
        return None
    m = RE_FIELD_POS.match(field_position.strip().upper())
    if not m:
        return None
    prefix = m.group(1).strip()
    owner = game_map.get(prefix)
    if owner is None:
        return None
    return 'own' if owner == offense else 'opponent'


def parse_yardline_raw(field_position: str) -> int | None:
    if not field_position:
        return None
    m = RE_FIELD_POS.match(field_position.strip().upper())
    if not m:
        return None
    return int(m.group(2))


def yardline_100(field_position: str, offense: str, game_map: dict) -> int | None:
    raw = parse_yardline_raw(field_position)
    side = field_pos_side(field_position, offense, game_map)
    if raw is None or side is None:
        return None
    return 100 - raw if side == 'own' else raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', default='2025-26')
    ap.add_argument('--out-dir', default='outputs')
    ap.add_argument('--plays', default=None, help='Override plays.csv path')
    ap.add_argument('--crosswalk', default=None, help='Override crosswalk path')
    ap.add_argument('--out', default=None, help='Override output path')
    args = ap.parse_args()

    season_dir = os.path.join(args.out_dir, args.season)
    plays_path = args.plays or os.path.join(season_dir, 'plays.csv')
    crosswalk_path = args.crosswalk or os.path.join(season_dir, 'prefix_crosswalk.csv')
    out_path = args.out or os.path.join(season_dir, 'plays_with_side.csv')

    crosswalk = load_crosswalk(crosswalk_path)
    print(f'Loaded crosswalk for {len(crosswalk)} games')

    with open(plays_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames + ['field_pos_side', 'yardline_raw', 'yardline_100']
        rows = list(reader)

    resolved = skipped = no_crosswalk = 0
    for row in rows:
        gid = row['game_id']
        game_map = crosswalk.get(gid)
        raw = parse_yardline_raw(row.get('field_position', ''))
        row['yardline_raw'] = '' if raw is None else raw
        if game_map is None:
            row['field_pos_side'] = ''
            row['yardline_100'] = ''
            no_crosswalk += 1
            continue
        side = field_pos_side(row.get('field_position', ''), row.get('offense', ''), game_map)
        row['field_pos_side'] = side or ''
        yl100 = yardline_100(row.get('field_position', ''), row.get('offense', ''), game_map)
        row['yardline_100'] = '' if yl100 is None else yl100
        if side:
            resolved += 1
        else:
            skipped += 1

    try:
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError:
        exists = os.path.exists(out_path)
        msg = f'Permission denied writing: {out_path}'
        if exists:
            msg += '\nThe file is probably open in another program. Close it and rerun.'
        print(msg, file=sys.stderr)
        sys.exit(1)

    total = len(rows)
    print(f'Total plays:       {total}')
    print(f'Resolved:          {resolved} ({resolved/total:.1%})')
    print(f'No field_position: {skipped}')
    print(f'No crosswalk:      {no_crosswalk}')
    print(f'Written to:        {out_path}')


if __name__ == '__main__':
    main()
