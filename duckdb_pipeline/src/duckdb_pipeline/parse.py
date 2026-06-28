from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .constants import BASE_URL


def parse_standings_html(html: str, season: str, run_id: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    teams: list[dict[str, str]] = []

    for table in soup.select("table.table.bg-white"):
        conf_th = table.select_one("thead th[colspan]")
        conference = conf_th.get_text(strip=True) if conf_th else "Unknown"

        for row in table.select("tbody tr"):
            link = row.select_one('a[href*="schedule?teamId"]')
            if not link:
                continue

            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = BASE_URL + href
            qs = parse_qs(urlparse(href).query)
            team_id = qs.get("teamId", [None])[0]
            team_name = (link.select_one("span.team-name") or link).get_text(strip=True)
            cells = row.select("td.stats-col")

            def cell(index: int) -> str:
                return cells[index].get_text(strip=True) if index < len(cells) else ""

            def split_wlt(value: str) -> tuple[str, str, str]:
                parts = value.split("-")
                wins = parts[0] if len(parts) > 0 else ""
                losses = parts[1] if len(parts) > 1 else ""
                ties = parts[2] if len(parts) > 2 else "0"
                return wins, losses, ties

            conf_w, conf_l, conf_t = split_wlt(cell(1))
            overall_w, overall_l, overall_t = split_wlt(cell(4))

            teams.append(
                {
                    "run_id": run_id,
                    "season": season,
                    "conference": conference,
                    "team_name": team_name,
                    "team_id": team_id or "",
                    "schedule_url": href,
                    "conf_gp": cell(0),
                    "conf_w": conf_w,
                    "conf_l": conf_l,
                    "conf_t": conf_t,
                    "conf_pct": cell(2),
                    "overall_gp": cell(3),
                    "overall_w": overall_w,
                    "overall_l": overall_l,
                    "overall_t": overall_t,
                    "overall_pct": cell(5),
                }
            )

    return teams


def parse_schedule_html(html: str, team: dict[str, str], season: str, run_id: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    games: list[dict[str, str]] = []

    for row in soup.select("tr.event-row"):
        link = row.select_one('a[href*="/boxscores/"]')
        if not link:
            continue

        href = link.get("href", "")
        if href and not href.startswith("http"):
            href = BASE_URL + href

        match = re.search(r"boxscores/(\d{8}_\w+)\.xml", href)
        if not match:
            continue

        game_id = match.group(1)
        game_date = game_id[:8]
        classes = row.get("class", [])
        home_away = "home" if "home" in classes else "away"

        opp_cell = row.select_one("td.team.opponent span.team-name")
        opponent = opp_cell.get_text(strip=True) if opp_cell else ""

        result_cell = row.select_one("td.result")
        result = result_cell.get_text(strip=True) if result_cell else ""

        pbp_url = href.rstrip("?") + "?view=plays"
        if home_away == "home":
            home_name, away_name = team["team_name"], opponent
        else:
            home_name, away_name = opponent, team["team_name"]

        games.append(
            {
                "run_id": run_id,
                "season": season,
                "team_name": team["team_name"],
                "team_id": team["team_id"],
                "game_id": game_id,
                "game_date": game_date,
                "home_away": home_away,
                "opponent": opponent,
                "result": result,
                "pbp_url": pbp_url,
                "schedule_home": home_name,
                "schedule_away": away_name,
            }
        )

    return games


def build_games_rows(schedule_rows: list[dict[str, str]], season: str, run_id: str) -> list[dict[str, str | int]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in schedule_rows:
        game_id = (row.get("game_id") or "").strip()
        if game_id:
            grouped.setdefault(game_id, []).append(row)

    games: list[dict[str, str | int]] = []
    for game_id, rows in sorted(grouped.items()):
        canonical_names: list[str] = []
        seen_names: set[str] = set()
        home_candidates: list[str] = []
        away_candidates: list[str] = []

        for row in rows:
            team_name = (row.get("team_name") or "").strip()
            if team_name and team_name not in seen_names:
                seen_names.add(team_name)
                canonical_names.append(team_name)
            home_away = (row.get("home_away") or "").strip().lower()
            if home_away == "home" and team_name:
                home_candidates.append(team_name)
            elif home_away == "away" and team_name:
                away_candidates.append(team_name)

        team_1 = canonical_names[0] if len(canonical_names) > 0 else ""
        team_2 = canonical_names[1] if len(canonical_names) > 1 else ""
        unique_team_count = len(canonical_names)
        row_count = len(rows)
        home_team_canonical = home_candidates[0] if len(home_candidates) == 1 else ""
        away_team_canonical = away_candidates[0] if len(away_candidates) == 1 else ""

        if unique_team_count == 2 and row_count == 2:
            pairing_status = "paired"
        elif unique_team_count == 2:
            pairing_status = "duplicate-rows"
        elif unique_team_count == 1:
            pairing_status = "single-sided"
        elif unique_team_count > 2:
            pairing_status = "over-paired"
        else:
            pairing_status = "incomplete"

        first = rows[0]
        games.append(
            {
                "run_id": run_id,
                "season": season,
                "game_id": game_id,
                "game_date": first.get("game_date", ""),
                "pbp_url": first.get("pbp_url", ""),
                "schedule_home": first.get("schedule_home", ""),
                "schedule_away": first.get("schedule_away", ""),
                "home_team_canonical": home_team_canonical,
                "away_team_canonical": away_team_canonical,
                "team_1": team_1,
                "team_2": team_2,
                "schedule_row_count": row_count,
                "unique_team_count": unique_team_count,
                "pairing_status": pairing_status,
            }
        )

    return games
