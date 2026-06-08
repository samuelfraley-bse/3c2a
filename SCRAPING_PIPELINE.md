# Scraping Pipeline — Technical Reference

This document describes the complete scraping and data pipeline for the Foothill CV football analytics project. It is intended as a reference for adapting this process to other leagues.

---

## 1. Data Source

**Platform:** PrestoSports (hosted at `3c2asports.org`)
**League:** 3C2A — California Community College Athletic Association
**Teams:** 66 California community college football programs
**Seasons:** Multi-season support via URL parameter

**Entry Point URLs:**
- Standings: `https://3c2asports.org/sports/fball/{season}/standings`
- Team Schedule: `https://3c2asports.org/sports/fball/{season}/schedule?teamId={team_id}`
- Play-by-Play: `https://3c2asports.org/sports/fball/{season}/boxscores/{game_id}.xml?view=plays`
- Participation: `https://3c2asports.org/sports/fball/{season}/boxscores/{game_id}.xml?view=participation`
- Team Roster: varies by team (PrestoSports subdomain, path `roster` or `sports/fball/{season}/roster`)

Game IDs follow the format `YYYYMMDD_slug` (e.g. `20251025_ligd`).

---

## 2. Scraping Method

**Libraries:** `requests`, `BeautifulSoup` (HTML parsing), `re` (regex field extraction)

**Robustness:**
- HTTP 429 rate-limit retries with exponential backoff: `60s × 2^attempt`
- Connection error retries with exponential backoff: `15s × 2^attempt`
- Configurable delay between requests (default `5.0s`)
- Failed games (0 plays returned) logged to `failed_games.txt`
- Resume via `--plays-only` flag (skips already-scraped games)
- Manual fallback: locally-saved `.html` files parseable with `--manual-dir`

---

## 3. Pipeline Stages

### Stage 1 — Scrape Season (`pipeline/01_scrape_season.py`)

**Standings page → `outputs/{season}/standings.csv`**

HTML targets:
- Conference name: `thead th[colspan]` text
- Team links: `a[href*="schedule?teamId"]`
- Team name: `span.team-name`
- Stats cells: `td.stats-col` (8 cells per row)

**Schedule page (per team) → `outputs/{season}/schedule.csv`**

HTML targets:
- Game link + ID: `a[href*="/boxscores/"]`, regex `boxscores/(\d{8}_\w+)\.xml`
- Home/Away: `tr.event-row` class ("home" or "away")
- Opponent: `td.team.opponent span.team-name`
- Result: `td.result` text

Schedule rows are deduplicated by game ID to produce `games.csv` (one row per unique game).

### Stage 2 — Scrape Play-by-Play (`pipeline/parse_pbp.py`)

**PBP HTML (per game) → `outputs/{season}/plays.csv`**

HTML targets:
- Game title: `meta[property="og:title"]` → extracts "Home vs Away"
- Game date: `link[rel="canonical"]` → extracts `YYYYMMDD`
- Quarter headers: `td[id^="qtr"]`
- Drive headers: single `th` with colspan, format `"TeamName at HH:MM"`
- Play rows: `tr` with exactly 2 `td` cells
  - `td[0]`: Situation ("1st and 10 at FIELDPOS")
  - `td[1]`: Play description text

### Stage 3 — Scrape Participation (`pipeline/02_scrape_participation.py`)

**Participation page (per game) → `outputs/{season}/participation.csv`**

URL pattern: same as PBP but `?view=participation` instead of `?view=plays`.

HTML structure: one outer table with two nested player tables (one per team). Each row is `jersey | player_name`. Both the participated and did-not-participate sections are captured with a `participated` boolean column.

Supports resume after interruption — already-scraped game IDs are skipped on re-run. Rate-limit codes 429 and 459 are retried with exponential backoff.

### Stage 4 — Scrape Rosters (`pipeline/03_scrape_rosters.py`)

**Team roster page (per team) → `outputs/{season}/players.csv`**

Scrapes official PrestoSports team roster pages for `pos`, `height`, `weight`, `hometown`. Used as a supplementary source for position data after canonical names are resolved from participation data.

Note: some teams return 403 or use JS-rendered pages — these are skipped. Players who dress but are not on the official roster page (walk-ons, late additions) are covered by participation data instead.

### Stage 5 — Build Field Position Crosswalk (`pipeline/04_generate_field_pos_crosswalk.py`)

PrestoSports uses game-specific field position prefixes (e.g. `FOOTHILL28`, `MT SANxx`). The same abbreviation can refer to different teams across games, so a per-game crosswalk is required.

**Generate draft → `outputs/{season}/prefix_crosswalk_draft.csv`**

Extracts all prefixes seen in `field_position` tokens, two per game. Canonical team name columns are left blank for review.

**Fill crosswalk → `outputs/{season}/prefix_crosswalk.csv`**

Resolution algorithm:
1. Check `MANUAL` dict (abbreviation → canonical name hardcoded for known ambiguous cases, 30+ entries)
2. Fuzzy substring match: prefix is substring of team name
3. Mark unresolved for manual review

### Stage 6 — Re-parse with Crosswalk (Optional)

Re-scrape or re-parse affected games using `--game-ids` flag. The crosswalk resolves:
- `field_pos_side`: `'own'` if owner == offense else `'opponent'`
- `yardline_100`: `100 - yardline_raw` if own side, else `yardline_raw`

### Stage 6b — Scrape Lineup for Player Slugs (`pipeline/10_scrape_lineup.py`)

**Team season stats pages (7 per team) → `outputs/{season}/lineup.csv`**

URL pattern: `cccaa.prestosports.com/sports/fball/{season}/teams/{team_slug}?view=season&pos={pos}` where pos ∈ `{qb, rb, wr, d, k, p, kr}`.

These are static (non-JS) pages — unlike the main lineup tab which DataTables-paginates to 25 rows, the position-filtered pages return the full list.

HTML target: `a[href*="/players/"]` — each link's text is the canonical name; the href slug encodes a stable opaque player ID.

Team slugs are extracted from `manual/print-teams-dec-printer-decorator.html` (save the printer-decorator URL from the teams page: `?dec=printer-decorator`).

Output columns: `team_name, team_slug, player_name, player_slug, pos_group`

`player_slug` (e.g. `drakemissamore7nfq`) contains the player ID embedded after the normalized name portion. This slug is stable across seasons and builds the profile URL: `3c2asports.org/sports/fball/{season}/players/{slug}`.

**This stage is complementary to participation scraping, not a replacement:**

| Source | Coverage | Has player slug | Has position | Used for |
|---|---|---|---|---|
| `participation.csv` | All players who dressed, every game | No | No | Name canonicalization (primary) |
| `lineup.csv` | Players with stats in their pos group | Yes | Inferred from pos_group | Cross-season player linking |
| `players.csv` | Teams with accessible roster pages only | No | Yes | Position, height, weight, hometown |

Rate limiting: this scraper defaults to 15s inter-request delay plus 45s between teams, with user-agent rotation. 490 total requests (~3.5 hours). Supports resume.

### Stage 7 — Player Name Normalization

PBP text uses inconsistent name spellings across games (truncations, typos, suffixes). Three steps normalize names to a single canonical form per player per team.

**Export unique names (`pipeline/06_export_pbp_names.py`) → `outputs/{season}/pbp_names.csv`**

Extracts all unique `(team, role, pbp_name)` combinations from plays.csv. Role is one of `passer`, `rusher`, `receiver`, `defender`. Teams with no participation data are flagged `no_roster`.

**Auto-match (`pipeline/07_match_pbp_names.py`) → updates `pbp_names.csv`**

Fuzzy-matches each PBP name against participation.csv names for the same team. Uses prefix matching, spelling similarity, suffix handling, and nickname equivalence. Unresolved rows are flagged for LLM review. Position is looked up from players.csv after a match is found.

**Apply crosswalk (`pipeline/08_apply_player_crosswalk.py`) → updates `plays.csv` in-place**

Replaces `passer`, `rusher`, `receiver`, `tackler_1`, `tackler_2`, and `penalty_player` columns with canonical names from `pbp_names.csv`.

---

## 4. Fields Extracted from HTML (Raw)

### From Standings
| Field | Source |
|---|---|
| `season` | URL parameter |
| `conference` | Table header |
| `team_name`, `team_id` | Team link text/href |
| `conf_gp/w/l/t/pct` | Stats cells |
| `overall_gp/w/l/t/pct` | Stats cells |

### From Schedule
| Field | Source |
|---|---|
| `game_id` | Boxscore link regex |
| `game_date` | Game ID prefix |
| `home_away` | `tr.event-row` class |
| `opponent` | Opponent cell |
| `result` | Result cell text |
| `pbp_url` | Constructed from boxscore URL |

### From Play-by-Play Text (Regex Patterns)

**Situation column (left cell):**
- Pattern: `(\d+)(?:st|nd|rd|th)\s+and\s+(\d+|goal)\s+at\s+([A-Z][A-Z0-9\s\.\-\_\~]*?\d+)`
- Extracts: `down` (1–4), `distance` (yards or "goal"), `field_position` (raw token)

**Play description column (right cell):**

| Play Type | Key Regex Pattern | Extracted Fields |
|---|---|---|
| Rush | `(\w[\w\s\-\'\.]+?)\s+rush for` | ball_carrier, yards |
| Pass complete | `pass complete to\s+(\w[\w\s\-\'\.]+?)\s+for` | passer, receiver, yards |
| Pass incomplete | `pass incomplete` | passer, optional target |
| Interception | `pass intercept` | passer, outcome |
| Sack | `(\w[\w\s\-\'\.]+?)\s+sacked for` | passer, yards (negative) |
| Punt | `punt(?:\s+(\d+)\s+yards)?` | punter, distance |
| Kickoff | `kickoff\s+(\d+)\s+yards` | kicker, distance |
| Field goal | `field goal attempt from\s+(\d+)\s+(GOOD\|MISSED)` | kicker, distance, result |
| PAT/2-pt | `(?:kick\|rush\|pass)\s+attempt\s+(GOOD\|FAILED)` | result |
| Fumble | `fumble by ... recovered by ... at FIELDPOS` | fumbler, recoverer, recovery location |
| Penalty | `PENALTY\s+([A-Z\s]+)\s+([a-z][\w\s]*?)\s*\(([^)]+)\)\s+(\d+)` | team, type, player, yards |
| Yardage | `for\s+(loss of\s+)?(\d+)\s+yards?` | signed integer |
| Touchdown | Contains literal "touchdown" | boolean |
| Tacklers | Trailing parenthetical `\(([^()]+)\)` | semicolon-separated names |

**Drive header:**
- Pattern: `^(.+?)\s+at\s+(\d+:\d+)$`
- Extracts: offense team name, drive start clock time
- Offense/defense resolved by fuzzy match against home/away team names

---

## 5. Derived / Computed Fields

### Field Position (Computed During Parse)

PrestoSports tilde-truncation handling:
- `SADDLE~139` → `SADDLE39` (3 trailing digits: drop leading digit)
- `SBCC~45` → `SBCC45` (2 trailing digits: keep as-is)

| Field | Computation |
|---|---|
| `yardline_raw` | Numeric suffix of field position token |
| `field_pos_side` | `'own'` or `'opponent'` via crosswalk |
| `yardline_100` | `100 - yardline_raw` (own side) or `yardline_raw` (opponent side). Range 1–99 from offense goal line. |

Fumble yardage: net yards = field position change from line of scrimmage to recovery spot (can be negative).

### Analysis Flags (Computed in `analysis/helpers.py`)

| Flag | Definition |
|---|---|
| `success` | 1st: yards ≥ 40% of distance; 2nd: ≥ 60%; 3rd/4th: ≥ 100% |
| `explosive` | Pass ≥ 20 yards or rush ≥ 10 yards |
| `passing_down` | (down==2 & distance≥8) or (down∈[3,4] & distance≥5) |
| `early_down` | down∈[1,2] and not passing_down |
| `redzone` | field_pos_side=='opponent' and yardline_100≤20 |
| `completion` | pass_result∈['complete','td'] |
| `run_stuff` | play_type=='rush' and yards_gained≤0 |

### NCAA Stat Conventions

- Sacks: stored as `play_type='pass', is_sack=True` (conceptually dropbacks)
- Sack yards: counted as negative rushing yards (NCAA convention)
- QB scrambles: indistinguishable from designed runs, both `play_type='rush'`
- Dropbacks = all `play_type='pass'` rows (attempts + sacks)
- Pass attempts = `play_type='pass' & is_sack=False`
- Rush attempts (NCAA) = `play_type='rush' | is_sack=True`
- Fumble return TDs: scored to defense, not offense

---

## 6. Output Files

All outputs land in `outputs/{season}/`.

### `standings.csv`
~66 rows, 15 columns: `season, conference, team_name, team_id, schedule_url, conf_gp/w/l/t/pct, overall_gp/w/l/t/pct`

### `schedule.csv`
~1,300 rows (each game appears twice, once per team): `season, team_name, team_id, game_id, game_date, home_away, opponent, result, pbp_url, schedule_home, schedule_away`

### `games.csv`
~650 rows (one per unique game): `season, game_id, game_date, pbp_url, schedule_home, schedule_away, home_team_canonical, away_team_canonical, team_1, team_2, schedule_row_count, unique_team_count, pairing_status`

`pairing_status` values: `paired`, `duplicate-rows`, `single-sided`, `over-paired`, `incomplete`

### `plays.csv`
~56,000 rows (season 2025–26), 35 columns:

**Game context:** `game_id, home_team, away_team, schedule_home, schedule_away, play_id, drive_id`

**Timing:** `drive_start_time, quarter, down, distance`

**Field position:** `field_position, yardline_raw, field_pos_side, yardline_100, offense, defense`

**Play type & actors:** `play_type, passer, rusher, receiver, pass_result`

**Outcome:** `yards_gained, is_td, is_sack, is_fumble, fumble_recovered_by, fg_result`

**Penalties:** `is_penalty, penalty_team, penalty_type, penalty_player, penalty_yards`

**Defense:** `tackler_1, tackler_2`

**Raw:** `raw_text`

### `participation.csv`
~40,000–50,000 rows (347 games × ~2 teams × ~50–110 players): `game_id, team_name, jersey, player_name, participated`

`participated=true` for players who dressed and played; `participated=false` for did-not-play. Note: DNP player names may be truncated in the source HTML.

### `players.csv`
~2,000–3,000 rows (teams with accessible roster pages only): `season, team_name, player_id, jersey, player_name, pos, height, weight, hometown, headshot_url`

### `lineup.csv`
~2,000–4,000 rows (70 teams × 7 position groups, deduplicated): `team_name, team_slug, player_name, player_slug, pos_group`

Players appear once per position group in which they have recorded stats. A player can appear in multiple pos_group rows (e.g. a receiver who also returns kicks appears under both `wr` and `kr`).

### `pbp_names.csv`
~4,700 rows: `team, role, pbp_name, canonical_name, position, flagged, review_flag`

Output of `06_export_pbp_names.py`; filled by `07_match_pbp_names.py` and LLM review.

### `prefix_crosswalk_draft.csv` / `prefix_crosswalk.csv`
~650 rows: `game_id, prefix_a, prefix_b, canonical_a, canonical_b, team_1, team_2, note`

### `failed_games.txt`
One game ID per line — games that returned 0 plays (no PBP available). Safe to leave permanently.

---

## 7. Example Play Record

```
game_id:           20251018_4eui
home_team:         Foothill
away_team:         San Mateo
play_id:           3
drive_id:          1
drive_start_time:  14:54
quarter:           1
down:              3
distance:          8
field_position:    FOOTHILL30
yardline_raw:      30
field_pos_side:    own
yardline_100:      70
offense:           Foothill
defense:           San Mateo
play_type:         pass
passer:            John Larios
rusher:            NULL
receiver:          NULL
pass_result:       incomplete
yards_gained:      -7
is_td:             False
is_sack:           True
is_fumble:         False
tackler_1:         Veni Wolfgramm
tackler_2:         NULL
raw_text:          "John Larios sacked for loss of 7 yards to the FOOTHILL23 (Veni Wolfgramm)."
```

---

## 8. Adapting to a Different League

Key things to verify when porting to a new PrestoSports-hosted league:
1. **URL structure** — confirm standings, schedule, and boxscore URL patterns
2. **HTML selectors** — table class names and row/cell structure may differ
3. **Game ID format** — confirm the `YYYYMMDD_slug` pattern holds
4. **Play description text** — regex patterns assume specific phrasing; audit a sample of raw plays
5. **Field position tokens** — confirm tilde-truncation behavior and prefix conventions
6. **Team name disambiguation** — build a new `MANUAL` dict for your league's abbreviations
7. **`?view=plays` parameter** — confirm PBP is served this way (PrestoSports-standard but worth checking)

For non-PrestoSports sources: the parse logic in `pipeline/parse_pbp.py` is the most platform-specific piece. The downstream schema (`plays.csv` columns) and all analysis code can remain unchanged if you produce the same output schema.
