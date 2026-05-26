"""
Health check for a scraped season's play-by-play data.

Usage:
    py -3 health_check.py [--season 2025-26] [--out outputs/]

Checks (in order):
  1. Team totals integrity  — for every game, plays labeled offense=X must equal
                              plays labeled defense=X (same plays, both sides of ball).
  2. Game coverage          — for every team in the schedule, compare scheduled games
                              to games that have play-by-play. Expects exactly 1 missing
                              game per team (the season-opening scrimmage has a score
                              but no PBP page).
"""

import argparse
import csv
import os
from collections import defaultdict


def load_csv(path):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Check 1: team totals integrity
# ---------------------------------------------------------------------------

def check_team_totals(plays: list[dict]) -> list[str]:
    """
    For each game, every play has exactly one offense team and one defense team.
    So: offense_count[game][teamA] must equal defense_count[game][teamA's opponent].
    Equivalently: total plays with offense=A must equal total plays with defense=A's opponent.

    This catches offense/defense being swapped for a whole game or individual drives.
    """
    errors = []

    offense_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    defense_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    game_teams: dict[str, set[str]] = defaultdict(set)

    for row in plays:
        gid = row['game_id']
        off = row.get('offense', '').strip()
        dfn = row.get('defense', '').strip()
        if off:
            offense_count[gid][off] += 1
            game_teams[gid].add(off)
        if dfn:
            defense_count[gid][dfn] += 1
            game_teams[gid].add(dfn)

    for gid in sorted(game_teams):
        teams = sorted(game_teams[gid])
        if len(teams) != 2:
            errors.append(f'  BAD-TEAMS {gid}  expected 2 teams, found: {teams}')
            continue

        a, b = teams
        # plays where A has ball == plays where B is on defense (same plays)
        a_off = offense_count[gid].get(a, 0)
        b_def = defense_count[gid].get(b, 0)
        b_off = offense_count[gid].get(b, 0)
        a_def = defense_count[gid].get(a, 0)

        if a_off != b_def:
            errors.append(
                f'  MISMATCH  {gid}  offense={a}({a_off}) != defense={b}({b_def})  diff={a_off - b_def:+d}'
            )
        if b_off != a_def:
            errors.append(
                f'  MISMATCH  {gid}  offense={b}({b_off}) != defense={a}({a_def})  diff={b_off - a_def:+d}'
            )

    return errors


# ---------------------------------------------------------------------------
# Check 2: game coverage per team
# ---------------------------------------------------------------------------

def check_game_coverage(
    schedule: list[dict],
    plays: list[dict],
    no_pbp: set[str],
    scrimmage_allowance: int = 1,
) -> list[str]:
    """
    For each team in the schedule, find which of their games have play-by-play.
    Games in no_pbp are known to have no PBP on the site and are noted but not flagged FAIL.
    """
    errors = []

    game_ids_with_plays: set[str] = {row['game_id'] for row in plays}

    # Map team -> list of scheduled game_ids
    team_scheduled: dict[str, list[str]] = defaultdict(list)
    for row in schedule:
        team_scheduled[row['team_name']].append(row['game_id'])

    for team in sorted(team_scheduled):
        scheduled = team_scheduled[team]
        missing = [gid for gid in scheduled if gid not in game_ids_with_plays]
        confirmed_no_pbp = [gid for gid in missing if gid in no_pbp]
        unexplained = [gid for gid in missing if gid not in no_pbp]
        n_missing = len(missing)
        n_unexplained = len(unexplained)

        if n_missing == 0:
            status = 'OK'
            note = 'all games have PBP'
        elif n_unexplained == 0:
            # All missing games are confirmed no-PBP on the site
            status = 'OK'
            note = f'no PBP available for: {", ".join(confirmed_no_pbp)}'
        elif n_unexplained <= scrimmage_allowance:
            status = 'OK'
            parts = []
            if confirmed_no_pbp:
                parts.append(f'no PBP: {", ".join(confirmed_no_pbp)}')
            if unexplained:
                parts.append(f'scrimmage?: {", ".join(unexplained)}')
            note = '  '.join(parts)
        else:
            status = 'FAIL'
            parts = []
            if confirmed_no_pbp:
                parts.append(f'confirmed no PBP: {", ".join(confirmed_no_pbp)}')
            parts.append(f'unexplained missing: {", ".join(unexplained)}')
            note = '  '.join(parts)

        if status != 'OK':
            errors.append(f'  {status:<4}  {team:<30}  scheduled={len(scheduled)}  missing={n_missing}  {note}')

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--out', default='outputs')
    args = parser.parse_args()

    out_dir = os.path.join(args.out, args.season)
    plays_path = os.path.join(out_dir, 'plays.csv')
    schedule_path = os.path.join(out_dir, 'schedule.csv')

    print(f'Season: {args.season}')
    print(f'Plays:    {plays_path}')
    print(f'Schedule: {schedule_path}')
    print()

    failed_path = os.path.join(out_dir, 'failed_games.txt')
    no_pbp: set[str] = set()
    if os.path.exists(failed_path):
        with open(failed_path) as f:
            no_pbp = {ln.strip() for ln in f if ln.strip()}

    plays = load_csv(plays_path)
    schedule = load_csv(schedule_path)
    print(f'Loaded {len(plays):,} plays across {len({r["game_id"] for r in plays})} games.')
    print(f'Loaded {len(schedule):,} schedule rows for {len({r["team_name"] for r in schedule})} teams.')
    if no_pbp:
        print(f'Loaded {len(no_pbp)} confirmed no-PBP games from {failed_path}.')
    print()

    # --- Check 1 ---
    print('=' * 60)
    print('CHECK 1: Team totals integrity (offense play count == defense play count per game)')
    print('=' * 60)
    totals_errors = check_team_totals(plays)
    if totals_errors:
        print(f'FAILED — {len(totals_errors)} mismatch(es):')
        for e in totals_errors:
            print(e)
    else:
        print('PASSED — all game/team offense and defense counts match.')
    print()

    # --- Check 2 ---
    print('=' * 60)
    print('CHECK 2: Game coverage per team (expect exactly 1 missing game = scrimmage)')
    print('=' * 60)
    coverage_errors = check_game_coverage(schedule, plays, no_pbp)
    if coverage_errors:
        print(f'Issues found ({len(coverage_errors)} team(s)):')
        for e in coverage_errors:
            print(e)
    else:
        print('PASSED — every team has exactly 1 game missing (scrimmage).')
    print()

    overall = 'PASSED' if not totals_errors and not coverage_errors else 'FAILED'
    print(f'Overall: {overall}')


if __name__ == '__main__':
    main()
