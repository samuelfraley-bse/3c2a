# DuckDB Pipeline

Milestone 1 of the Foothill DuckDB rebuild.

This subproject is a clean-room restart of the DuckDB pipeline.

See also:

- `METRICS.md` for the canonical football metrics and filter definitions that should drive future reports and dashboards.

Milestone 1 covers the structure pipeline:

- standings
- schedule
- games

Current dependency model:

- `standings` currently discovers team schedule URLs
- `schedule` provides team-sided game rows
- `games` is the canonical one-row-per-game layer derived from `schedule`
- `plays` depends on canonical `games`

In other words, the current working path is:

- `standings -> schedule -> games -> plays`

`build_games` is a derive/canonicalization step, not a separate web scrape.

### Bronze / silver / gold layering

Every stage follows the same three-layer shape:

- **Bronze (raw):** `raw_standings_html`, `raw_schedule_html`, `raw_pbp_html` — append-only, exactly what the source returned, keyed by `run_id`. Never mutated.
- **Silver (parsed/canonical):** `standings`, `schedule`, `games`, `plays` — also append-only and `run_id`-keyed, each a pure function of (raw HTML, parser code). Because raw HTML is kept forever, a parser bug is fixed by re-running a `rebuild_*_from_raw` command against stored raw HTML, never by re-scraping. Both `rebuild_structure_from_raw` (standings/schedule/games) and `rebuild_plays_from_raw` (plays) exist for this reason.
- **Gold (current + analytics):** the `v_*_current` views and everything built on top of them (`v_play_context_current`, `v_team_season_offense_current`, etc.). Logic-only, so metric definitions can change freely via `CREATE OR REPLACE VIEW` without touching stored data.

`pipeline_runs` tracks every run across every stage in one shared table, distinguished by an explicit `stage` column (`'structure'`, `'plays'`, `'field_position'`, later `'lineups'`). Each `v_current_<x>_runs` view picks, per season, the most recently `completed` run for its `stage` — so "current" is always resolved automatically from `pipeline_runs`, never tracked manually. A run that fails or gets interrupted is marked `'failed'` and is permanently excluded, so a bad run can never silently become current.

Milestone 2 now covers:

- raw play-by-play HTML
- base `plays` rows tied to canonical `games`
- failed game fetch audit rows
- manual field-position crosswalk workflow
- derived field-position enrichment rows

It intentionally does not include:

- participation
- roster scraping
- player identity resolution

The remaining gaps after this slice are:

- participation joins
- player-name crosswalk application

## What it writes

Default database path:

`duckdb_pipeline/data/foothill.duckdb`

Tables created in Milestone 1:

- `raw_standings_html`
- `raw_schedule_html`
- `standings`
- `schedule`
- `games`
- `pipeline_runs`

Additional tables for the next slice:

- `raw_pbp_html`
- `plays`
- `failed_game_fetches`
- `field_position_prefixes`
- `field_position_crosswalk`
- `play_field_positions`

New source (official PrestoSports JSON, not derived from `plays`):

- `raw_lineup_json` — bronze table. See `LOGS.md` (2026-07-05) for the full discovery narrative and decoded field legend. Fetch with:

  ```powershell
  uv run --active scrape_lineup_json --season 2025-26 --team-slug foothill --delay 20
  ```

  `players`/`teams` are conference-wide singletons, so `--team-slug` only needs to be one real team (any team) to pull data covering all 66 — it does not loop over teams.

- `player_lineup_stats` / `v_player_lineup_stats_current` — silver table, parsed from `raw_lineup_json`'s `players_json` rows. **This is the Team Leaders source** (Passing/Rushing/Receiving/Tackles/Sacks) — see `METRICS.md` for the full column list. Parse with:

  ```powershell
  uv run --active parse_lineup_stats --season 2025-26
  ```

  (defaults to the latest completed `scrape_lineup_json` run). One row per player per season, covering every team in the conference in a single parse — not per-team, not per-position, and no player-name-crosswalk dependency (comes with a stable `player_id`, jersey number, and class year directly from the source).

This source covers more than Team Leaders, documented and confirmed working but not yet built on:
  - **Player *game logs*** — a separate, per-player endpoint (found via each player's own profile page) gives game-by-game stat lines keyed to the same `game_id`s already used everywhere else in this pipeline, not just season totals. Not yet fetched by `scrape_lineup_json` — needs one request per player of interest, scoped separately.
  - **Team per-game box scores** — embedded in the team-page JSON's schedule/events list: points, total yards, comp-att-int, time of possession, penalties, for both the team and its opponent, per game. This is effectively the "box score layer" previously proposed as future work (see `LOGS.md` 2026-06-30) — already available here instead of needing a new scrape.
  - **Team season totals for all 70 conference teams** — a second, independent cross-check source for this pipeline's own `v_team_season_offense_current`/`_defense_current` (already spot-verified to match exactly).
  - **Confirmed NOT available here, exhaustively** (searched every rendering script's endpoint-passing convention, not just inferred): play-by-play, drive summaries, participation, and starters. The whole boxscore/game-detail page family (`view=plays`/`drives`/`participation`/`starters`) is old-style server-rendered HTML with no JSON backing, unlike the team/player stats pages — the existing `parse_pbp_html` scraper remains the only source for real play-level data. The Drive Summary tab (`view=drives`) turned out to be unnecessary: `plays.drive_id` was already sufficient to build a full drive-level rollup (`v_drives_current` and friends, see below) directly from the existing play-by-play scrape, no HTML parsing needed.

Core helper views:

- `v_current_structure_runs`
- `v_current_plays_runs`
- `v_current_field_position_runs`
- `v_current_lineup_stats_runs`
- `v_current_runs`
- `v_games_current`
- `v_schedule_current`
- `v_standings_current`
- `v_plays_current`
- `v_play_field_positions_current`
- `v_play_context_current`
- `v_team_game_offense`
- `v_team_game_offense_current`
- `v_team_season_offense_current`
- `v_team_game_defense_current`
- `v_team_season_defense_current`
- `v_team_season_offense_ranked_current`
- `v_team_season_defense_ranked_current`
- `v_team_game_situation_offense_current` / `_defense_current`
- `v_team_season_situation_offense_current` / `_defense_current`
- `v_team_season_situation_offense_ranked_current` / `_defense_ranked_current`
- `v_player_game_passing_current` / `v_player_season_passing_current`
- `v_player_lineup_stats_current`
- `v_pbp_coverage_by_team_current`
- `v_team_game_points_current` / `v_team_season_points_current` / `v_team_season_points_ranked_current`
- `v_drives_current`
- `v_team_game_drives_offense_current` / `_defense_current`
- `v_team_season_drives_offense_current` / `_defense_current`
- `v_team_season_drives_offense_ranked_current` / `_defense_ranked_current`

## Run

From the repo root:

```powershell
python -m duckdb_pipeline.cli --season 2025-26
```

From inside `duckdb_pipeline/`:

```powershell
uv run python -m duckdb_pipeline.cli --season 2025-26
```

Or via the console script:

```powershell
uv run --active scrape_season_structure --season 2025-26
```

To refresh the current schema and `v_*` views inside an existing database file:

```powershell
uv run --active refresh_duckdb_views --db-path duckdb_pipeline/data/foothill.duckdb
```

## Analyst dashboard

A local Streamlit dashboard for clicking through team offense/defense passing/rushing stats, filtering by season/week/team/quarter/down/distance/score-margin/drive-number. See `DASHBOARD_SPEC.md` for the full content spec (tabs, columns, filters).

```powershell
uv run --active streamlit run src/duckdb_pipeline/dashboard_app.py
```

Opens `http://localhost:8501` in your browser. The database path is a sidebar field (defaults to `data/foothill.duckdb`) — the app only ever opens a **read-only** connection, so there's no risk of it mutating data. `dashboard_data.py` is the pure query layer (no Streamlit import); `dashboard_app.py` is presentation-only, same split as `report_data.py`/`report_build.py`.

To re-parse stored raw standings/schedule HTML into a fresh `standings`/`schedule`/`games` run, without re-scraping:

```powershell
uv run --active rebuild_structure_from_raw --season 2025-26
uv run --active rebuild_structure_from_raw --season 2025-26 --source-structure-run-id 471e4a97-8818-40b4-822e-93cf8134dc02
```

To scrape base play-by-play using an existing `games` run:

```powershell
uv run --active scrape_season_plays --season 2025-26
uv run --active scrape_season_plays --season 2025-26 --source-run-id 471e4a97-8818-40b4-822e-93cf8134dc02
uv run --active scrape_season_plays --season 2025-26 --source-run-id 471e4a97-8818-40b4-822e-93cf8134dc02 --limit 5
```

Optional flags:

```powershell
python -m duckdb_pipeline.cli --season 2025-26 --delay 2.0
python -m duckdb_pipeline.cli --season 2025-26 --db-path duckdb_pipeline/data/foothill.duckdb
```

For plays:

```powershell
uv run --active scrape_season_plays --season 2025-26 --delay 5.0
uv run --active scrape_season_plays --season 2025-26 --source-run-id <structure_run_id>
uv run --active scrape_season_plays --season 2025-26 --source-run-id <structure_run_id> --limit 3
```

For large full-season runs, treat the process as incomplete until the console prints `DONE run_id=...`. The `WRITE plays ...` line is only the start of the DuckDB insert/commit phase and may be followed by several minutes of database work before the prompt returns.

## Working with current runs

The base tables remain append-only and auditable by `run_id`.

For day-to-day analysis, prefer the helper views instead of hardcoding run IDs in every query:

```sql
select *
from v_current_runs;
```

```sql
select *
from v_plays_current
limit 100;
```

```sql
select *
from v_games_current
order by game_date, game_id;
```

```sql
select *
from v_standings_current
order by wins desc, team_name;
```

```sql
select *
from v_team_season_offense_current
order by pass_yds desc;
```

```sql
select *
from v_play_context_current
where offense = 'Foothill'
limit 100;
```

```sql
select *
from v_team_season_defense_current
order by opp_pass_yds asc;
```

```sql
select *
from v_pbp_coverage_by_team_current
order by missing_pbp_games desc, team_name;
```

This gives the project two layers:

- raw audited storage in tables like `plays`, `games`, and `pipeline_runs`
- operator-facing working surfaces in `v_*_current`

When a better reparse becomes the blessed working run, the current views automatically point at the latest completed run for that season.

## Derived analytics views

The first analytics-oriented view layer now sits on top of `v_plays_current`.

`v_play_context_current` is the main per-play working surface for future reports. It adds:

- `week` as team game order within season
- `distance_bucket`
- normalized `yardline_100`
- `field_zone`
- `is_success`
- `explosive_rush`
- `explosive_pass`
- `is_explosive`
- `is_stuffed`
- `is_safety` (pass-through from `plays`)
- `is_defensive_td` (pick-six, resolved at parse time; fumble-return TD, resolved here using the field-position crosswalk — see `METRICS.md`)
- `home_score` / `away_score` (pre-play running score, derived from `plays` scoring events)
- `score_margin` / `score_margin_bucket`

`score_margin` accounts for offensive TD/FG/PAT/two-point, safeties, and defensive/return touchdowns (pick-six and fumble-return). The one remaining known gap is blocked-kick-return touchdowns, which aren't covered by either resolution path — confirmed real but rare (~5 instances in the season). See `METRICS.md` for details.

This feeds the first mirrored team rollups:

- `v_team_game_offense_current`
- `v_team_season_offense_current`
- `v_team_game_defense_current`
- `v_team_season_defense_current`

These are intended to support the first automated `team_report` implementation before any dashboard work.

For field-position review and enrichment:

```powershell
uv run --active prepare_field_positions --season 2025-26 --source-plays-run-id <plays_run_id>
uv run --active prepare_field_positions --season 2025-26 --source-plays-run-id <plays_run_id> --review
uv run --active resolve_field_position_prefix --season 2025-26 --source-plays-run-id <plays_run_id> --game-id 20250830_2nv6 --prefix "LONG BEA" --canonical-team "Long Beach"
uv run --active resolve_field_position_prefix --season 2025-26 --source-plays-run-id <plays_run_id> --queue-index 4 --which a --canonical-team "Long Beach"
uv run --active apply_field_positions --season 2025-26 --source-plays-run-id <plays_run_id>
```

## Manual field-position workflow

The intended stable loop is:

1. Scrape `plays` for a season or week.
2. Detect per-game prefixes with `prepare_field_positions`.
3. Review the unresolved queue output for each game:
   - each unresolved game gets a sequential `queue` number
   - canonical teams are shown
   - both observed prefixes are shown
4. Resolve one prefix with `resolve_field_position_prefix`.
   - the other prefix is auto-assigned to the other team
   - this can be done either by explicit `--game-id` and `--prefix`
   - or by `--queue-index` and `--which a|b` when you are just working top-to-bottom through new games
5. Materialize `play_field_positions` with `apply_field_positions`.

This keeps:

- raw `plays` unchanged
- manual decisions auditable in `field_position_crosswalk`
- derived field-position data rebuildable when logic changes

## Team-stat accounting note

For future team-level offensive aggregates, the working rule is:

- official rushing totals should include sacks
- dropback context should still treat sacks as pass-play outcomes

That means the next aggregate layer should likely expose both:

- official/accounting flags such as `is_rush_att`
- context flags such as `is_dropback`

Expected interpretation:

- `play_type = 'rush' and not is_sack` -> designed run
- `play_type = 'pass'` -> pass attempt
- `is_sack = true` -> sack
- `is_rush_att = true` for `rush` plays and sacks, so team rushing matches the source box score
- `is_dropback = true` for pass attempts and sacks, so pass-game context stays analytically useful

The current explicit `plays`-level flag split is:

- `is_dropback`: pass-play context, including sacks
- `is_conversion`: PAT / two-point try context, excluded from standard offensive passing and rushing totals
- `is_pass_attempt`: official forward pass attempts only
- `is_rush_attempt`: official team rushing attempts, including sacks

So a sack should read as:

- `is_dropback = true`
- `is_pass_attempt = false`
- `is_rush_attempt = true`

And a two-point pass try should read as:

- `play_type = 'two_point'`
- `is_conversion = true`
- `is_dropback = false`
- `is_pass_attempt = false`
- `is_rush_attempt = false`

That keeps try plays in the event log while ensuring they contribute no normal passing, rushing, or interception stats by construction.

## Source reconciliation note

For now, the `plays` table should be treated as the source of truth for play-derived modeling and aggregates built directly from public play-by-play.

That matters because some `3C2A` game pages appear internally inconsistent:

- the public `?view=plays` event log can disagree with
- the game-level box-score stat table or season aggregate pages

Current known example:

- `20251116_5n02` (`Santa Monica at Victor Valley`, `November 16, 2025`)
- public play-by-play supports `3` Victor Valley passing touchdowns
- the box-score passing table credits `Seth Burbine` with `4`
- the scoring summary also contains at least one mislabeled row on the source site

So the current policy is:

- trust public play-by-play for `plays` and play-derived aggregates
- log game-level source discrepancies when discovered
- defer any official box-score reconciliation into a later, explicit audit layer rather than silently overriding parsed play events

## Review queue workflow

For in-season use, the intended operator flow is:

1. scrape new `plays`
2. run `prepare_field_positions --review`
3. the console shows the next unresolved game
4. answer `a` or `b` for which prefix belongs to `team_1`
5. let the command auto-assign the other side
6. continue until the queue is empty, or use `s` to skip and `q` to stop

That avoids needing to know `game_id` or the raw prefix string ahead of time, which makes weekly manual review much less fragile.

The prompt intentionally resets to `Queue 1` after each resolution, because it always reloads the next unresolved game instead of preserving a stale index from the earlier list.

## Historical vs in-season

The current field-position review flow is intentionally optimized for week-by-week in-season ingest:

1. scrape the newest games
2. run `prepare_field_positions --review`
3. resolve the small unresolved queue
4. apply the derived field-position layer

That is expected to stay stable because the manual review surface per week should remain small.

Historical backfill is a little different. The same review flow works today, and it is fine to keep using it for now, but if the historical scope gets large enough we may want a later assist layer such as:

- batched review
- suggested mappings
- partial automation with manual confirmation

For now, treat historical mode as manual-first and flag larger-scale automation as a future improvement rather than a requirement for the current pipeline.

## Test

From the repo root:

```powershell
python -m unittest discover duckdb_pipeline/tests
```

From inside `duckdb_pipeline/`:

```powershell
uv run python -m unittest discover tests
```
