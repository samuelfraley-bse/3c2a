import unittest

from duckdb_pipeline.lineup_scrape import (
    build_metadata_legend_url,
    build_team_print_url,
    extract_s3_json_urls,
)

# A trimmed but structurally real sample of the `ps.rendering.team.initialize(...)`
# call embedded in a team's print-view page (see LOGS.md, 2026-07-05).
SAMPLE_PRINT_PAGE_SCRIPT = """
<script>
    $(document).ready(function () {
        ps.rendering.team.initialize(
                true,
                "en_us",
                "https://prestosports-downloads.s3.us-west-2.amazonaws.com/teamData/an42fqq3u1wiedd5.json",
                "https://prestosports-downloads.s3.us-west-2.amazonaws.com/playersData/agwhctziptolcaqc.json",
                                        "https://prestosports-downloads.s3.us-west-2.amazonaws.com/teamsData/t1omz6dw1rwy3dfa.json"
                ,
                "https://prestosports-downloads.s3.us-west-2.amazonaws.com/metaData/SPORT_CODE.json",
                "/sports/fball/2025-26",
                null, null, null, null, null, null, null, null,
                true, true,
                "https://prestosports-downloads.s3.us-west-2.amazonaws.com/metaData/g5xpj7agcui7frap/SPORT_CODE/statsPagesLayoutPathsTree.json"        );
    });
</script>
"""


class LineupScrapeTests(unittest.TestCase):
    def test_build_team_print_url(self) -> None:
        url = build_team_print_url("2025-26", "foothill")
        self.assertEqual(
            url,
            "https://3c2asports.org/sports/fball/2025-26/teams/foothill"
            "?tmpl=teaminfo-network-monospace-json-template",
        )

    def test_extract_s3_json_urls(self) -> None:
        endpoints = extract_s3_json_urls(SAMPLE_PRINT_PAGE_SCRIPT)
        self.assertEqual(
            endpoints,
            {
                "team": "https://prestosports-downloads.s3.us-west-2.amazonaws.com/teamData/an42fqq3u1wiedd5.json",
                "players": "https://prestosports-downloads.s3.us-west-2.amazonaws.com/playersData/agwhctziptolcaqc.json",
                "teams": "https://prestosports-downloads.s3.us-west-2.amazonaws.com/teamsData/t1omz6dw1rwy3dfa.json",
            },
        )
        # The literal "SPORT_CODE.json" / ".../SPORT_CODE/..." URLs are
        # unresolved JS template placeholders, not real endpoints -- they
        # must NOT be surfaced as a fourth/fifth entry here. The real
        # metadata legend URL is only known after resolving `sportCode`
        # from the fetched teamData JSON (see build_metadata_legend_url).
        self.assertEqual(len(endpoints), 3)

    def test_extract_s3_json_urls_missing_teams(self) -> None:
        # A player's own bio page passes `null` for teamsDataEndp -- confirm
        # a missing source doesn't raise and just isn't in the result.
        script = SAMPLE_PRINT_PAGE_SCRIPT.replace(
            '"https://prestosports-downloads.s3.us-west-2.amazonaws.com/teamsData/t1omz6dw1rwy3dfa.json"',
            "null",
        )
        endpoints = extract_s3_json_urls(script)
        self.assertNotIn("teams", endpoints)
        self.assertIn("team", endpoints)
        self.assertIn("players", endpoints)

    def test_build_metadata_legend_url(self) -> None:
        self.assertEqual(
            build_metadata_legend_url(0),
            "https://prestosports-downloads.s3.us-west-2.amazonaws.com/metaData/0.json",
        )


if __name__ == "__main__":
    unittest.main()
