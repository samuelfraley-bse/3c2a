"""
Build a player name crosswalk by fuzzy-matching play-by-play names against
canonical roster names within each team's scope.

Usage:
    python pipeline/05_build_player_crosswalk.py --season 2025-26 [--out outputs/]

Output: outputs/{season}/player_crosswalk.csv
    team_name, pbp_name, canonical_name, match_score

Review this file before running 06_apply_player_crosswalk.py.
Rows where pbp_name == canonical_name are identity mappings (no change needed).
"""

import argparse
import csv
import difflib
import os
from collections import defaultdict

CROSSWALK_FIELDS = ['team_name', 'pbp_name', 'canonical_name', 'match_score']

# Columns in plays.csv that contain player names, and which team side they belong to
PLAYER_COLUMNS = [
    ('ball_carrier', 'offense'),
    ('targeted_receiver', 'offense'),
    ('tackler_1', 'defense'),
    ('tackler_2', 'defense'),
    ('penalty_player', 'offense'),
]


def best_match(name: str, candidates: list[str], threshold: float = 0.82) -> tuple[str | None, float]:
    """Return (best_candidate, score) or (None, 0) if no match above threshold."""
    if not candidates or not name:
        return None, 0.0

    # Exact match
    if name in candidates:
        return name, 1.0

    best_candidate = None
    best_score = 0.0

    name_lower = name.lower()
    for candidate in candidates:
        # Prefix match: pbp name is a prefix of roster name (handles truncation like Kamaka→Kamakawiwo'ole)
        if candidate.lower().startswith(name_lower) or name_lower.startswith(candidate.lower()):
            score = len(min(name, candidate, key=len)) / len(max(name, candidate, key=len))
            if score > best_score:
                best_score = score
                best_candidate = candidate

        ratio = difflib.SequenceMatcher(None, name_lower, candidate.lower()).ratio()
        if ratio > best_score:
            best_score = ratio
            best_candidate = candidate

    if best_score >= threshold:
        return best_candidate, round(best_score, 3)
    return None, round(best_score, 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    rosters_path = os.path.join(out_dir, 'rosters.csv')
    plays_path = os.path.join(out_dir, 'plays.csv')
    crosswalk_path = os.path.join(out_dir, 'player_crosswalk.csv')

    # Load roster: {team_name: [canonical_names]}
    roster = defaultdict(list)
    with open(rosters_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            roster[row['team_name']].append(row['player_name'])

    print(f'Loaded rosters for {len(roster)} teams')

    # Collect unique (team, pbp_name) pairs from plays.csv
    pbp_names: dict[str, set[str]] = defaultdict(set)
    with open(plays_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            for col, side in PLAYER_COLUMNS:
                name = row.get(col, '').strip()
                team = row.get(side, '').strip()
                if name and team:
                    pbp_names[team].add(name)

    print(f'Found player names across {len(pbp_names)} teams in plays.csv')

    crosswalk_rows = []
    total_remapped = 0

    for team in sorted(pbp_names):
        candidates = roster.get(team, [])
        if not candidates:
            continue

        for pbp_name in sorted(pbp_names[team]):
            canonical, score = best_match(pbp_name, candidates)
            if canonical is None:
                canonical = pbp_name  # identity — no match found
                score = 0.0
            if canonical != pbp_name:
                total_remapped += 1
            crosswalk_rows.append({
                'team_name': team,
                'pbp_name': pbp_name,
                'canonical_name': canonical,
                'match_score': score,
            })

    with open(crosswalk_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CROSSWALK_FIELDS)
        w.writeheader()
        w.writerows(crosswalk_rows)

    print(f'Wrote {len(crosswalk_rows)} entries ({total_remapped} remapped) → {crosswalk_path}')

    # Print the remapped entries for review
    remapped = [r for r in crosswalk_rows if r['pbp_name'] != r['canonical_name']]
    if remapped:
        print(f'\nRemapped entries (review before applying):')
        for r in remapped[:40]:
            print(f"  {r['team_name']:<22} {r['pbp_name']:<28} → {r['canonical_name']:<28} ({r['match_score']})")
        if len(remapped) > 40:
            print(f'  ... and {len(remapped)-40} more (see {crosswalk_path})')


if __name__ == '__main__':
    main()
