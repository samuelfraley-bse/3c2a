# Foothill CV Football Scraper

Scrapes 3C2A football data from `3c2asports.org` into per-season CSVs with enriched field position data.

## Pipeline Overview

```
── Data collection ──────────────────────────────────────────────────────
01_scrape_season.py          → standings, schedule, games, plays.csv
02_scrape_participation.py   → participation.csv  (per-game player lists)
03_scrape_rosters.py         → players.csv        (positions, hometowns)

── Field position crosswalk ─────────────────────────────────────────────
04_generate_field_pos_crosswalk.py → prefix_crosswalk_draft.csv
[fill crosswalk manually/LLM]      → prefix_crosswalk.csv
01_scrape_season.py --crosswalk    → plays.csv (enriched field position)

── Validation ───────────────────────────────────────────────────────────
05_check_season.py           → spot-check team totals vs box scores

── Player name canonicalization ─────────────────────────────────────────
10_scrape_lineup.py          → lineup.csv     (canonical names + player slugs)
06_export_pbp_names.py       → pbp_names.csv  (unique PBP names to fill)
07_match_pbp_names.py        → pbp_names.csv  (auto-fill from participation)
[LLM review of unresolved rows]
08_apply_player_crosswalk.py → plays.csv      (canonical names applied)
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

Most prefixes resolve automatically via substring matching. Use the script below, which handles clean prefixes (`FOOTHILL`, `REEDLEY`) automatically and requires a manual mapping dict only for abbreviations and mascot-name variants (`CCSF`, `ARC`, `MSJC-FB`, etc.).

```python
import csv, re

def norm(s): return re.sub(r'[^a-z0-9]', '', s.lower())

# Add entries here for any prefix that doesn't substring-match its team name
MANUAL = {
    'CCSF':    'San Francisco',
    'SRJC':    'Santa Rosa',
    'ARC':     'American River',
    'ECC':     'El Camino',
    'DVC':     'Diablo Valley',
    'FCC':     'Fresno City',
    'LMC':     'Los Medanos',
    'MER':     'Merced',
    'COD':     'Desert',
    'COC':     'Canyons',
    'CSM':     'San Mateo',
    'CHAF':    'Chaffey',
    'CHAB':    'Chabot',
    'DAC':     'De Anza',
    'SBCC':    'Santa Barbara',
    'SBVC':    'San Bernardino Valley',
    'WLAC':    'West LA',
    'LASW':    'LA Southwest',
    'MSJC-FB': 'Mt. San Jacinto',
    'GWC-FB':  'Golden West',
    'OCC-FB':  'Orange Coast',
    'ELCO':    'El Camino',
    'SADDLE':  'Saddleback',
    'SDMESA':  'San Diego Mesa',
    'VVC':     'Victor Valley',
    'PAL':     'Palomar',
    'RCC':     'Riverside',
    'FRC':     'Feather River',
    'FEATHER': 'Feather River',
    'FRESNO':  'Fresno City',
    'MODESTO': 'Modesto',
    'SEQUOIAS':'Sequoias',
    'SJC':     'Sierra',
    'CAB':     'Cabrillo',
    'GLEN':    'Glendale',
    'FOOT':    'Foothill',
    'LANE':    'Laney',
    'LANEY':   'Laney',
    'SAN JOAQ':'San Joaquin Delta',
    'COALINGA':'Coalinga',
}

def resolve(prefix, t1, t2):
    if prefix in MANUAL:
        return MANUAL[prefix]
    np = norm(prefix)
    nt1, nt2 = norm(t1), norm(t2)
    m1 = np in nt1 or nt1.startswith(np)
    m2 = np in nt2 or nt2.startswith(np)
    if m1 and not m2: return t1
    if m2 and not m1: return t2
    return ''  # needs manual review

rows = list(csv.DictReader(open('outputs/2024-25/prefix_crosswalk_draft.csv', encoding='utf-8')))
out, problems = [], []
for r in rows:
    ca = resolve(r['prefix_a'], r['team_1'], r['team_2'])
    cb = resolve(r['prefix_b'], r['team_1'], r['team_2'])
    out.append({'game_id': r['game_id'], 'prefix_a': r['prefix_a'], 'prefix_b': r['prefix_b'],
                'canonical_a': ca, 'canonical_b': cb})
    if not ca or not cb or ca == cb:
        problems.append(r)

with open('outputs/2024-25/prefix_crosswalk.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['game_id','prefix_a','prefix_b','canonical_a','canonical_b'])
    w.writeheader(); w.writerows(out)

print(f'Written: {len(out)} rows, Problems: {len(problems)}')
for p in problems:
    print(p)
```

Run the script, then check any rows printed under `Problems` — add them to `MANUAL` and re-run until zero problems remain.

**Audit** — verify every resolved canonical is actually one of the game's two teams and they don't collide:

```python
for r, o in zip(rows, out):
    assert o['canonical_a'] in (r['team_1'], r['team_2']), r
    assert o['canonical_b'] in (r['team_1'], r['team_2']), r
    assert o['canonical_a'] != o['canonical_b'], r
print('Audit passed')
```

Save the completed file as `outputs/2024-25/prefix_crosswalk.csv`.

---

### Step 4 — Re-parse affected games with the crosswalk

After the crosswalk is filled you can audit existing `plays.csv` data to find games with wrong `field_pos_side` without re-scraping everything:

```python
import csv, re

def norm(s): return re.sub(r'[^a-z0-9]', '', s.lower())
RE_PREFIX = re.compile(r'^([A-Z][A-Z0-9\s\.\-]*?)\d+$')

xwalk = {}
with open('outputs/2024-25/prefix_crosswalk.csv', newline='', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        xwalk.setdefault(r['game_id'], {})[r['prefix_a']] = r['canonical_a']
        xwalk.setdefault(r['game_id'], {})[r['prefix_b']] = r['canonical_b']

wrong_games = set()
with open('outputs/2024-25/plays.csv', newline='', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        fp = row.get('field_position','').strip()
        side = row.get('field_pos_side','').strip()
        offense = row.get('offense','').strip()
        gid = row.get('game_id','').strip()
        if not fp or not side or not offense or not gid: continue
        m = RE_PREFIX.match(fp.strip().upper())
        if not m: continue
        prefix = m.group(1).strip()
        owner = xwalk.get(gid, {}).get(prefix)
        if owner is None: continue
        if (('own' if owner == offense else 'opponent') != side):
            wrong_games.add(gid)

print(f'Games needing re-parse: {len(wrong_games)}')
print(' '.join(sorted(wrong_games)))
```

Then re-parse only those games (fetches from network — use a safe delay):

```powershell
python pipeline/01_scrape_season.py --season 2024-25 --plays-only --delay 15 --game-ids <ids from above>
```

If the site rate-limits you, save the HTML manually (File → Save As in browser) into a `manual/` directory named `<game_id>.html`, then:

```powershell
python pipeline/01_scrape_season.py --season 2024-25 --plays-only --manual-dir manual --game-ids <ids>
```

> **Note:** You can also pass `--crosswalk` during the initial Step 1 scrape if the crosswalk already exists from a prior season — this avoids needing Step 4 at all.

---

## Scripts

| Script | Purpose |
|---|---|
| `pipeline/01_scrape_season.py` | Scrape season; rescrape specific games with crosswalk |
| `pipeline/02_scrape_participation.py` | Scrape per-game participation + DNP lists |
| `pipeline/03_scrape_rosters.py` | Scrape team roster pages (positions, hometowns) |
| `pipeline/04_generate_field_pos_crosswalk.py` | Generate field position prefix crosswalk draft |
| `pipeline/05_check_season.py` | Validate team totals vs official box scores |
| `pipeline/06_export_pbp_names.py` | Export unique PBP player names for normalization |
| `pipeline/07_match_pbp_names.py` | Auto-fill canonical names from participation data |
| `pipeline/08_apply_player_crosswalk.py` | Apply canonical names to plays.csv |
| `pipeline/10_scrape_lineup.py` | Scrape canonical player names + stable player slugs from season stats pages |
| `pipeline/find_prestosports_rosters.py` | Utility — probe and verify roster URLs |
| `pipeline/parse_pbp.py` | Internal — HTML → play rows, used by 01 |
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

## Player Name Sources

Two scrapers collect player identity data, and they serve different purposes:

### `02_scrape_participation.py` — who played in each game

```powershell
python pipeline/02_scrape_participation.py --season 2025-26 --delay 8
```

Scrapes `?view=participation` for every game. Produces `participation.csv` with every player who dressed (participated) or was listed as a DNP, per game. This is the **primary source for name canonicalization** because:
- It covers 100% of teams, including those with no accessible roster page.
- It captures walk-ons and late additions who never appear on the official website roster.
- Names are from the same PrestoSports database that drives the PBP text.

`07_match_pbp_names.py` uses participation as its matching pool — for each PBP name it fuzzy-matches against the set of players who appeared in any game for that team.

### `10_scrape_lineup.py` — canonical names + stable player IDs

```powershell
python pipeline/10_scrape_lineup.py --season 2025-26
```

Scrapes the non-JS per-position stats pages (`?view=season&pos=qb` etc.) for each team. Produces `lineup.csv` with the canonical player name as PrestoSports stores it **and** the player slug, which encodes a stable opaque player ID (e.g. `drakemissamore7nfq`). This is the **source for player slugs** when you need to join across seasons or look up a player profile URL.

Coverage is limited to players with recorded stats in that position group — players who dressed but had no stats will appear in participation but not lineup.

### How they complement each other

| Need | Use |
|---|---|
| Canonical name to match against PBP | `participation.csv` (primary) |
| Position, height, weight, hometown | `players.csv` from `03_scrape_rosters.py` |
| Stable player ID / profile URL | `lineup.csv` from `10_scrape_lineup.py` |
| All players who dressed for a game | `participation.csv` |
| Players with recorded stats | `lineup.csv` |

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
