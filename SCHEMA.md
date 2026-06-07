# Dataset Schema

All data is scraped from [3c2asports.org](https://3c2asports.org) (PrestoSports platform) for the 3C2A California Community College Athletic Association football season.

Outputs live in `outputs/{season}/` (e.g. `outputs/2025-26/`).

---

## standings.csv

One row per team per season. Source: the season standings page.

| column | type | description |
|---|---|---|
| `season` | string | Season identifier, e.g. `2025-26` |
| `conference` | string | Conference name as shown on the standings page |
| `team_name` | string | Full team name, e.g. `Foothill` |
| `team_id` | string | PrestoSports internal team ID (opaque string) |
| `schedule_url` | string | Full URL to the team's schedule page |
| `conf_gp` | int | Conference games played |
| `conf_w` | int | Conference wins |
| `conf_l` | int | Conference losses |
| `conf_t` | int | Conference ties |
| `conf_pct` | float | Conference win percentage |
| `overall_gp` | int | Overall games played |
| `overall_w` | int | Overall wins |
| `overall_l` | int | Overall losses |
| `overall_t` | int | Overall ties |
| `overall_pct` | float | Overall win percentage |

---

## schedule.csv

One row per team-game pair. Each game appears twice (once for each team), so join on `game_id` to get both sides. Source: each team's schedule page.

| column | type | description |
|---|---|---|
| `season` | string | Season identifier, e.g. `2025-26` |
| `team_name` | string | The team whose schedule this row came from |
| `team_id` | string | PrestoSports internal team ID |
| `game_id` | string | Canonical game identifier using the stable boxscore slug only, e.g. `20251018_1561` |
| `game_date` | string | Date in `YYYYMMDD` format |
| `home_away` | string | `home` or `away` from this team's perspective |
| `opponent` | string | Opponent team name |
| `result` | string | Game result from this team's perspective, e.g. `W, 42-7` or `L, 20-17` |
| `pbp_url` | string | Full URL to the play-by-play page for this game |
| `schedule_home` | string | Home team name as seen on the schedule page for this row's game |
| `schedule_away` | string | Away team name as seen on the schedule page for this row's game |

---

## games.csv

One row per unique game slug, derived from `schedule.csv`. This is the canonical game table and should be the primary join layer for assigning teams to a game.

| column | type | description |
|---|---|---|
| `season` | string | Season identifier, e.g. `2025-26` |
| `game_id` | string | Canonical game identifier using the stable boxscore slug only, e.g. `20251018_1561` |
| `game_date` | string | Date in `YYYYMMDD` format |
| `pbp_url` | string | Full URL to the play-by-play page for this game |
| `schedule_home` | string | Home team name as seen on one contributing schedule row |
| `schedule_away` | string | Away team name as seen on one contributing schedule row |
| `home_team_canonical` | string | Canonical home team inferred from paired schedule rows when available |
| `away_team_canonical` | string | Canonical away team inferred from paired schedule rows when available |
| `team_1` | string | First canonical participant from paired schedule rows |
| `team_2` | string | Second canonical participant from paired schedule rows |
| `schedule_row_count` | int | Number of `schedule.csv` rows grouped into this game |
| `unique_team_count` | int | Number of distinct `schedule.team_name` values grouped into this game |
| `pairing_status` | string | Pairing quality flag: `paired`, `duplicate-rows`, `single-sided`, `over-paired`, or `incomplete` |

---

## plays.csv

One row per play across all scraped games. Source: each game's play-by-play page, parsed by `parse_pbp.py`. Plays nullified by penalty (`NO PLAY`) are excluded.

### Game context

| column | type | description |
|---|---|---|
| `game_id` | string | Matches `game_id` in `schedule.csv` |
| `home_team` | string | Home team name |
| `away_team` | string | Away team name |
| `schedule_home` | string | Home team name passed through from `schedule.csv` for the same game |
| `schedule_away` | string | Away team name passed through from `schedule.csv` for the same game |
| `play_id` | int | Sequential play number within the game (1-based) |
| `drive_id` | int | Sequential drive number within the game (1-based) |
| `drive_start_time` | string | Clock time at drive start, e.g. `14:54` |
| `quarter` | int | Quarter number (1–4, or 5+ for OT) |
| `down` | int | Down (1–4), null for non-scrimmage plays |
| `distance` | int | Yards to go, null for goal-line or non-scrimmage plays |
| `field_position` | string | Field position token, e.g. `MONTEREY17` |
| `field_pos_side` | string | `own` or `opponent` relative to the offense; blank if prefix unresolved |
| `yardline_raw` | int | Numeric yardline extracted from `field_position`, e.g. `MONTEREY17` → `17` |
| `yardline_100` | int | Yards to the opponent end zone: own 25 → `75`, opponent 25 → `25` |
| `offense` | string | Team name with the ball |
| `defense` | string | Team name on defense |

### Play classification

| column | type | description |
|---|---|---|
| `play_type` | string | `rush`, `pass`, `punt`, `kickoff`, `field_goal`, `pat`, `two_point`, `penalty` |
| `passer` | string | Passer name on pass plays (including sacks); null otherwise |
| `rusher` | string | Ball carrier name on rush, kickoff, punt, field_goal, pat, and two_point plays; null otherwise |
| `receiver` | string | Targeted receiver name on pass plays (if named); null otherwise |
| `pass_result` | string | `complete`, `incomplete`, `int`, `td` — null for non-pass plays |
| `yards_gained` | int | Net yards on the play. **Sack yards are negative and count against rushing, not passing.** |

### Outcomes

| column | type | description |
|---|---|---|
| `is_td` | bool | True if the play resulted in a touchdown |
| `is_sack` | bool | True if the play was a sack (play_type=`pass`) |
| `is_fumble` | bool | True if a fumble occurred |
| `fumble_recovered_by` | string | `HOME` or `AWAY` token indicating recovery team |

### Penalties

| column | type | description |
|---|---|---|
| `is_penalty` | bool | True if a penalty was called (play may still count) |
| `penalty_team` | string | Team that committed the penalty |
| `penalty_type` | string | Penalty description, e.g. `holding`, `offside` |
| `penalty_player` | string | Player flagged (if named) |
| `penalty_yards` | int | Penalty yardage |

### Special teams / scoring

| column | type | description |
|---|---|---|
| `fg_result` | string | `good` or `missed` for field goals; `good` or `failed` for PATs |

### Tackling

| column | type | description |
|---|---|---|
| `tackler_1` | string | Primary tackler (if named) |
| `tackler_2` | string | Assist tackler (if named) |

### Raw data

| column | type | description |
|---|---|---|
| `raw_text` | string | Original play description text from the source HTML |

---

## Stat conventions

Sacks are stored as `play_type='pass', is_sack=True`. Conceptually a sack is a dropback — the QB dropped back to pass and was tackled. The NCAA box score convention, however, counts sacks as rush attempts and charges their negative yardage to the rushing total. Both conventions are validated against official 3C2A totals.

QB scrambles (QB tucks and runs) appear as `play_type='rush'` in the PBP text and are indistinguishable from designed runs.

| Metric | Formula |
|---|---|
| **Dropbacks** | `play_type='pass'` (pass attempts + sacks) |
| **Pass attempts** | `play_type='pass'` and `is_sack=False` |
| **Completions** | `play_type='pass'` and `pass_result in ('complete', 'td')` |
| **Net passing yards** | sum of `yards_gained` where `play_type='pass'` and `pass_result in ('complete', 'td')` |
| **Rush attempts (NCAA box)** | count where `play_type='rush'` or `is_sack=True` |
| **Net rushing yards (NCAA box)** | sum of `yards_gained` where `play_type='rush'` or `is_sack=True` (sack yards are negative) |
| **Sack count / yards** | `is_sack=True`; yards are negative, stored on the `play_type='pass'` row |

---

## Player name sources

Two complementary sources are used for player identity:

| Source | File | Used for |
|---|---|---|
| Game participation pages (`?view=participation`) | `participation.csv` | Primary canonical name source; covers all teams including those with no roster page. Includes players who dressed but are not listed on the official website roster (walk-ons, late additions). |
| Team roster pages | `players.csv` | Position (`pos`), height, weight, hometown. Not used as the primary name source — roster pages are incomplete for some teams (403 errors, JS-rendered) and miss players not officially listed. |

`participation.csv` contains both participants (`participated=true`) and did-not-play players (`participated=false`). Note that DNP player names may be truncated in the source HTML.

---

## Join keys

```
standings.team_name  <->  schedule.team_name
schedule.game_id     <->  games.game_id
games.game_id        <->  plays.game_id
games.game_id        <->  participation.game_id
```
