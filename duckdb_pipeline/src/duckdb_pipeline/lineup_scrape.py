from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .constants import BASE_URL
from .scrape import build_session, fetch

# The exact S3-hosted JSON sources this project has confirmed exist (see
# duckdb_pipeline/LOGS.md, 2026-07-05): searched every rendering script
# referenced by every page type found so far for the `*DataEndp` naming
# convention the site's own JS uses to pass these URLs around, and found
# exactly these five, no more -- teamData, playersData, teamsData,
# playerData (per-player, not fetched here), and the metaData legend.

_S3_HOST_PREFIX = "https://prestosports-downloads.s3."


def build_team_print_url(season: str, team_slug: str) -> str:
    return f"{BASE_URL}/sports/fball/{season}/teams/{team_slug}?tmpl=teaminfo-network-monospace-json-template"


def extract_s3_json_urls(print_page_html: str) -> dict[str, str]:
    """Pull the `teamData`/`playersData`/`teamsData` S3 URLs out of a team's
    print-view page (embedded in its `ps.rendering.team.initialize(...)` call).
    """
    urls: list[str] = []
    for match in re.finditer(re.escape(_S3_HOST_PREFIX) + r"[^\"\s,)]+", print_page_html):
        url = match.group()
        if url not in urls:
            urls.append(url)

    endpoints: dict[str, str] = {}
    for url in urls:
        if "/teamData/" in url:
            endpoints["team"] = url
        elif "/playersData/" in url:
            endpoints["players"] = url
        elif "/teamsData/" in url:
            endpoints["teams"] = url
    return endpoints


def build_metadata_legend_url(sport_code: object) -> str:
    return f"{_S3_HOST_PREFIX}us-west-2.amazonaws.com/metaData/{sport_code}.json"


def fetch_lineup_json_sources(
    season: str,
    team_slug: str,
    delay: float,
    session=None,
) -> list[dict[str, object]]:
    """Fetch the team/players/teams/metadata-legend JSON sources discoverable
    from one team's print-view page.

    Returns rows shaped for `raw_lineup_json` (missing `run_id`, which the
    caller attaches). `players`/`teams` are conference-wide singletons --
    fetching them via one team is enough to cover every team in the
    conference; they don't need to be re-fetched per team.
    """
    if session is None:
        session = build_session()

    rows: list[dict[str, object]] = []

    def add_row(source_kind: str, url: str, text: str) -> None:
        rows.append(
            {
                "season": season,
                "source_kind": source_kind,
                "fetched_at": datetime.now(timezone.utc),
                "source_url": url,
                "json_text": text,
            }
        )

    print_url = build_team_print_url(season, team_slug)
    print_html = fetch(print_url, delay, session)
    endpoints = extract_s3_json_urls(print_html)
    if "team" not in endpoints:
        raise RuntimeError(f"Could not find a teamData endpoint on {print_url}")

    team_json_text = fetch(endpoints["team"], delay, session)
    add_row("team_json", endpoints["team"], team_json_text)

    if "players" in endpoints:
        players_json_text = fetch(endpoints["players"], delay, session)
        add_row("players_json", endpoints["players"], players_json_text)

    if "teams" in endpoints:
        teams_json_text = fetch(endpoints["teams"], delay, session)
        add_row("teams_json", endpoints["teams"], teams_json_text)

    sport_code = json.loads(team_json_text).get("sportCode")
    if sport_code is not None:
        metadata_url = build_metadata_legend_url(sport_code)
        metadata_json_text = fetch(metadata_url, delay, session)
        add_row("metadata_legend_json", metadata_url, metadata_json_text)

    return rows
