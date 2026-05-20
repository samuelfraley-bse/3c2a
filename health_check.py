import argparse
import re
import sys
from pathlib import Path

import pandas as pd


DEFAULT_SEASONS = ["2024-25", "2025-26"]
OUTPUTS_DIR = Path("outputs")
FOOTHILL_PATTERN = "foothill"
GAME_SLUG_RE = re.compile(r"^(\d{8}_[A-Za-z0-9]+)")


def main() -> int:
    args = parse_args()
    seasons = [args.season] if args.season else DEFAULT_SEASONS

    overall_has_mismatch = False
    for season in seasons:
        season_has_mismatch = run_season_check(season)
        overall_has_mismatch = overall_has_mismatch or season_has_mismatch

    return 1 if overall_has_mismatch else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check play-by-play coverage against schedules and standings."
    )
    parser.add_argument(
        "--season",
        choices=DEFAULT_SEASONS,
        help="Run the health check for a single season.",
    )
    return parser.parse_args()


def run_season_check(season: str) -> bool:
    plays, schedule, standings, games = load_files(season)

    print(f"\n=== {season} Health Check ===\n")

    check_unique_teams(plays)
    plays_game_ids = check_total_games(plays)
    foothill_play_game_ids = check_foothill_games(plays)

    mismatch = False
    mismatch = check_canonical_games(games) or mismatch
    mismatch = check_against_schedule(plays_game_ids, schedule, games) or mismatch
    mismatch = check_foothill_count(foothill_play_game_ids, schedule, games) or mismatch
    mismatch = check_home_away_alignment(plays) or mismatch
    mismatch = check_against_standings(plays, schedule, standings, games) or mismatch
    mismatch = check_duplicate_play_rows(plays) or mismatch

    print_summary(mismatch)
    return mismatch


def load_files(season: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    season_dir = OUTPUTS_DIR / season
    plays = pd.read_csv(season_dir / "plays.csv", dtype=str, low_memory=False)
    schedule = pd.read_csv(season_dir / "schedule.csv", dtype=str, low_memory=False)
    standings = pd.read_csv(season_dir / "standings.csv", dtype=str, low_memory=False)
    games_path = season_dir / "games.csv"
    games = (
        pd.read_csv(games_path, dtype=str, low_memory=False)
        if games_path.exists()
        else None
    )
    plays = drop_embedded_header_rows(plays)
    plays["game_id"] = normalize_game_id_series(plays["game_id"])
    schedule["game_id"] = normalize_game_id_series(schedule["game_id"])
    if games is not None:
        games["game_id"] = normalize_game_id_series(games["game_id"])
    return plays, schedule, standings, games


def drop_embedded_header_rows(plays: pd.DataFrame) -> pd.DataFrame:
    header_like = (
        normalize_series(plays["game_id"]).eq("game_id")
        | normalize_series(plays["home_team"]).eq("home_team")
        | normalize_series(plays["away_team"]).eq("away_team")
    )
    return plays.loc[~header_like].copy()


def normalize_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def normalize_team_key(series: pd.Series) -> pd.Series:
    return normalize_series(series).str.casefold()


def normalize_game_id(value: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    match = GAME_SLUG_RE.match(text)
    return match.group(1) if match else text


def normalize_game_id_series(series: pd.Series) -> pd.Series:
    return normalize_series(series).map(normalize_game_id)


def sorted_game_ids(series: pd.Series) -> list[str]:
    values = normalize_series(series)
    return sorted(value for value in values.unique().tolist() if value)


def check_unique_teams(plays: pd.DataFrame) -> None:
    home_teams = normalize_series(plays["home_team"])
    away_teams = normalize_series(plays["away_team"])
    combined = pd.concat([home_teams, away_teams], ignore_index=True)
    non_empty = combined[combined != ""]

    unique_teams = sorted(non_empty.unique().tolist())
    team_counts = non_empty.value_counts()
    singletons = sorted(team_counts[team_counts == 1].index.tolist())

    print(f"[Teams] {len(unique_teams)} unique teams found: {unique_teams}")
    if singletons:
        print(f"[Teams] MISMATCH: {len(singletons)} team names appear only once: {singletons}")
    else:
        print("[Teams] No team names appear only once")


def check_total_games(plays: pd.DataFrame) -> set[str]:
    game_ids = set(sorted_game_ids(plays["game_id"]))
    print(f"[Games] {len(game_ids)} unique games in plays.csv")
    return game_ids


def check_canonical_games(games: pd.DataFrame | None) -> bool:
    if games is None or "pairing_status" not in games.columns:
        return False

    status_counts = normalize_series(games["pairing_status"]).value_counts().to_dict()
    total_games = len(games)
    paired_count = status_counts.get("paired", 0)
    other_counts = {k: v for k, v in status_counts.items() if k and k != "paired"}
    print(f"[Canonical games] {paired_count}/{total_games} paired in games.csv")
    if other_counts:
        print(f"[Canonical games] MISMATCH: non-paired statuses: {other_counts}")
        return True

    print("[Canonical games] All game rows are paired")
    return False


def check_foothill_games(plays: pd.DataFrame) -> set[str]:
    home_match = normalize_series(plays["home_team"]).str.contains(
        FOOTHILL_PATTERN, case=False, na=False
    )
    away_match = normalize_series(plays["away_team"]).str.contains(
        FOOTHILL_PATTERN, case=False, na=False
    )
    foothill_games = set(sorted_game_ids(plays.loc[home_match | away_match, "game_id"]))
    print(f"[Foothill] {len(foothill_games)} Foothill games: {sorted(foothill_games)}")
    return foothill_games


def get_expected_game_ids(schedule: pd.DataFrame, games: pd.DataFrame | None) -> set[str]:
    if games is not None and "game_id" in games.columns:
        return set(sorted_game_ids(games["game_id"]))
    return set(sorted_game_ids(schedule["game_id"]))


def check_against_schedule(
    plays_game_ids: set[str], schedule: pd.DataFrame, games: pd.DataFrame | None
) -> bool:
    schedule_game_ids = get_expected_game_ids(schedule, games)
    missing_from_plays = sorted(schedule_game_ids - plays_game_ids)
    missing_from_schedule = sorted(plays_game_ids - schedule_game_ids)
    matching = len(plays_game_ids & schedule_game_ids)

    print(
        f"[Schedule vs Plays] {len(missing_from_plays)} games in schedule missing from plays: "
        f"{missing_from_plays}"
    )
    print(
        f"                    {len(missing_from_schedule)} games in plays missing from schedule: "
        f"{missing_from_schedule}"
    )
    print(f"                    {matching} matching games")

    return bool(missing_from_plays or missing_from_schedule)


def check_foothill_count(
    foothill_play_game_ids: set[str], schedule: pd.DataFrame, games: pd.DataFrame | None
) -> bool:
    if games is not None and {"team_1", "team_2", "game_id"}.issubset(games.columns):
        team_1_match = normalize_series(games["team_1"]).str.contains(
            FOOTHILL_PATTERN, case=False, na=False
        )
        team_2_match = normalize_series(games["team_2"]).str.contains(
            FOOTHILL_PATTERN, case=False, na=False
        )
        foothill_schedule_game_ids = set(
            sorted_game_ids(games.loc[team_1_match | team_2_match, "game_id"])
        )
    else:
        foothill_schedule_mask = normalize_series(schedule["team_name"]).str.contains(
            FOOTHILL_PATTERN, case=False, na=False
        )
        foothill_schedule_game_ids = set(
            sorted_game_ids(schedule.loc[foothill_schedule_mask, "game_id"])
        )

    schedule_count = len(foothill_schedule_game_ids)
    plays_count = len(foothill_play_game_ids)
    status = "OK" if schedule_count == plays_count else "MISMATCH"

    print(
        f"[Foothill count] Schedule: {schedule_count} | Plays: {plays_count} | {status}"
    )
    return schedule_count != plays_count


def check_home_away_alignment(plays: pd.DataFrame) -> bool:
    cols = ["game_id", "home_team", "away_team", "schedule_home", "schedule_away"]
    game_rows = plays[cols].copy()
    for col in cols[1:]:
        game_rows[col] = normalize_series(game_rows[col])

    game_rows = game_rows.drop_duplicates()
    game_level = (
        game_rows.groupby("game_id", as_index=False)
        .agg(
            pbp_home=("home_team", "first"),
            pbp_away=("away_team", "first"),
            schedule_home=("schedule_home", "first"),
            schedule_away=("schedule_away", "first"),
            pbp_home_count=("home_team", "nunique"),
            pbp_away_count=("away_team", "nunique"),
            schedule_home_count=("schedule_home", "nunique"),
            schedule_away_count=("schedule_away", "nunique"),
        )
    )

    inconsistent_rows = game_level[
        (game_level["pbp_home_count"] > 1)
        | (game_level["pbp_away_count"] > 1)
        | (game_level["schedule_home_count"] > 1)
        | (game_level["schedule_away_count"] > 1)
    ]

    comparable = game_level[
        (game_level["pbp_home"] != "")
        & (game_level["pbp_away"] != "")
        & (game_level["schedule_home"] != "")
        & (game_level["schedule_away"] != "")
    ].copy()
    comparable["matches"] = (
        comparable["pbp_home"].eq(comparable["schedule_home"])
        & comparable["pbp_away"].eq(comparable["schedule_away"])
    )
    mismatches = comparable.loc[~comparable["matches"]]

    print(
        f"[Home/Away] {len(mismatches)} games where pbp home/away disagrees with schedule "
        f"home/away"
    )
    if not mismatches.empty:
        for row in mismatches.itertuples(index=False):
            print(
                f"  {row.game_id} | pbp: {row.pbp_home} vs {row.pbp_away} | "
                f"schedule: {row.schedule_home} vs {row.schedule_away}"
            )

    if not inconsistent_rows.empty:
        inconsistent_game_ids = sorted_game_ids(inconsistent_rows["game_id"])
        print(
            f"[Home/Away] MISMATCH: {len(inconsistent_game_ids)} games have multiple "
            f"home/away values within plays.csv: {inconsistent_game_ids}"
        )

    return (not mismatches.empty) or (not inconsistent_rows.empty)


def count_schedule_games_by_team(schedule: pd.DataFrame) -> dict[str, int]:
    schedule_clean = schedule.copy()
    schedule_clean["team_key"] = normalize_team_key(schedule_clean["team_name"])
    schedule_clean["game_id_clean"] = normalize_series(schedule_clean["game_id"])

    filtered = schedule_clean[
        (schedule_clean["team_key"] != "") & (schedule_clean["game_id_clean"] != "")
    ]
    grouped = filtered.groupby("team_key")["game_id_clean"].nunique()
    return grouped.to_dict()


def count_games_by_team(games: pd.DataFrame | None, schedule: pd.DataFrame) -> dict[str, int]:
    if games is not None and {"team_1", "team_2", "game_id"}.issubset(games.columns):
        home = games[["game_id", "team_1"]].rename(columns={"team_1": "team_name"})
        away = games[["game_id", "team_2"]].rename(columns={"team_2": "team_name"})
        team_games = pd.concat([home, away], ignore_index=True)
        team_games["team_key"] = normalize_team_key(team_games["team_name"])
        team_games["game_id_clean"] = normalize_series(team_games["game_id"])
        filtered = team_games[
            (team_games["team_key"] != "") & (team_games["game_id_clean"] != "")
        ]
        grouped = filtered.groupby("team_key")["game_id_clean"].nunique()
        return grouped.to_dict()

    return count_schedule_games_by_team(schedule)


def count_play_games_by_team(
    plays: pd.DataFrame, schedule: pd.DataFrame, games: pd.DataFrame | None
) -> dict[str, int]:
    # Attribute scraped games using canonical game rows keyed by slug when available.
    play_game_ids = set(sorted_game_ids(plays["game_id"]))
    if games is not None and {"team_1", "team_2", "game_id"}.issubset(games.columns):
        home = games[["game_id", "team_1"]].rename(columns={"team_1": "team_name"})
        away = games[["game_id", "team_2"]].rename(columns={"team_2": "team_name"})
        team_games = pd.concat([home, away], ignore_index=True)
        team_games["team_key"] = normalize_team_key(team_games["team_name"])
        team_games["game_id_clean"] = normalize_series(team_games["game_id"])
        filtered = team_games[
            (team_games["team_key"] != "")
            & (team_games["game_id_clean"] != "")
            & (team_games["game_id_clean"].isin(play_game_ids))
        ]
        grouped = filtered.groupby("team_key")["game_id_clean"].nunique()
        return grouped.to_dict()

    schedule_clean = schedule.copy()
    schedule_clean["team_key"] = normalize_team_key(schedule_clean["team_name"])
    schedule_clean["game_id_clean"] = normalize_series(schedule_clean["game_id"])
    filtered = schedule_clean[
        (schedule_clean["team_key"] != "")
        & (schedule_clean["game_id_clean"] != "")
        & (schedule_clean["game_id_clean"].isin(play_game_ids))
    ]
    grouped = filtered.groupby("team_key")["game_id_clean"].nunique()
    return grouped.to_dict()


def build_team_display_names(
    schedule: pd.DataFrame, standings: pd.DataFrame, play_counts: dict[str, int]
) -> dict[str, str]:
    display_names: dict[str, str] = {}

    for frame in (standings, schedule):
        names = frame["team_name"] if "team_name" in frame.columns else pd.Series(dtype=str)
        for raw_name in normalize_series(names):
            if raw_name:
                key = raw_name.casefold()
                display_names.setdefault(key, raw_name)

    for key in play_counts:
        display_names.setdefault(key, key.title())

    return display_names


def check_against_standings(
    plays: pd.DataFrame,
    schedule: pd.DataFrame,
    standings: pd.DataFrame,
    games: pd.DataFrame | None,
) -> bool:
    standings_clean = standings.copy()
    standings_clean["team_key"] = normalize_team_key(standings_clean["team_name"])
    standings_clean["team_name_clean"] = normalize_series(standings_clean["team_name"])

    standings_gp = (
        standings_clean.loc[standings_clean["team_key"] != "", ["team_key", "overall_gp"]]
        .drop_duplicates(subset=["team_key"], keep="first")
        .set_index("team_key")["overall_gp"]
        .fillna(0)
        .astype(int)
        .to_dict()
    )
    schedule_counts = count_games_by_team(games, schedule)
    play_counts = count_play_games_by_team(plays, schedule, games)
    display_names = build_team_display_names(schedule, standings, play_counts)

    all_team_keys = sorted(set(standings_gp) | set(schedule_counts) | set(play_counts))

    print("[Per-team GP]")
    mismatch = False
    for team_key in all_team_keys:
        team_name = display_names.get(team_key, team_key)
        standings_count = standings_gp.get(team_key, 0)
        schedule_count = schedule_counts.get(team_key, 0)
        plays_count = play_counts.get(team_key, 0)
        status = "OK"
        if not (standings_count == schedule_count == plays_count):
            status = "MISMATCH"
            mismatch = True

        print(
            f"  {team_name:<20} | standings: {standings_count:<2} | "
            f"schedule: {schedule_count:<2} | plays: {plays_count:<2} | {status}"
        )

    return mismatch


def check_duplicate_play_rows(plays: pd.DataFrame) -> bool:
    duplicate_mask = plays.duplicated(subset=["game_id", "play_id"], keep=False)
    duplicate_rows = plays.loc[duplicate_mask, ["game_id", "play_id"]].copy()
    duplicate_pairs = duplicate_rows.drop_duplicates(subset=["game_id", "play_id"])
    duplicate_count = duplicate_pairs.shape[0]

    if duplicate_count:
        affected_game_ids = sorted_game_ids(duplicate_pairs["game_id"])
        print(
            f"[Duplicates] {duplicate_count} duplicate (game_id, play_id) pairs "
            f"across games: {affected_game_ids}"
        )
        return True

    print("[Duplicates] 0 duplicate (game_id, play_id) pairs")
    return False


def print_summary(has_mismatch: bool) -> None:
    status = "MISMATCHES FOUND" if has_mismatch else "OK"
    print(f"\n[Summary] {status}")


if __name__ == "__main__":
    sys.exit(main())
