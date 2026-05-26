# Foothill 2025-26 Season Report — Analysis Plan

## Data Source
`outputs/2025-26/plays_with_side_v2.csv` — 56,067 plays across 66 CA JC teams.
Scrimmage plays only (`play_type` in `rush`, `pass`). Rankings are against all 66 teams.

## Shared Definitions (helpers.py)

| Concept | Definition |
|---|---|
| **Success rate** | 1st down: yards ≥ 40% of distance; 2nd down: yards ≥ 60% of distance; 3rd/4th down: yards ≥ distance (conversion) |
| **Explosive play** | Pass ≥ 20 yards or rush ≥ 10 yards |
| **Passing down** | 2nd & 8+, or 3rd/4th & 5+ |
| **Early down** | 1st & 2nd downs that are NOT passing downs |
| **Red zone** | `field_pos_side == 'opponent'` and `yardline_100 <= 20` |
| **Run stuff** | Rush play with yards_gained ≤ 0 |
| **Completion** | `pass_result` in `complete` or `td` |

### Ranking direction
- **Offense metrics**: higher = better (rank 1 = highest value)
- **Defense metrics**: lower yards/rates allowed = better (rank 1 = lowest value); neutral rate stats (% plays pass/run) rank higher = better

### Output format
Each table produces:
- `{table}_offense.csv` — all 66 teams, all metrics + rank columns
- `{table}_defense.csv` — same for defensive role
- `{table}_report.csv` — side-by-side: `Offense | Metric | Defense` with Foothill's value and ordinal rank (e.g. `337 (22nd)`)

---

## Known Data Issue
Game `20250906_tjag` (Foothill vs Redwoods): offense/defense labels are **swapped** in the CSV. Foothill shows 173 yards on 45 plays; site shows 317. Needs fix upstream in the scraper before final numbers are trusted.

---

## Tables

### 1. Production Stats ✅ (`table_production.py`)
Filter: all scrimmage plays

| Metric | Group |
|---|---|
| % Plays Pass | Passing |
| Total Yards | Passing |
| Yards per Attempt | Passing |
| TD | Passing |
| Comp Pct | Passing |
| 10+ Yd Completions | Passing |
| 20+ Yd Completions | Passing |
| Success Rate | Passing |
| % Plays Run | Rushing |
| Total Yards | Rushing |
| Yards Per Attempt | Rushing |
| TD | Rushing |
| 10+ Yard Rushes | Rushing |
| 20+ Yard Rushes | Rushing |
| Success Rate | Rushing |

---

### 2. Third Down Report (`table_third_down.py`)
Filter: `down == 3`

| Metric | Notes |
|---|---|
| Attempts / Conversions | count of 3rd downs; conversions = yards >= distance |
| Average Yards to Go | mean distance |
| % Third and Long (7+) | distance >= 7 |
| % Third and Short (<3) | distance < 3 |
| Yards per Play | mean yards_gained |
| Explosive Plays | explosive flag |
| Run / Pass Plays | counts |
| % Run Conversion | rush conversion rate |
| % Pass Conversion | pass conversion rate |
| Dropbacks / Sack % | sacks / pass attempts |
| Turnovers | INT + fumbles lost |
| Penalty Yards | sum penalty_yards |

Defense ranking: lower conversion rate allowed = better; lower yards per play = better.

---

### 3. Red Zone Report (`table_redzone.py`)
Filter: `redzone == True` (opponent side, yardline_100 ≤ 20)

| Metric | Notes |
|---|---|
| Drives Inside 20 | distinct drive_ids in redzone |
| TD % | TD drives / total RZ drives |
| FG % | FG drives / total RZ drives |
| Stop % | drives with no score / total RZ drives (defense) |
| % Run Plays | rush / total plays |
| Yards per Carry | rush YPA |
| % Run Stuff | stuffed rushes / rush plays |
| Rush TD | rush TDs |
| % Pass Play | pass / total plays |
| Comp Pct | completions / attempts |
| Pass TD | pass TDs |
| Int | interceptions |

Drive-level metrics require grouping by `drive_id` within redzone entries.

---

### 4. Early Down Report (`table_early_down.py`)
Filter: `early_down == True` (1st & 2nd, not passing downs)

| Metric | Notes |
|---|---|
| Yards per Play | |
| Success Rate | |
| Explosive % | explosives / plays |
| % Plays Rush | |
| Rushing YPA | |
| Run Stuff % | stuffed rushes / rush plays |
| Explosive Runs | count |
| % Plays Pass | |
| Passing YPA | |
| Pass Comp % | |
| Sack % | sacks / pass attempts |
| Turnovers | |
| Penalty Yards | |

---

### 5. Passing Down Report (`table_passing_down.py`)
Filter: `passing_down == True` (2nd & 8+, 3rd/4th & 5+)

Same metrics as Early Down Report.

---

### 6. 4th Down Decision Report (`table_fourth_down.py`)
Filter: `down == 4` (exclude PAT/FG — scrimmage plays only already handles this)

| Metric | Notes |
|---|---|
| Attempts / Conversion % | |
| % Pass | |
| % Run | |
| Rush Attempts / Convert | |
| Pass Attempts / Convert | |
| Explosive Plays | |

---

### 7. Explosive Plays (`table_explosives.py`)
Filter: `explosive == True`

| Metric | Notes |
|---|---|
| Total Explosives / Rate | count and explosives / total plays |
| Explosive Pass / Rate | |
| Explosive Runs / Rate | |
| Explosive Early Down / Rate | explosive & early_down |
| Explosive Third Down / Rate | explosive & down == 3 |

---

### 8. Finishing Drives (`table_finishing_drives.py`)
Drive-level table — group by `drive_id`, summarize each drive.

| Metric | Notes |
|---|---|
| Avg Starting Pos | mean yardline_100 at drive start |
| Plays Per Drive | mean play count per drive |
| Scoring Rate | drives with TD or FG / total drives |
| TD Rate | drives ending in TD / total drives |
| Three Out Rate | drives with ≤ 3 plays and no score |

Skipping for now — needs drive-level aggregation logic.

---

### 9. Hidden Yards (`table_hidden_yards.py`)
Points per drive segmented by starting field position.

| Segment | Definition |
|---|---|
| Backed Up | own side, yardline_100 >= 75 |
| Normal | own side, 26 ≤ yardline_100 < 75 |
| Plus | opponent side, yardline_100 > 20 |
| Redzone | yardline_100 ≤ 20 |

Requires scoring outcome per drive — skipping until drive logic is built.

---

### 10. Turnover Swing (`table_turnovers.py`)
Filter: all plays with `is_fumble == True` or `pass_result == 'int'`

| Metric | Notes |
|---|---|
| Interceptions | count |
| Fumbles | `is_fumble == True` |
| Points off Turnovers | requires drive outcome — skip for now |
| Turnover Score Rate | drives following a turnover that score |

---

## Game-by-Game Trend Charts
No ranking needed — Foothill-only, grouped by `game_id`.

| Chart | Metric |
|---|---|
| Success Rate by Game (O/D) | success rate per game, offense & defense |
| Explosive Play Rate by Game | explosives / plays per game |
| Stuff Rate by Game | run_stuff / rush plays per game |
| Third Down Conversions by Game | 3rd down conversion rate per game |
| Early Down Rush Rate by Game | rush / early down plays per game |
| Passing Down Pass Rate by Game | pass / passing down plays per game |
| Avg Starting Position by Game | mean yardline_100 at drive start |
| Penalty Yards by Game | sum penalty_yards per game |
| 1st Half vs 2nd Half Success Rate (O) | split by quarter <= 2 vs > 2 |
| 1st Half vs 2nd Half Success Rate (D) | same, defensive role |

---

## Other Charts

| Chart | Definition |
|---|---|
| Success Rate by Down | success rate for downs 1, 2, 3, 4 |
| Conversion Rate by Yards to Go | group distance into buckets: 1, 2-3, 4-6, 7-10, 10+ |
