import unittest

from duckdb_pipeline.parse import (
    build_games_rows,
    normalize_play_text,
    parse_pbp_html,
    parse_schedule_html,
    parse_standings_html,
)


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

SCHEDULE_NEUTRAL_HOME_HTML = """
<html>
  <body>
    <table>
      <tr class="event-row neutral regional result has-recap">
        <td>
          <a
            href="/sports/fball/2025-26/boxscores/20250906_u5wl.xml"
            aria-label="Football event: September 6 01:00 PM: Cabrillo vs. Chabot: @ Hayward, CA: Box Score"
          >Box</a>
        </td>
        <td class="team opponent"><span class="team-name">Cabrillo</span></td>
        <td class="result">W, 21-14</td>
      </tr>
    </table>
  </body>
</html>
"""

PBP_HTML = """
<html>
  <head>
    <meta property="og:title" content="Foothill vs. San Mateo - Box Score - 9/6/2025" />
    <link rel="canonical" href="https://3c2asports.org/sports/fball/2025-26/boxscores/20250906_abcd.xml?view=plays" />
  </head>
  <body>
    <table>
      <tr><td id="qtr1">1st Quarter</td></tr>
      <tr><th colspan="2">Foothill at 15:00</th></tr>
      <tr>
        <td>1st and 10 at FOOTHILL25</td>
        <td>John Smith rush for 5 yards to the FOOTHILL30 (Mike Jones).</td>
      </tr>
      <tr>
        <td>2nd and 5 at FOOTHILL30</td>
        <td>John Smith pass complete to Alex Ray for 12 yards to the SAN MATE48 (Ty Lee).</td>
      </tr>
      <tr>
        <td>1st and 10 at SAN MATE48</td>
        <td>PENALTY SAN MATE holding (Ty Lee) 10 yards</td>
      </tr>
    </table>
  </body>
</html>
"""

PBP_HTML_WITH_ENTITY_ARTIFACT = """
<html>
  <head>
    <meta property="og:title" content="Butte vs. Reedley - Box Score - 8/29/2025" />
    <link rel="canonical" href="https://3c2asports.org/sports/fball/2025-26/boxscores/20250829_evpw.xml?view=plays" />
  </head>
  <body>
    <table>
      <tr><td id="qtr1">1st Quarter</td></tr>
      <tr><th colspan="2">Butte at 13:02</th></tr>
      <tr>
        <td>2nd and 4 at REEDLEY44</td>
        <td>Amare' Cooper pass complete to Rhys Cooper&amp;nbs for 14 yards to the REEDLEY44 (Christian Phill).</td>
      </tr>
    </table>
  </body>
</html>
"""


class ParseTests(unittest.TestCase):
    def test_normalize_play_text_cleans_entity_artifacts(self) -> None:
        self.assertEqual(
            normalize_play_text("Amare' Cooper pass complete to Rhys Cooper&nbs for 14 yards"),
            "Amare' Cooper pass complete to Rhys Cooper for 14 yards",
        )
        self.assertEqual(
            normalize_play_text("Amare' Cooper pass incomplete to Rhys Cooper&nbs, dropped pass."),
            "Amare' Cooper pass incomplete to Rhys Cooper, dropped pass.",
        )
        self.assertEqual(
            normalize_play_text("Rhys Cooper,dropped pass."),
            "Rhys Cooper, dropped pass.",
        )

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

    def test_parse_schedule_neutral_vs_row_sets_home_team_from_label(self) -> None:
        team = {
            "run_id": "run-1",
            "season": "2025-26",
            "team_name": "Chabot",
            "team_id": "303",
            "schedule_url": "https://example.com/chabot",
        }
        rows = parse_schedule_html(SCHEDULE_NEUTRAL_HOME_HTML, team, "2025-26", "run-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_away"], "home")
        self.assertEqual(rows[0]["schedule_home"], "Chabot")
        self.assertEqual(rows[0]["schedule_away"], "Cabrillo")

    def test_build_games_rows_falls_back_to_consistent_schedule_home_away(self) -> None:
        schedule_rows = [
            {
                "run_id": "run-1",
                "season": "2025-26",
                "team_name": "Chabot",
                "team_id": "303",
                "game_id": "20250906_u5wl",
                "game_date": "20250906",
                "home_away": "neutral",
                "opponent": "Cabrillo",
                "result": "W, 21-14",
                "pbp_url": "https://example.com",
                "schedule_home": "Chabot",
                "schedule_away": "Cabrillo",
            },
            {
                "run_id": "run-1",
                "season": "2025-26",
                "team_name": "Cabrillo",
                "team_id": "404",
                "game_id": "20250906_u5wl",
                "game_date": "20250906",
                "home_away": "neutral",
                "opponent": "Chabot",
                "result": "L, 14-21",
                "pbp_url": "https://example.com",
                "schedule_home": "Chabot",
                "schedule_away": "Cabrillo",
            },
        ]
        games = build_games_rows(schedule_rows, "2025-26", "run-1")
        self.assertEqual(games[0]["pairing_status"], "paired")
        self.assertEqual(games[0]["home_team_canonical"], "Chabot")
        self.assertEqual(games[0]["away_team_canonical"], "Cabrillo")

    def test_parse_pbp_html_base_rows(self) -> None:
        game = {
            "game_id": "20250906_abcd",
            "schedule_home": "Foothill",
            "schedule_away": "San Mateo",
            "home_team_canonical": "Foothill",
            "away_team_canonical": "San Mateo",
        }
        rows = parse_pbp_html(PBP_HTML, game, "2025-26", "run-2")
        self.assertEqual(len(rows), 3)

        rush = rows[0]
        self.assertEqual(rush["play_type"], "rush")
        self.assertEqual(rush["rusher"], "John Smith")
        self.assertEqual(rush["yards_gained"], 5)
        self.assertEqual(rush["offense"], "Foothill")
        self.assertEqual(rush["defense"], "San Mateo")
        self.assertEqual(rush["yardline_raw"], 25)
        self.assertFalse(rush["is_dropback"])
        self.assertFalse(rush["is_pass_attempt"])
        self.assertTrue(rush["is_rush_attempt"])

        completion = rows[1]
        self.assertEqual(completion["play_type"], "pass")
        self.assertEqual(completion["passer"], "John Smith")
        self.assertEqual(completion["receiver"], "Alex Ray")
        self.assertEqual(completion["pass_result"], "complete")
        self.assertTrue(completion["completion"])
        self.assertTrue(completion["is_dropback"])
        self.assertTrue(completion["is_pass_attempt"])
        self.assertFalse(completion["is_rush_attempt"])

        penalty = rows[2]
        self.assertEqual(penalty["play_type"], "penalty")
        self.assertTrue(penalty["is_penalty"])
        self.assertEqual(penalty["penalty_team"], "SAN MATE")
        self.assertEqual(penalty["penalty_player"], "Ty Lee")

    def test_parse_pbp_html_cleans_raw_text_entity_artifact(self) -> None:
        game = {
            "game_id": "20250829_evpw",
            "schedule_home": "Butte",
            "schedule_away": "Reedley",
            "home_team_canonical": "Butte",
            "away_team_canonical": "Reedley",
        }
        rows = parse_pbp_html(PBP_HTML_WITH_ENTITY_ARTIFACT, game, "2025-26", "run-3")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["raw_text"],
            "Amare' Cooper pass complete to Rhys Cooper for 14 yards to the REEDLEY44 (Christian Phill).",
        )
        self.assertEqual(rows[0]["receiver"], "Rhys Cooper")

    def test_parse_play_sack_is_dropback_and_rush_attempt(self) -> None:
        game = {
            "game_id": "20250920_47d4",
            "schedule_home": "Foothill",
            "schedule_away": "Sierra",
            "home_team_canonical": "Foothill",
            "away_team_canonical": "Sierra",
        }
        html = """
        <html>
          <head>
            <meta property="og:title" content="Foothill vs. Sierra - Box Score - 9/20/2025" />
            <link rel="canonical" href="https://3c2asports.org/sports/fball/2025-26/boxscores/20250920_47d4.xml?view=plays" />
          </head>
          <body>
            <table>
              <tr><td id="qtr1">1st Quarter</td></tr>
              <tr><th colspan="2">Foothill at 12:34</th></tr>
              <tr>
                <td>2nd and 10 at FOOTHILL25</td>
                <td>James Maxwell sacked for loss of 14 yards to the FOOTHILL11 (Von Edwards).</td>
              </tr>
            </table>
          </body>
        </html>
        """
        rows = parse_pbp_html(html, game, "2025-26", "run-4")
        self.assertEqual(len(rows), 1)
        sack = rows[0]
        self.assertEqual(sack["play_type"], "pass")
        self.assertTrue(sack["is_sack"])
        self.assertTrue(sack["is_dropback"])
        self.assertFalse(sack["is_pass_attempt"])
        self.assertTrue(sack["is_rush_attempt"])
        self.assertFalse(sack["completion"])
        self.assertEqual(sack["yards_gained"], -14)

    def test_parse_play_interception_return_fumble_keeps_zero_pass_yards(self) -> None:
        game = {
            "game_id": "20251011_cdcb",
            "schedule_home": "Allan Hancock",
            "schedule_away": "Ventura",
            "home_team_canonical": "Allan Hancock",
            "away_team_canonical": "Ventura",
        }
        html = """
        <html>
          <head>
            <meta property="og:title" content="Allan Hancock vs. Ventura - Box Score - 10/11/2025" />
            <link rel="canonical" href="https://3c2asports.org/sports/fball/2025-26/boxscores/20251011_cdcb.xml?view=plays" />
          </head>
          <body>
            <table>
              <tr><td id="qtr4">4th Quarter</td></tr>
              <tr><th colspan="2">Ventura at 02:01</th></tr>
              <tr>
                <td>2nd and 10 at ALLAN HA48</td>
                <td>Devin Tate pass intercepted by Justyce Roserie at the ALLAN HA07, Justyce Roserie return 52 yards to the VENTURA41, fumble forced by Tayvion McCoy, fumble by Justyce Roserie recovered by ALLAN HA Justyce Roserie at VENTURA43.</td>
              </tr>
            </table>
          </body>
        </html>
        """
        rows = parse_pbp_html(html, game, "2025-26", "run-5")
        self.assertEqual(len(rows), 1)
        interception = rows[0]
        self.assertEqual(interception["play_type"], "pass")
        self.assertTrue(interception["is_interception"])
        self.assertTrue(interception["is_pass_attempt"])
        self.assertFalse(interception["completion"])
        self.assertEqual(interception["yards_gained"], 0)

    def test_parse_pbp_html_quarter_start_embedded_ball_on_resets_possession(self) -> None:
        game = {
            "game_id": "20250913_z92j",
            "schedule_home": "Ventura",
            "schedule_away": "Bakersfield",
            "home_team_canonical": "Ventura",
            "away_team_canonical": "Bakersfield",
        }
        html = """
        <html>
          <head>
            <meta property="og:title" content="Bakersfield at Ventura - Box Score - 9/13/2025" />
            <link rel="canonical" href="https://3c2asports.org/sports/fball/2025-26/boxscores/20250913_z92j.xml?view=plays" />
          </head>
          <body>
            <table>
              <tr><td id="qtr2">2nd Quarter</td></tr>
              <tr><th colspan="2">Ventura at 00:00</th></tr>
              <tr>
                <td>1st and 10 at VENTURA40</td>
                <td>End of half, clock 15:00.</td>
              </tr>
              <tr><td id="qtr3">3rd Quarter</td></tr>
              <tr>
                <td>1st and 10 at VENTURA40</td>
                <td>Start of 3rd quarter, clock 15:00, BAKERSFI ball on BAKERSFI25.</td>
              </tr>
              <tr>
                <td>1st and 10 at BAKERSFI25</td>
                <td>Ian Jernigan rush for 3 yards to the BAKERSFI28 (Marcellus Brigh).</td>
              </tr>
              <tr>
                <td>2nd and 7 at BAKERSFI28</td>
                <td>Chase Furtado pass complete to Dylan Johnson for 6 yards to the BAKERSFI34 (Easton Baker).</td>
              </tr>
            </table>
          </body>
        </html>
        """
        rows = parse_pbp_html(html, game, "2025-26", "run-6")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["offense"], "Bakersfield")
        self.assertEqual(rows[0]["defense"], "Ventura")
        self.assertEqual(rows[1]["offense"], "Bakersfield")
        self.assertEqual(rows[1]["defense"], "Ventura")
        self.assertEqual(rows[1]["passer"], "Chase Furtado")
        self.assertTrue(rows[1]["is_pass_attempt"])
        self.assertTrue(rows[1]["completion"])
        self.assertEqual(rows[1]["yards_gained"], 6)

    def test_parse_play_two_point_pass_attempt_is_conversion(self) -> None:
        game = {
            "game_id": "20250830_fzzx",
            "schedule_home": "Palomar",
            "schedule_away": "Ventura",
            "home_team_canonical": "Palomar",
            "away_team_canonical": "Ventura",
        }
        html = """
        <html>
          <head>
            <meta property="og:title" content="Palomar vs. Ventura - Box Score - 8/30/2025" />
            <link rel="canonical" href="https://3c2asports.org/sports/fball/2025-26/boxscores/20250830_fzzx.xml?view=plays" />
          </head>
          <body>
            <table>
              <tr><td id="qtr2">2nd Quarter</td></tr>
              <tr><th colspan="2">Ventura at 04:00</th></tr>
              <tr>
                <td></td>
                <td>Braesen Leon pass attempt to TEAM failed (intercepted), returned by Hunter Stowe.</td>
              </tr>
            </table>
          </body>
        </html>
        """
        rows = parse_pbp_html(html, game, "2025-26", "run-7")
        self.assertEqual(len(rows), 1)
        play = rows[0]
        self.assertEqual(play["play_type"], "two_point")
        self.assertTrue(play["is_conversion"])
        self.assertFalse(play["is_dropback"])
        self.assertFalse(play["is_pass_attempt"])
        self.assertFalse(play["is_rush_attempt"])
        self.assertFalse(play["is_interception"])
        self.assertFalse(play["completion"])
        self.assertEqual(play["yards_gained"], 0)
        self.assertEqual(play["fg_result"], "failed")

    def test_parse_play_defensive_fumble_return_td_is_not_offensive_td(self) -> None:
        game = {
            "game_id": "20250906_t3z9",
            "schedule_home": "Long Beach",
            "schedule_away": "Mt. San Jacinto",
            "home_team_canonical": "Long Beach",
            "away_team_canonical": "Mt. San Jacinto",
        }
        html = """
        <html>
          <head>
            <meta property="og:title" content="Long Beach vs. Mt. San Jacinto - Box Score - 9/6/2025" />
            <link rel="canonical" href="https://3c2asports.org/sports/fball/2025-26/boxscores/20250906_t3z9.xml?view=plays" />
          </head>
          <body>
            <table>
              <tr><td id="qtr1">1st Quarter</td></tr>
              <tr><th colspan="2">Long Beach at 00:56</th></tr>
              <tr>
                <td>2nd and 7 at LONG BEA01</td>
                <td>Wyatt McCauley sacked for loss of 1 yard to the LONG BEA00 (Ifeanyi Onye), fumble by Wyatt McCauley recovered by MT. SAN Ifeanyi Onye at LONG BEA00, TOUCHDOWN, clock 00:56.</td>
              </tr>
            </table>
          </body>
        </html>
        """
        rows = parse_pbp_html(html, game, "2025-26", "run-8")
        self.assertEqual(len(rows), 1)
        play = rows[0]
        self.assertEqual(play["play_type"], "pass")
        self.assertTrue(play["is_sack"])
        self.assertTrue(play["is_fumble"])
        self.assertTrue(str(play["fumble_recovered_by"]).startswith("MT. SAN"))
        self.assertEqual(play["yards_gained"], -1)
        self.assertFalse(play["is_td"])


if __name__ == "__main__":
    unittest.main()
