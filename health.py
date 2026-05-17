import csv
import os
import random
from collections import defaultdict

OUTPUTS_DIR = "outputs"

COLS = [
    "home_team", "away_team", "play_id", "drive_id", "drive_start_time",
    "quarter", "down", "distance", "field_position", "offense", "defense",
    "play_type", "ball_carrier", "targeted_receiver", "pass_result", "yards_gained",
    "is_td", "is_sack", "is_fumble", "fumble_recovered_by",
    "is_penalty", "penalty_team", "penalty_type", "penalty_player", "penalty_yards",
    "fg_result", "tackler_1", "tackler_2", "raw_text",
]

# Columns worth inspecting — high NA that shouldn't be
INSPECT = ["down", "distance", "field_position", "offense", "defense", "yards_gained"]
SAMPLE_N = 8

def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def main():
    seasons = sorted(
        d for d in os.listdir(OUTPUTS_DIR)
        if os.path.isdir(os.path.join(OUTPUTS_DIR, d))
    )

    for season in seasons:
        plays = load_csv(os.path.join(OUTPUTS_DIR, season, "plays.csv"))
        n = len(plays)
        missing = defaultdict(int)
        null_rows = defaultdict(list)

        for play in plays:
            for c in COLS:
                if not play.get(c):
                    missing[c] += 1
                    if c in INSPECT:
                        null_rows[c].append(play)

        print(f"\n{'='*70}")
        print(f"  Season: {season}   ({n} plays)")
        print(f"{'='*70}")
        print(f"\n  {'COLUMN':<22} {'MISSING':>8}  {'RATE':>7}")
        print(f"  {'-'*22} {'-'*8}  {'-'*7}")
        for c in COLS:
            m = missing[c]
            rate = f"{m/n*100:.1f}%" if n else "N/A"
            print(f"  {c:<22} {m:>8}  {rate:>7}")

        # Games where og:title parsing failed
        bad_title_games = sorted({r["game_id"] for r in plays if r.get("home_team") in ("HOME", "")})
        if bad_title_games:
            print(f"\n--- Games with failed og:title ({len(bad_title_games)}) ---")
            for gid in bad_title_games:
                print(f"  {gid}")

        # Games with any defense=null plays (drive header mismatch)
        defense_null_counts = defaultdict(int)
        for r in plays:
            if not r.get("defense"):
                defense_null_counts[r.get("game_id", "?")] += 1
        if defense_null_counts:
            print(f"\n--- Games with defense=null ({len(defense_null_counts)} games) ---")
            print(f"  {'GAME_ID':<45} {'NULL_PLAYS':>10}")
            print(f"  {'-'*45} {'-'*10}")
            for gid, cnt in sorted(defense_null_counts.items(), key=lambda x: -x[1]):
                print(f"  {gid:<45} {cnt:>10}")

        print(f"\n--- Sample NA rows ({SAMPLE_N} per column) ---")
        for c in INSPECT:
            rows = null_rows[c]
            if not rows:
                continue
            sample = random.sample(rows, min(SAMPLE_N, len(rows)))
            print(f"\n  [{c}]  ({len(rows)} total null)")
            for r in sample:
                game = r.get("game_id", "")[:30]
                play_type = r.get("play_type", "").ljust(12)
                offense = r.get("offense", "").ljust(20)
                raw = r.get("raw_text", "")[:80]
                print(f"    {game}  type={play_type}  off={offense}  | {raw}")

if __name__ == "__main__":
    main()
