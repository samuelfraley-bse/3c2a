from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from .constants import BASE_URL, DEFAULT_USER_AGENT
from .parse import build_games_rows, parse_schedule_html, parse_standings_html


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def log(message: str) -> None:
    stamp = utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{stamp}] {message}", flush=True)


def season_standings_url(season: str) -> str:
    return f"{BASE_URL}/sports/fball/{season}/standings"


def fetch(url: str, delay: float, session: requests.Session, retries: int = 6) -> str:
    log(f"WAIT  {delay:.1f}s before fetch: {url}")
    time.sleep(delay)
    for attempt in range(retries):
        try:
            log(f"GET   {url} (attempt {attempt + 1}/{retries})")
            response = session.get(url, timeout=30)
            if response.status_code in (429, 202) or not response.text.strip():
                wait = 60 * (2 ** attempt)
                reason = "429 rate limited" if response.status_code == 429 else f"{response.status_code} empty response"
                log(f"RETRY {url} -> {reason}; sleeping {wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            log(f"OK    {url} [{response.status_code}]")
            return response.text
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", "unknown")
            log(f"FAIL  {url} -> HTTP {status}")
            raise
        except Exception as exc:
            if attempt == retries - 1:
                log(f"FAIL  {url} -> {exc}")
                raise
            wait = 15 * (2 ** attempt)
            log(f"RETRY {url} -> {exc}; sleeping {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url}")


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = DEFAULT_USER_AGENT
    return session


def scrape_structure(season: str, delay: float, run_id: str) -> dict[str, object]:
    session = build_session()
    standings_url = season_standings_url(season)
    log(f"BEGIN season={season} run_id={run_id}")
    log("STAGE standings")
    standings_html = fetch(standings_url, delay, session)
    standings_rows = parse_standings_html(standings_html, season, run_id)
    log(f"PARSE standings -> {len(standings_rows)} teams")

    raw_schedule_rows: list[dict[str, object]] = []
    schedule_rows: list[dict[str, str]] = []
    total_teams = len(standings_rows)
    log("STAGE schedules")
    for index, team in enumerate(standings_rows, start=1):
        schedule_url = team["schedule_url"]
        log(f"TEAM  [{index}/{total_teams}] {team['team_name']}")
        html = fetch(schedule_url, delay, session)
        raw_schedule_rows.append(
            {
                "run_id": run_id,
                "season": season,
                "team_id": team["team_id"],
                "team_name": team["team_name"],
                "fetched_at": utc_now(),
                "source_url": schedule_url,
                "html_text": html,
            }
        )
        parsed_games = parse_schedule_html(html, team, season, run_id)
        schedule_rows.extend(parsed_games)
        log(f"PARSE schedule -> {len(parsed_games)} rows for {team['team_name']}")

    log("STAGE games")
    games_rows = build_games_rows(schedule_rows, season, run_id)
    log(
        "PARSE games -> "
        f"{len(games_rows)} unique games "
        f"from {len(schedule_rows)} schedule rows"
    )
    return {
        "raw_standings_rows": [
            {
                "run_id": run_id,
                "season": season,
                "fetched_at": utc_now(),
                "source_url": standings_url,
                "html_text": standings_html,
            }
        ],
        "standings_rows": standings_rows,
        "raw_schedule_rows": raw_schedule_rows,
        "schedule_rows": schedule_rows,
        "games_rows": games_rows,
    }
