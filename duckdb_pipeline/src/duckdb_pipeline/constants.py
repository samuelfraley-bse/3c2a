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
