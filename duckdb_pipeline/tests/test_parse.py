import unittest

from duckdb_pipeline.parse import build_games_rows, parse_schedule_html, parse_standings_html


STANDINGS_HTML = """
<html>
  <body>
    <table class="table bg-white">
      <thead>
        <tr><th colspan="8">Coast</th></tr>
      </thead>
      <tbody>
        <tr>
          <td><a href="/sports/fball/2025-26/schedule?teamId=101"><span class="team-name">Foothill</span></a></td>
          <td class="stats-col">5</td>
          <td class="stats-col">4-1</td>
          <td class="stats-col">.800</td>
          <td class="stats-col">10</td>
          <td class="stats-col">8-2</td>
          <td class="stats-col">.800</td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""

SCHEDULE_HOME_HTML = """
<html>
  <body>
    <table>
      <tr class="event-row home">
        <td><a href="/sports/fball/2025-26/boxscores/20250906_abcd.xml">Box</a></td>
        <td class="team opponent"><span class="team-name">San Mateo</span></td>
        <td class="result">W, 42-7</td>
      </tr>
    </table>
  </body>
</html>
"""

SCHEDULE_AWAY_HTML = """
<html>
  <body>
    <table>
      <tr class="event-row away">
        <td><a href="/sports/fball/2025-26/boxscores/20250906_abcd.xml">Box</a></td>
        <td class="team opponent"><span class="team-name">Foothill</span></td>
        <td class="result">L, 7-42</td>
      </tr>
    </table>
  </body>
</html>
"""


class ParseTests(unittest.TestCase):
    def test_parse_standings_html(self) -> None:
        rows = parse_standings_html(STANDINGS_HTML, "2025-26", "run-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["team_name"], "Foothill")
        self.assertEqual(rows[0]["team_id"], "101")
        self.assertTrue(rows[0]["schedule_url"].endswith("teamId=101"))

    def test_parse_schedule_and_build_games(self) -> None:
        home_team = {
            "run_id": "run-1",
            "season": "2025-26",
            "team_name": "Foothill",
            "team_id": "101",
            "schedule_url": "https://example.com/a",
        }
        away_team = {
            "run_id": "run-1",
            "season": "2025-26",
            "team_name": "San Mateo",
            "team_id": "202",
            "schedule_url": "https://example.com/b",
        }
        schedule_rows = parse_schedule_html(SCHEDULE_HOME_HTML, home_team, "2025-26", "run-1")
        schedule_rows += parse_schedule_html(SCHEDULE_AWAY_HTML, away_team, "2025-26", "run-1")

        self.assertEqual(len(schedule_rows), 2)
        self.assertEqual(schedule_rows[0]["game_id"], "20250906_abcd")

        games = build_games_rows(schedule_rows, "2025-26", "run-1")
        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual(game["pairing_status"], "paired")
        self.assertEqual(game["home_team_canonical"], "Foothill")
        self.assertEqual(game["away_team_canonical"], "San Mateo")
        self.assertEqual(game["unique_team_count"], 2)

    def test_build_games_duplicate_rows(self) -> None:
        schedule_rows = [
            {
                "run_id": "run-1",
                "season": "2025-26",
                "team_name": "Foothill",
                "team_id": "101",
                "game_id": "20250906_abcd",
                "game_date": "20250906",
                "home_away": "home",
                "opponent": "San Mateo",
                "result": "W, 42-7",
                "pbp_url": "https://example.com",
                "schedule_home": "Foothill",
                "schedule_away": "San Mateo",
            },
            {
                "run_id": "run-1",
                "season": "2025-26",
                "team_name": "Foothill",
                "team_id": "101",
                "game_id": "20250906_abcd",
                "game_date": "20250906",
                "home_away": "home",
                "opponent": "San Mateo",
                "result": "W, 42-7",
                "pbp_url": "https://example.com",
                "schedule_home": "Foothill",
                "schedule_away": "San Mateo",
            },
        ]
        games = build_games_rows(schedule_rows, "2025-26", "run-1")
        self.assertEqual(games[0]["pairing_status"], "single-sided")


if __name__ == "__main__":
    unittest.main()
