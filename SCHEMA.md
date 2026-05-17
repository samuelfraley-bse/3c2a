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
| `game_id` | string | Canonical game identifier: `{slug}_{HOME}_{AWAY}`, e.g. `20251018_1561_MONTEREY_PENINSULA_SEQUOIAS` |
| `game_date` | string | Date in `YYYYMMDD` format |
| `home_away` | string | `home` or `away` from this team's perspective |
| `opponent` | string | Opponent team name |
| `result` | string | Game result from this team's perspective, e.g. `W, 42-7` or `L, 20-17` |
| `pbp_url` | string | Full URL to the play-by-play page for this game |

---

## plays.csv

One row per play across all scraped games. Source: each game's play-by-play page, parsed by `parse_pbp.py`. Plays nullified by penalty (`NO PLAY`) are excluded.

### Game context

| column | type | description |
|---|---|---|
| `game_id` | string | Matches `game_id` in `schedule.csv` |
| `home_team` | string | Home team name |
| `away_team` | string | Away team name |
| `play_id` | int | Sequential play number within the game (1-based) |
| `drive_id` | int | Sequential drive number within the game (1-based) |
| `drive_start_time` | string | Clock time at drive start, e.g. `14:54` |
| `quarter` | int | Quarter number (1–4, or 5+ for OT) |
| `down` | int | Down (1–4), null for non-scrimmage plays |
| `distance` | int | Yards to go, null for goal-line or non-scrimmage plays |
| `field_position` | string | Field position token, e.g. `MONTEREY17` |
| `offense` | string | Team name with the ball |
| `defense` | string | Team name on defense |

### Play classification

| column | type | description |
|---|---|---|
| `play_type` | string | `rush`, `pass`, `punt`, `kickoff`, `field_goal`, `pat`, `two_point`, `penalty` |
| `ball_carrier` | string | Primary player name (rusher, passer, kicker) |
| `targeted_receiver` | string | Receiver name on pass plays (if named) |
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

These match the official 3C2A box score definitions:

- **Net rushing yards** = sum of `yards_gained` where `play_type='rush'` (includes sack yards, which are negative)
- **Rushing attempts** = count of `play_type='rush'` rows (includes sacks)
- **Net passing yards** = sum of `yards_gained` where `play_type='pass'` and `pass_result in ('complete', 'td')`
- **Pass attempts** = count of `play_type='pass'` and `is_sack=False`
- **Completions** = count of `play_type='pass'` and `pass_result in ('complete', 'td')`
- **Dropbacks** = pass attempts + sack count
- **Sacks** = count/sum where `is_sack=True` (yards are negative)

---

## Join keys

```
standings.team_name  <->  schedule.team_name
schedule.game_id     <->  plays.game_id
```
