# Foothill CV Football Scraper

Scrapes 3C2A football data from `3c2asports.org` into per-season CSVs with enriched field position data.

## Pipeline Overview

```
Step 1 — pipeline/01_scrape_season.py          → standings, schedule, games, plays
Step 2 — pipeline/02_generate_crosswalk_draft.py → prefix_crosswalk_draft.csv
Step 3 — [fill crosswalk manually/Claude]      → prefix_crosswalk.csv
Step 4 — pipeline/01_scrape_season.py --crosswalk → plays.csv (enriched)
```

All scripts are run from the repo root.

---

## Step-by-Step: Adding a New Season

### Step 1 — Scrape the season

```powershell
python pipeline/01_scrape_season.py --season 2024-25
```

Hits the 3C2A standings page, follows every team's schedule, and scrapes all play-by-play. Outputs under `outputs/2024-25/`:

- `standings.csv` — one row per team
- `schedule.csv` — one row per team-game
- `games.csv` — one row per unique game
- `plays.csv` — all play-by-play rows

If the scrape is interrupted, resume with `--plays-only`:

```powershell
python pipeline/01_scrape_season.py --season 2024-25 --plays-only
```

To rescrape specific games (e.g. after a parse fix):

```powershell
python pipeline/01_scrape_season.py --season 2024-25 --game-ids 20241018_1561 20241025_abcd
```

To parse a game from a saved local HTML file instead of fetching:

```powershell
python pipeline/01_scrape_season.py --season 2024-25 --game-ids 20241018_1561 --manual-dir manual/
```

#### Robustness and failed games

The scraper retries on 429 rate-limit responses and connection errors with exponential backoff. Games that fetch successfully but return 0 plays are written to:

```
outputs/{season}/failed_games.txt
```

On a resumed `--plays-only` run these games are skipped automatically. To retry after a cooldown, pass their IDs with `--game-ids` — this clears them from `failed_games.txt` and re-attempts.

Some games on 3C2A have no play-by-play page (coaches-view only). Once confirmed, leave their IDs in `failed_games.txt` as a permanent record.

---

### Step 2 — Generate the crosswalk draft

```powershell
python pipeline/02_generate_crosswalk_draft.py --season 2024-25
```

Reads `plays.csv` and `games.csv` to extract the two field position prefixes used in each game. Outputs:

- `outputs/2024-25/prefix_crosswalk_draft.csv`

Columns: `game_id`, `prefix_a`, `prefix_b`, `canonical_a`, `canonical_b` *(blank)*, `team_1`, `team_2`, `note`

---

### Step 3 — Fill the crosswalk

Open a new Claude conversation and paste this prompt:

> I have a football play-by-play crosswalk CSV. Each row is one game. I need you to fill in `canonical_a` and `canonical_b` — the full team name that each prefix belongs to. You know the two teams in the game from `team_1` and `team_2`. Match each prefix to one of those two teams. Here is the CSV:
>
> [paste the contents of `prefix_crosswalk_draft.csv`]

Save the result as:

```
outputs/2024-25/prefix_crosswalk.csv
```

**Tips:**
- For ambiguous prefixes like `MT. SAN` (could be Mt. San Antonio or Mt. San Jacinto), both teams are in `team_1`/`team_2` so Claude can resolve it unambiguously
- Double-check rows where `note` contains a warning (more than two prefixes found)
- Keep the draft file untouched as a reference

---

### Step 4 — Re-scrape with crosswalk to enrich field position

```powershell
python pipeline/01_scrape_season.py --season 2024-25 --plays-only --crosswalk outputs/2024-25/prefix_crosswalk.csv
```

This re-parses every game with the crosswalk, writing three enriched columns directly into `plays.csv`:

- `field_pos_side`: `own` or `opponent` (relative to the offense)
- `yardline_raw`: numeric yardline extracted from the field position token
- `yardline_100`: yards to the opponent end zone (own 25 → `75`, opponent 25 → `25`)

> **Note:** You can also pass `--crosswalk` during the initial Step 1 scrape if the crosswalk already exists from a prior season. Step 4 is only needed when filling the crosswalk after the fact.

---

## Scripts

| Script | Purpose |
|---|---|
| `pipeline/01_scrape_season.py` | Steps 1 + 4; rescrape specific games |
| `pipeline/02_generate_crosswalk_draft.py` | Step 2 |
| `pipeline/parse_pbp.py` | Internal — HTML → play rows, used by scraper |
| `analysis/` | Season report tables (see ANALYSIS.md) |

---

## Output Files

All outputs live under `outputs/{season}/`.

### `standings.csv`
One row per team.

### `schedule.csv`
One row per team-game scraped from a team schedule page. Key columns: `team_name`, `game_id`, `home_away`, `opponent`, `pbp_url`, `schedule_home`, `schedule_away`.

### `games.csv`
One row per unique game slug. Built by grouping schedule rows by `game_id`. Key columns: `game_id`, `pbp_url`, `home_team_canonical`, `away_team_canonical`, `team_1`, `team_2`, `pairing_status`.

`pairing_status` values:
- `paired` — both team rows were scraped (expected)
- `single-sided` — only one team's schedule was in standings
- `duplicate-rows`, `over-paired`, `incomplete` — problematic, investigate

### `plays.csv`
One row per play. After Step 4, includes `field_pos_side`, `yardline_raw`, and `yardline_100` in addition to the base parse columns. This is the analysis-ready file.

### `prefix_crosswalk_draft.csv`
Generated by Step 2. Per-game prefix pairs with blank canonical columns — input for Step 3.

### `prefix_crosswalk.csv`
Filled in Step 3. Same structure with `canonical_a` / `canonical_b` completed — input for Step 4.

### `failed_games.txt`
One game ID per line. Written when a game returns 0 plays. Safe to leave permanently for games with no PBP page.

---

## Known Parser Behavior

### Fumble yardage
Fumble plays measure net yards from the line of scrimmage to the **recovery spot**, not the tackle spot. This matches the NCAA official scoring convention. For example, a rush that gains 0 yards to the tackle spot but the ball is recovered 1 yard behind the LOS is recorded as -1 yards.

### Sacks and dropbacks
Sacks are stored as `play_type='pass', is_sack=True`. Conceptually they are dropbacks — the QB dropped back to pass and was tackled. QB scrambles appear as `play_type='rush'` and cannot be distinguished from designed runs.

NCAA box score convention counts sacks as rush attempts with negative yardage (validated against official 3C2A totals):
- **Rush attempts (NCAA)** = `play_type='rush'` + `is_sack=True`
- **Rush yards (NCAA)** = sum of `yards_gained` where `play_type='rush'` or `is_sack=True`
- **Pass attempts** = `play_type='pass'` and `is_sack=False`
- **Dropbacks** = `play_type='pass'` (pass attempts + sacks)

### Field position prefix normalization
PrestoSports sometimes truncates field position tokens with a tilde:
- 3-digit suffix (e.g. `SADDLE~139`): the leading digit is a truncation artifact → `SADDLE39`
- 2-digit suffix (e.g. `SBCC~45`): tilde is a separator only → `SBCC45`

---

## How the Crosswalk Works

PrestoSports PBP HTML uses game-specific field position prefixes like `SDMESA25`, `MSJC-FB44`, `MT. SAN31`. The same abbreviation can mean different teams across games (`MT. SAN` = Mt. San Antonio in some games, Mt. San Jacinto in others), so the mapping must be resolved per-game.

Since each game has exactly two teams, every prefix is unambiguous — it must belong to one of the two known participants. The crosswalk maps each prefix to the correct canonical team name, which the scraper uses to compute `field_pos_side` and `yardline_100`.

When no crosswalk entry exists for a game, the scraper falls back to fuzzy name matching (prefix substring of team name). This works for clean prefixes like `FOOTHILL` but will miss truncated or abbreviated ones — fill the crosswalk for reliable field position data.

---

## Health Check

```powershell
python health_check.py --season 2025-26
```

**Check 1 — Team totals integrity:** For every game, plays where team A is on offense must equal plays where team B is on defense. A mismatch means offense/defense labels got swapped — investigate the parser.

**Check 2 — Game coverage:** Every team in the schedule should have play-by-play for all their games. Games listed in `failed_games.txt` are treated as confirmed no-PBP and shown as OK.

---

## Canonical Model

The canonical game key is the boxscore slug, e.g. `20251018_4eui`. This is stable across team schedule pages and avoids drift from team-name suffixes in URLs.

`games.csv` is the authoritative game/team mapping. `plays.csv` is keyed to it and is the final analysis-ready file.
