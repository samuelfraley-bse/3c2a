"""
Build a player name crosswalk by clustering name variants within each team.

Approach: roster-independent intra-team clustering. For each team, collect all
unique names from plays.csv, then fuzzy-cluster names that look like variants of
the same person. The longest/most-complete form in each cluster becomes canonical.

Usage:
    python pipeline/05_build_player_crosswalk.py --season 2025-26 [--out outputs/]

Output: outputs/{season}/player_crosswalk.csv
    team_name, pbp_name, canonical_name, match_score, source

Review this file before running 06_apply_player_crosswalk.py.
Rows where pbp_name == canonical_name are identity mappings (no change needed).
"""

import argparse
import csv
import difflib
import os
from collections import defaultdict

CROSSWALK_FIELDS = ['team_name', 'pbp_name', 'canonical_name', 'match_score', 'source']
THRESHOLD = 0.82

# Columns in plays.csv that contain player names, and which team side they belong to
PLAYER_COLUMNS = [
    ('passer', 'offense'),
    ('rusher', 'offense'),
    ('receiver', 'offense'),
    ('tackler_1', 'defense'),
    ('tackler_2', 'defense'),
    # penalty_player handled separately — attributed to penalty_team, not always offense
]


def similarity(a: str, b: str) -> float:
    """Fuzzy similarity between two names, boosted for prefix matches (handles truncation)."""
    a_l, b_l = a.lower(), b.lower()
    if a_l == b_l:
        return 1.0
    # Prefix match: one is a truncation of the other
    if a_l.startswith(b_l) or b_l.startswith(a_l):
        shorter = min(len(a), len(b))
        longer = max(len(a), len(b))
        return shorter / longer
    return difflib.SequenceMatcher(None, a_l, b_l).ratio()


def cluster_names(names: list[str]) -> dict[str, str]:
    """
    Cluster name variants within a team. Returns {pbp_name: canonical_name}.
    Canonical = longest name in the cluster (most complete form).
    """
    names = sorted(set(names))
    # Union-find
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if similarity(a, b) >= THRESHOLD:
                union(a, b)

    # Group by cluster root
    clusters: dict[str, list[str]] = defaultdict(list)
    for name in names:
        clusters[find(name)].append(name)

    # Canonical = longest name in cluster
    mapping = {}
    for members in clusters.values():
        canonical = max(members, key=len)
        for name in members:
            mapping[name] = canonical

    return mapping


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    plays_path = os.path.join(out_dir, 'plays.csv')
    crosswalk_path = os.path.join(out_dir, 'player_crosswalk.csv')

    # Collect unique (team, pbp_name) pairs from plays.csv
    pbp_names: dict[str, set[str]] = defaultdict(set)
    with open(plays_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            for col, side in PLAYER_COLUMNS:
                name = row.get(col, '').strip()
                team = row.get(side, '').strip()
                if name and team:
                    pbp_names[team].add(name)
            # penalty_player: attribute to the team that committed the penalty
            pen_name = row.get('penalty_player', '').strip()
            pen_team_token = row.get('penalty_team', '').strip().upper()
            offense = row.get('offense', '').strip()
            defense = row.get('defense', '').strip()
            if pen_name and pen_team_token:
                # penalty_team is an uppercase token (e.g. "CERRITOS", "MT. SAN")
                # match it against offense/defense by checking if token appears in team name
                def _tok_match(tok, team):
                    return tok in team.upper().replace(' ', '').replace('.', '') or \
                           team.upper().replace(' ', '').replace('.', '') in tok
                if _tok_match(pen_team_token.replace(' ', '').replace('.', ''), offense):
                    pbp_names[offense].add(pen_name)
                elif defense and _tok_match(pen_team_token.replace(' ', '').replace('.', ''), defense):
                    pbp_names[defense].add(pen_name)

    print(f'Found player names across {len(pbp_names)} teams in plays.csv')

    crosswalk_rows = []
    total_remapped = 0

    for team in sorted(pbp_names):
        mapping = cluster_names(list(pbp_names[team]))
        for pbp_name in sorted(pbp_names[team]):
            canonical = mapping[pbp_name]
            score = round(similarity(pbp_name, canonical), 3) if canonical != pbp_name else 1.0
            if canonical != pbp_name:
                total_remapped += 1
            crosswalk_rows.append({
                'team_name': team,
                'pbp_name': pbp_name,
                'canonical_name': canonical,
                'match_score': score,
                'source': 'identity' if canonical == pbp_name else 'intra-team',
            })

    with open(crosswalk_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CROSSWALK_FIELDS)
        w.writeheader()
        w.writerows(crosswalk_rows)

    print(f'Wrote {len(crosswalk_rows)} entries ({total_remapped} remapped) → {crosswalk_path}')

    remapped = [r for r in crosswalk_rows if r['pbp_name'] != r['canonical_name']]
    if remapped:
        print(f'\nRemapped entries (review before applying):')
        for r in remapped[:50]:
            print(f"  {r['team_name']:<22} {r['pbp_name']:<30} → {r['canonical_name']}")
        if len(remapped) > 50:
            print(f'  ... and {len(remapped)-50} more (see {crosswalk_path})')


if __name__ == '__main__':
    main()
