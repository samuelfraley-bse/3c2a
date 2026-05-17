"""
Team-level summary stats from pbp_output.csv for box score verification.
Usage: python summary_stats.py pbp_output.csv
"""

import csv
import sys
from collections import defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else 'pbp_output.csv'
rows = list(csv.DictReader(open(path)))

teams = sorted({r['home_team'] for r in rows} | {r['away_team'] for r in rows})

def yards(r):
    v = r['yards_gained']
    return int(v) if v not in ('', 'None') else 0

def team_tokens_match(pen: str, team: str) -> bool:
    """True if penalty team token matches a team name, allowing truncation."""
    pen, team = pen.strip().upper(), team.strip().upper()
    if pen == team:
        return True
    # Allow truncated token (e.g. "SAN MATE" vs "SAN MATEO") — require ≥4 chars
    # to avoid "SAN" spuriously matching "SAN MATEO"
    if len(pen) >= 4 and team.startswith(pen):
        return True
    if len(team) >= 4 and pen.startswith(team):
        return True
    return False

def offense_penalized(r):
    """True when the offense committed the penalty — play result is nullified."""
    if r['is_penalty'] != 'True' or not r['penalty_team']:
        return False
    return team_tokens_match(r['penalty_team'], r['offense'])

stats = {t: {
    'pass_comp': 0, 'pass_att': 0, 'pass_yds': 0,
    'rush_att': 0, 'rush_yds': 0,
    'sack_n': 0, 'sack_yds': 0,
    'tds': 0,
    'penalty_n': 0, 'penalty_yds': 0,
} for t in teams}

for r in rows:
    off = r['offense']
    if off not in stats:
        continue
    s = stats[off]
    y = yards(r)
    is_td = r['is_td'] == 'True'

    off_penalty = offense_penalized(r)

    if r['play_type'] == 'pass':
        if r['is_sack'] == 'True':
            s['sack_n'] += 1
            s['sack_yds'] += y
            s['rush_att'] += 1
            s['rush_yds'] += y
        else:
            s['pass_att'] += 1
            if r['pass_result'] in ('complete', 'td'):
                s['pass_comp'] += 1
                # Zero yards when offense committed the penalty (play result negated)
                s['pass_yds'] += 0 if off_penalty else y
            if is_td:
                s['tds'] += 1

    elif r['play_type'] == 'rush':
        s['rush_att'] += 1
        s['rush_yds'] += y
        if is_td:
            s['tds'] += 1

    # Penalties — charge to the penalized team
    if r['is_penalty'] == 'True' and r['penalty_team'] and r['penalty_yards']:
        for t in teams:
            if team_tokens_match(r['penalty_team'], t):
                stats[t]['penalty_n'] += 1
                stats[t]['penalty_yds'] += int(r['penalty_yards'])
                break

t1, t2 = teams[0], teams[1]
s1, s2 = stats[t1], stats[t2]

w = 22
h1 = t1[:14]
h2 = t2[:14]
print()
print(f"{'':>{w}}  {h1:>15}  {h2:>15}")
print('-' * (w + 34))

def row(label, v1, v2):
    print(f"{label:>{w}}  {str(v1):>15}  {str(v2):>15}")

row('NET PASS YDS', s1['pass_yds'], s2['pass_yds'])
row('COMP-ATT', f"{s1['pass_comp']}-{s1['pass_att']}", f"{s2['pass_comp']}-{s2['pass_att']}")
row('DROPBACKS', s1['pass_att'] + s1['sack_n'], s2['pass_att'] + s2['sack_n'])
row('SACKED (N-YDS)', f"{s1['sack_n']}-{abs(s1['sack_yds'])}", f"{s2['sack_n']}-{abs(s2['sack_yds'])}")
row('NET RUSH YDS', s1['rush_yds'], s2['rush_yds'])
row('RUSH ATT', s1['rush_att'], s2['rush_att'])
row('TOTAL OFFENSE', s1['pass_yds'] + s1['rush_yds'], s2['pass_yds'] + s2['rush_yds'])
row('TDs', s1['tds'], s2['tds'])
row('PENALTIES (N-YDS)', f"{s1['penalty_n']}-{s1['penalty_yds']}", f"{s2['penalty_n']}-{s2['penalty_yds']}")
print()
