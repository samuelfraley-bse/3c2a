from pathlib import Path


BASE_URL = "https://3c2asports.org"
DEFAULT_SEASON = "2025-26"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = str(PROJECT_ROOT / "data" / "foothill.duckdb")
DEFAULT_DELAY = 5.0
DEFAULT_USER_AGENT = "foothill-duckdb-pipeline/0.1"

STANDINGS_FIELDS = [
    "run_id",
    "season",
    "conference",
    "team_name",
    "team_id",
    "schedule_url",
    "conf_gp",
    "conf_w",
    "conf_l",
    "conf_t",
    "conf_pct",
    "overall_gp",
    "overall_w",
    "overall_l",
    "overall_t",
    "overall_pct",
]

SCHEDULE_FIELDS = [
    "run_id",
    "season",
    "team_name",
    "team_id",
    "game_id",
    "game_date",
    "home_away",
    "opponent",
    "result",
    "pbp_url",
    "schedule_home",
    "schedule_away",
]

GAMES_FIELDS = [
    "run_id",
    "season",
    "game_id",
    "game_date",
    "pbp_url",
    "schedule_home",
    "schedule_away",
    "home_team_canonical",
    "away_team_canonical",
    "team_1",
    "team_2",
    "schedule_row_count",
    "unique_team_count",
    "pairing_status",
]

PLAYS_FIELDS = [
    "run_id",
    "season",
    "game_id",
    "home_team",
    "away_team",
    "schedule_home",
    "schedule_away",
    "play_id",
    "drive_id",
    "drive_start_time",
    "quarter",
    "down",
    "distance",
    "field_position",
    "yardline_raw",
    "offense",
    "defense",
    "play_type",
    "passer",
    "rusher",
    "receiver",
    "pass_result",
    "yards_gained",
    "is_dropback",
    "is_attempt",
    "is_conversion",
    "is_pass_attempt",
    "is_rush_attempt",
    "completion",
    "is_interception",
    "is_td",
    "is_sack",
    "is_fumble",
    "fumble_recovered_by",
    "is_penalty",
    "penalty_team",
    "penalty_type",
    "penalty_player",
    "penalty_yards",
    "fg_result",
    "tackler_1",
    "tackler_2",
    "raw_text",
]
