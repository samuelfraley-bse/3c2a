"""
Check a team's season totals from plays.csv against official box scores.

Prints one row per game with rushing and passing stats.
Sacks counted as rush attempts (NCAA convention).

Usage:
    python pipeline/03_check_season.py --season 2025-26
    python pipeline/03_check_season.py --season 2025-26 --team Reedley
"""

import argparse
import csv
import os
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', default='2025-26')
    ap.add_argument('--team', default='Foothill')
    ap.add_argument('--out', default='outputs')
    args = ap.parse_args()
    TEAM = args.team

    plays_path = os.path.join(args.out, args.season, 'plays.csv')
    games_path = os.path.join(args.out, args.season, 'games.csv')

    # game order and opponent lookup
    games_meta = {}
    game_order = []
    with open(games_path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if TEAM in (r['team_1'], r['team_2']):
                gid = r['game_id']
                opponent = r['team_2'] if r['team_1'] == TEAM else r['team_1']
                home_away = 'vs' if r['home_team_canonical'] == TEAM else '@'
                games_meta[gid] = {'opponent': opponent, 'ha': home_away, 'date': gid[:8]}
                game_order.append(gid)

    by_game = defaultdict(list)
    with open(plays_path, newline='', encoding='utf-8') as f:
        for p in csv.DictReader(f):
            if p['offense'] == TEAM:
                by_game[p['game_id']].append(p)

    header = f"{'Game':<28} {'Rush Att':>8} {'Rush Yds':>9} {'Rush TD':>7} {'Pass C/A':>9} {'Pass Yds':>9} {'Pass TD':>7} {'INT':>4} {'Sacks':>6}"
    print(header)
    print('-' * len(header))

    for gid in game_order:
        plays = by_game.get(gid, [])
        meta = games_meta[gid]

        rushes = [p for p in plays if p['play_type'] == 'rush']
        sacks  = [p for p in plays if p['play_type'] == 'pass' and p['is_sack'] == 'True']
        passes = [p for p in plays if p['play_type'] == 'pass' and p['is_sack'] != 'True']

        rush_att  = len(rushes) + len(sacks)
        rush_yds  = sum(int(p['yards_gained']) for p in rushes if p['yards_gained']) \
                  + sum(int(p['yards_gained']) for p in sacks  if p['yards_gained'])
        rush_td   = sum(1 for p in rushes if p['is_td'] == 'True')

        completions = [p for p in passes if p['pass_result'] in ('complete', 'td')]
        pass_att  = len(passes)
        pass_yds  = sum(int(p['yards_gained']) for p in completions if p['yards_gained'])
        pass_td   = sum(1 for p in passes if p['is_td'] == 'True')
        ints      = sum(1 for p in passes if p['pass_result'] == 'int')
        sack_count = len(sacks)

        date = f"{meta['date'][4:6]}/{meta['date'][6:8]}"
        label = f"{date} {meta['ha']} {meta['opponent'][:18]}"
        comp_att = f"{len(completions)}/{pass_att}"

        print(f"{label:<28} {rush_att:>8} {rush_yds:>9} {rush_td:>7} {comp_att:>9} {pass_yds:>9} {pass_td:>7} {ints:>4} {sack_count:>6}")

    # Season totals
    all_plays = [p for plays in by_game.values() for p in plays]
    rushes_all = [p for p in all_plays if p['play_type'] == 'rush']
    sacks_all   = [p for p in all_plays if p['play_type'] == 'pass' and p['is_sack'] == 'True']
    passes_all  = [p for p in all_plays if p['play_type'] == 'pass' and p['is_sack'] != 'True']
    comps_all   = [p for p in passes_all if p['pass_result'] in ('complete', 'td')]

    tot_rush_att = len(rushes_all) + len(sacks_all)
    tot_rush_yds = sum(int(p['yards_gained']) for p in rushes_all + sacks_all if p['yards_gained'])
    tot_rush_td  = sum(1 for p in rushes_all if p['is_td'] == 'True')
    tot_pass_att = len(passes_all)
    tot_pass_yds = sum(int(p['yards_gained']) for p in comps_all if p['yards_gained'])
    tot_pass_td  = sum(1 for p in passes_all if p['is_td'] == 'True')
    tot_ints     = sum(1 for p in passes_all if p['pass_result'] == 'int')
    tot_comp_att = f"{len(comps_all)}/{tot_pass_att}"

    print('-' * len(header))
    label = 'SEASON TOTAL'
    print(f"{label:<28} {tot_rush_att:>8} {tot_rush_yds:>9} {tot_rush_td:>7} {tot_comp_att:>9} {tot_pass_yds:>9} {tot_pass_td:>7} {tot_ints:>4}")


if __name__ == '__main__':
    main()
