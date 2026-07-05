# DuckDB Pipeline Log

## 2026-07-06

### Real bug found and fixed: field_zone labels and avg_start_yardline_100_rank were inverted
- Surfaced while sanity-checking `score_plays.py` output from the new xPass/xYards modeling layer (see below) — not a modeling bug, a pre-existing bug in `v_play_context_current`/the drives ranked views.
- `yardline_100` is distance remaining to the opponent's goal line (confirmed both from `crosswalk.py`'s own formula, `yardline_100 = 100 - yardline_raw` when on the offense's own side, and from real plays — a 1-yard touchdown rush lands at `yardline_100=1`). Lower is closer to scoring, matching the standard nflfastR-style convention.
- Two places in `db.py` were built on the opposite assumption:
  - `field_zone` labels were swapped: `yardline_100 <= 20` (the literal red zone) was labeled `'backed_up'`; `>= 80` (deep in your own territory) was labeled `'red_zone'`. No downstream code read `field_zone`'s value before this was caught (only a test asserted it), so no report/dashboard output was ever wrong from this specific piece — it was latent.
  - **`avg_start_yardline_100_rank` on both `v_team_season_drives_offense_ranked_current` and `_defense_ranked_current` was ranked backwards** — real, shipped metric, live in the Report Prep/dashboard Drives tab. Offense was ranked `DESC` (treating a worse starting position as better); defense was ranked `ASC` (treating a worse opponent-pinning job as better). Confirmed the direction flip against real 2025-26 data before and after the fix (e.g. a team with the actual best average field position, ~7 yardline_100 average, was previously not even in the top 5; after the fix it's correctly rank 1).
- Fixed both in `db.py`, updated `METRICS.md`'s `field_zone` and drives-ranking sections to document the corrected convention and the bug, and fixed the one test assertion in `test_db.py` that depended on the old (wrong) `field_zone` label. Applied to the real database: backed up to `foothill.duckdb.bak-pre-fieldzone-and-drivesrank-fix`, then `refresh_duckdb_views` (a pure view redefinition — no data rows touched).
- Two unrelated, pre-existing data-quality items surfaced while validating this fix, not chased down yet: a blank/`"TEAM"`-placeholder offense name showing up in the drives ranking (likely a tiny-sample artifact from unresolved raw text, e.g. "TEAM rush for loss of..." lines), and a handful of out-of-range `yardline_100` outliers (seen as low as -110345 and as high as 110448) feeding into a couple of games' field position. Worth a follow-up look if `yardline_100`-based metrics ever look off for a specific team/game.

### xPass / xYards modeling layer (v1): a simple, honest baseline
- Built a new `duckdb_pipeline/src/duckdb_pipeline/modeling/` subpackage per the user's request for "a simple run probability/over expected and some expected yards" model, deliberately scoped down from a fuller NGS-style plan discussed earlier (xSuccess, K-Means archetypes, live booth tool, calibration, monotonic constraints, garbage-time filtering, and team-weighting were all explicitly deferred, not built).
- `train_xpass.py`: `HistGradientBoostingClassifier` on `is_dropback` (not `is_pass_attempt` — a sack is a called pass gone wrong, and training on `is_pass_attempt` would miscode every sack as a "run"). `train_xyards.py`: `HistGradientBoostingRegressor` on raw `yards_gained`, `--play-type rush|pass`. Features are pre-snap only (`down`, `distance`, `yardline_100`, `score_margin`, `quarter`, `is_home`, `week`) — team/opponent identity is deliberately never a feature, since these models exist to measure deviation from a team-agnostic baseline.
- Evaluation reports two distinct diagnostics per model rather than one blended score, directly answering the user's original worry ("not overfitting to a few teams or years"): a team-grouped CV within seasons (`GroupKFold`/`StratifiedGroupKFold` by offense), and leave-one-season-out. Real results on the full 3-season dataset (127,878 scrimmage plays): xPass AUC ~0.698 on both diagnostics (near-identical, i.e. no overfitting signal); xYards rush/pass MAE also near-identical across both diagnostics.
- **Real bug caught during training**: the rush-yards population (`is_rush_attempt`) initially included sacks, because this project's `is_rush_attempt` flag deliberately includes sacks for an unrelated reason (the dashboard's pass_pct/rush_pct scrimmage-play denominator convention). That convention doesn't belong in a yardage-regression population — 4,191 sack rows (confirmed via row-count arithmetic: `is_dropback` + `is_rush_attempt` totals didn't match the union count) were mixing pass-blocking outcomes into the "expected rushing yards" population. Fixed: rush population is now `is_rush_attempt AND NOT is_sack`.
- **Honest finding, not a failure**: comparing xYards against a naive "always predict the flat mean" baseline showed only a thin improvement — ~1.8% MAE improvement for rush, ~0.7% for pass. Situational context predicts *what play gets called* (xPass) far better than it predicts *how many yards a given play gains* (xYards) — expected, since per-play yardage is dominated by execution (blocking, missed tackles) that isn't in this feature set. Documented as a real ceiling of this simple approach, with the bucketed/distributional yards model (discussed earlier, deferred) flagged as the more promising next step if a bigger signal is wanted, since situational context likely moves the *shape* of the yardage distribution (P(stuffed), P(explosive)) more than it moves the *mean*.
- Not yet built: writing model output back into DuckDB as a gold table (currently `score_plays.py` outputs a DataFrame/CSV for inspection only).

### Historical backfill started: 2024-25 done (minus lineups), 2023-24 in progress
- First real use of the pipeline against a season other than 2025-26, using the exact command sequence documented in `README.md`'s "Historical vs in-season" section:
  ```powershell
  uv run --active scrape_season_structure --season <season> --delay 5
  uv run --active scrape_season_plays --season <season>
  uv run --active scrape_lineup_json --season <season> --team-slug foothill --delay 20
  uv run --active parse_lineup_stats --season <season>
  ```
- **2024-25**: structure + plays + field position complete (field position auto-refreshed per this session's new auto-refresh feature — no separate `prepare_field_positions`/`apply_field_positions` calls were needed). Lineups (`scrape_lineup_json`/`parse_lineup_stats`) not yet run for this season.
- **2023-24**: kicked off and running as of this entry.
- Not yet independently verified against the database (the file was locked by the in-progress 2023-24 scrape at the time of this entry, so exact row counts weren't queried) — this entry reflects the operator's report of what ran, not a post-hoc DB check. Follow-up: confirm `v_current_runs.field_position_is_stale = false` and real standings/games/plays counts for both seasons once the scrapes are done, and run `scrape_lineup_json`/`parse_lineup_stats` for 2024-25 to close out that season's data.

## 2026-07-05

### Field position: visibility + auto-refresh, so it stops going stale silently
- Follow-up to the real bug found and fixed earlier this session (`avg_start_yardline_100` silently going `NULL` after a reparse because `play_field_positions` was keyed to a stale `plays` run_id). User asked "should we adjust it to not go stale" — decided on both halves rather than either alone: make staleness visible, and auto-refresh in the case that needs no human judgment.
- **Visibility**: added `field_position_is_stale` to the existing `v_current_runs` view (no new view/table needed — it already joined `v_current_plays_runs.plays_run_id` and `v_current_field_position_runs.source_plays_run_id`, the exact two values needed). `true` whenever there's no field_position run at all, or the current one wasn't built from the current plays run.
- **Auto-refresh**: new `_auto_refresh_field_positions(conn, season, source_plays_run_id)` helper in `cli.py`, called at the end of both `main_plays` and `main_rebuild_plays_from_raw` (opt-out via `--skip-field-position-refresh` on both). Reuses the exact same building blocks `prepare_field_positions`/`apply_field_positions` already use (`build_field_position_prefix_rows`, `_preseed_memory_crosswalk_rows`, `_load_field_position_review_queue`, `build_field_position_rows`) rather than duplicating that logic:
  - If prior confirmed crosswalk memory fully resolves every game in the new run (the common case — confirmed this session to auto-resolve 100% of games, twice in a row), applies immediately under a new `stage='field_position'` run. No human needed.
  - If any game is left genuinely unresolved (a new/ambiguous team abbreviation), does **not** auto-apply — that would mean silently accepting an unconfirmed guess — and instead logs exactly which games need `prepare_field_positions --review` + `apply_field_positions`. Staleness stays visible via the view above until that happens.
  - Never fails the plays run/reparse itself if the auto-refresh step errors — that run already succeeded on its own merits; a field-position hiccup is logged as a warning, not a failure.
- Testing this surfaced a real fixture-authoring bug worth noting: the first draft of the "fully auto-resolves" test used a 2-play PBP HTML fixture where both plays happened to *start* from a `FOOTHILL` field position (the `SAN MATE48` token only ever appeared as a play's *ending* location in the play text, never as a play's own starting position) — so only one prefix was ever detected for the game, and the memory-matching logic correctly declined to seed anything (it requires exactly 2 distinct prefixes per game). Fixed by adding back a third play that actually starts from the other team's side of the field (matching the real 3-play fixture already established in `test_parse.py`), not by changing any production code — the auto-refresh logic was correct throughout; the test fixture wasn't representative of a real game yet.
- Added 2 new tests to `test_db.py` (`field_position_is_stale` flips correctly when a new plays run lands, and reads `true` when no field_position run exists at all) and 2 to `test_cli.py` (a full end-to-end `main_rebuild_plays_from_raw` run that auto-applies via prior crosswalk memory, and a direct `_auto_refresh_field_positions` call proving it does *not* auto-apply for a genuinely unresolved prefix). Full suite: 66 tests passing.

### "Report Prep" dashboard tab: raw data for reports/Wk1-Butte-template.pdf, browsable by team pair
- User wants to build the template report by hand (pick two teams, read the numbers, no docx automation needed for this) rather than only through the fixed automated pipeline. Added a second top-level dashboard tab alongside the existing Team Stats grid.
- Reused `report_data.py`'s existing functions directly rather than re-deriving anything: `load_schedule_recap`, `load_production_matchup`, `load_situation_trimmed`, `load_weekly_trends` are the same functions `report_build.py` already uses for the automated docx report — one query layer serving both the fixed report and this interactive tab.
- Added 3 new functions to `report_data.py` for the pieces that didn't exist yet:
  - `load_quick_hitters` — PPG (from this session's `v_team_season_points_ranked_current`) + combined success/explosive rate + YPC/YPA + 3rd-down conversion, split Offense/Defense, all with conference rank. Everything except PPG was already sitting on the offense/defense ranked views from earlier in this session, just never assembled into one place.
  - `load_team_leaders` — top players per category straight from `v_player_lineup_stats_current` (2 QB by `pass_yds`, 2 RB by `rush_yds`, 3 WR by `rec_yds`, 2 by `tackles_total`, 2 by `sacks`), explicitly the section the automated docx report dropped earlier this session due to the player-name-crosswalk problem `player_lineup_stats` was built specifically to avoid.
  - `load_identity` — rush/pass split + yards/play with conference average (confirmed with the user: "conference average" means every team tracked in the season, a plain `AVG()` over the ranked views, not a new data source), field-position/tempo bullets straight from this session's drive-rollup views, rushing/passing bullets, situation run rate, and weekly success-rate trend with a new `_conference_weekly_success_rate` helper (pooled success rate per week across every team, for the "Avg (CA)" comparison line the Identity page's chart needs).
  - Also confirmed with the user: include the Match-Up section in this tab too, since `load_production_matchup`/`load_situation_trimmed` already compute it — no extra work.
- `dashboard_app.py` restructured: the whole existing app now lives under a "Team Stats" tab; "Report Prep" sits alongside it with its own team/opponent/season pickers and `Season Recap | Quick Hitters | Team Leaders | Match-Up | Identity` sub-tabs. Deliberately renders with plain `st.dataframe` tables, not the AgGrid rank-and-sort treatment used elsewhere — this tab is for reading/copying a fixed handful of numbers for one specific matchup, not sorting across ~66 teams.
- Cleaned up an early draft's `source is merged_offense`/`stats_view.endswith(...)` object-identity/string-matching pattern for picking offense-vs-defense columns before it shipped — replaced with an explicit `is_offense: bool` parameter in both `load_quick_hitters` and the new `_identity_side` helper.
- Added 3 new tests to `tests/test_report_views.py` (PPG/success-rate correctness including graceful `None` handling when no third-down plays exist, rush/pass split + conference average across a 2-team fixture, and Team Leaders' per-category ordering/capping including the tackles/sacks categories drawing independently from the same defensive-player pool). Full suite: 62 tests passing.
- Verified against a scratch copy of the real database: Quick Hitters/Team Leaders/Identity numbers all match figures already validated earlier this session (James Maxwell's 1028 pass_yds as the top passer, 60.4%/44.5% rush/pass split, 60.9 avg starting field position). Streamlit server starts cleanly with the new tab.

### Real bug found and fixed: fumble-recovery defensive TDs were miscredited as offensive passing TDs; added sack_rate
- User asked to add sack rate and flagged that passer rating "might be off" — investigated by tracing every `pass_td`/`rush_td` computation site rather than guessing, since the user gave no specific example to anchor on.
- **Confirmed a real bug**: `pass_td`/`rush_td` (and their opponent-facing `opp_pass_td`/`opp_rush_td` mirrors) counted raw `is_td` without checking `is_defensive_td`. A fumble recovered and returned for a score by the *defense* can carry a misleading raw `is_td = true` (the same known parse-time quirk already documented for `is_defensive_td`, e.g. `FULLERTO Ethan`/`MSJC-FB`-style name pollution) — without excluding it, that defensive touchdown was getting miscredited as the offense's own passing/rushing TD. Since `passer_rating` weights TDs at +330, this measurably inflated the affected teams' ratings.
- Confirmed via direct query against the real 2025-26 data: exactly 5 real plays this season hit this case (all on pass plays) — Contra Costa, Bakersfield, West LA, San Diego Mesa, Chabot. Each team's `passer_rating` dropped by roughly 1-1.5 points after the fix (e.g. Bakersfield 113.6 → 112.4). **Foothill's own rating (122.0) was unaffected** — it wasn't one of the 5 teams involved, so this specific bug isn't what the user was seeing if they were looking at Foothill specifically, but it's a real, confirmed, now-fixed data-correctness issue regardless.
- Fixed in all 6 places the `is_td`-without-guard pattern existed: `db.py`'s `v_team_game_offense_current` (added `is_defensive_td` to its narrowed inner projection, since it wasn't previously exposed there), `v_team_game_defense_current` (already had full `v_play_context_current` access), `v_player_game_passing_current`, and `dashboard_data.py`'s re-expressed `pass_td`/`rush_td` formulas (both offense and rushing base sums). Season-level views (`v_team_season_offense_current`/`_defense_current`, `v_player_season_passing_current`) just sum the now-fixed game-level counts, so they inherit the fix automatically.
- **Added `sack_rate`** (`sacks / dropbacks` — not `sacks / pass_att`, since `dropbacks` already includes sacks per this project's own `is_dropback` convention) — this was actually already spec'd as `derived_next` in `METRICS.md` from an earlier session, just never implemented. Added to `v_team_season_offense_ranked_current` (`sack_rate`, rank ascending) and `v_team_season_defense_ranked_current` (`opp_sack_rate`, rank descending — forcing more sacks is good defense), plus `dashboard_data.py`'s Passing tab and `OFFENSE_METRIC_DIRECTION` (lower-is-better), plus dashboard column label/width.
- Added regression tests proving the exact bug scenario in both `test_db.py` and `test_dashboard_data.py` (a fumble-recovery-TD-on-a-pass-play fixture, reusing the `field_position_crosswalk` fixture pattern already established for `is_defensive_td` testing), asserting `pass_td=0`/`opp_pass_td=0` (not 1) and correct `sack_rate`/`opp_sack_rate` values. Full suite: 59 tests passing.
- Applied to the real database: backed up first (`data/foothill.duckdb.bak-pre-passtd-sackrate-fix`), then `refresh_duckdb_views`. Blocked briefly by a file lock from the user's own running `streamlit run` session — waited for them to stop it rather than force-closing anything. Verified the fixed `pass_td`/`passer_rating`/`sack_rate` values directly against the real file afterward, matching the scratch-copy verification exactly.

### Dashboard aesthetics/UX pass: labels, widths, stripes, nested tabs, top filter bar
- User feedback after using the dashboard: raw column names (`comp_pct`) instead of readable labels, every column the same too-wide width, no visual row separation, Team/Grain as radio buttons while Passing/Rushing were already tabs, and filters buried in a sidebar list.
- `dashboard_app.py`: added `COLUMN_LABELS`/`COLUMN_WIDTHS` dicts (readable headers, narrower widths for short count stats like `pass_att`/`pass_td` vs. more room for rate columns and longer labels), applied per-column via `gb.configure_column(...)`; unlisted columns fall back to a humanized default (`col.replace("_", " ").title()`) rather than ever silently showing a raw variable name. Dropped the blanket `minWidth` from 130 to 90.
- Added zebra row striping via `grid_options["getRowStyle"]` (AG-Grid doesn't stripe by default in the `streamlit` theme) — a `JsCode` callback keyed on `rowIndex % 2`.
- Replaced the `st.radio()` Team (Offense/Defense) and Grain (Season/Game) selectors with nested `st.tabs()`, so the whole page is one consistent tab hierarchy: Team → Grain → Passing/Rushing (confirmed Streamlit 1.58 nests tabs fine). Accepted tradeoff: all 8 tab-body combinations' queries now run on every rerun (already true for Passing/Rushing before this), not just the 2 previously visible — fine for a local, single-user, DuckDB-backed tool.
- Moved every data filter (season/week/offense/defense/quarter/down/score-margin/distance/drive-number) from the sidebar into a two-row `st.columns(...)` bar across the top of the main page. `Database path` is the one thing left in the sidebar, since it's a connection setting, not a data filter.
- **Found and fixed a real Rank-column bug from live use**: sorting `pass_yds` ascending, the ranks weren't monotonic (should decrease as yards increase, but jumped around for most rows, with only the last few visible rows correctly ordered). Root cause: AG-Grid doesn't automatically re-invoke a column's `valueGetter` for already-rendered row nodes when the sort changes — only rows freshly drawn into view via virtualization (e.g. newly scrolled into the viewport) get the recomputed value, leaving already-rendered rows showing Rank as of the *previous* sort. Fixed with `grid_options["onSortChanged"]`/`["onFilterChanged"]` handlers that call `params.api.refreshCells({force: true})`, forcing every cell to recompute after any sort or filter change — this is a pure client-side JS wiring, no Python/Streamlit involvement, consistent with `update_on=[]` keeping all of this off the Python round-trip.
- Verified: `uv run python -c "import duckdb_pipeline.dashboard_app"` imports cleanly; full test suite (56 tests, unrelated to this presentation-only change) still passes; `streamlit run` against a scratch copy starts and responds `200`. **Not verified by me**: the actual visual result (label/width/stripe appearance, tab nesting, top filter bar layout) and whether the Rank refresh fix fully resolves the staleness in a real browser — needs the user's own click-through, same limitation as every prior UI change this session.

### Analyst dashboard implemented (Streamlit + AG-Grid)
- Built the dashboard from `DASHBOARD_SPEC.md` (logged below): `dashboard_data.py` (pure query layer, no Streamlit import, mirrors `report_data.py`'s separation of concerns) + `dashboard_app.py` (Streamlit UI, presentation-only).
- Chose Streamlit + `streamlit-aggrid` over Tableau/QuickSight: reuses the same DuckDB connection/query style already in this codebase, runs entirely locally (`uv run streamlit run src/duckdb_pipeline/dashboard_app.py`), no hosting/account/cost. QuickSight was ruled out outright — it wants data in S3/Athena/Redshift and per-user cloud billing, solving a hosting/multi-user problem this project doesn't have.
- `dashboard_data.py::load_team_stats(conn, *, side, grain, family, season, ...)` builds one parameterized query per call against `v_play_context_current` directly (not the existing `v_team_season/game_offense/defense_(ranked_)current` views) — those pre-built views are fixed full-season/game aggregates and can't accept fresh row-level filters (quarter/down/distance/score-margin) ahead of their own `GROUP BY`. This means the metric formulas are **re-expressed** here, not referenced — an accepted, deliberate duplication (not an oversight), guarded against drift by `tests/test_dashboard_data.py`, which asserts that with no situational filters applied, this module's output exactly matches the canonical views' output for the same plays. All 6 new tests passed on the first run, load-bearing evidence the two implementations agree.
- All filter values are bound SQL parameters (`?`), never string-interpolated; only `side`/`grain`/`family` (a small fixed enum, never derived from user input) drive which SQL text gets assembled — no injection surface despite the query being built dynamically.
- The dashboard opens its own **read-only** `duckdb.connect(db_path, read_only=True)` directly, bypassing `db.py`'s `connect()`/`init_db()` (which issues schema-mutating DDL a read-only connection can't run, and which the dashboard has no business doing anyway — schema/view refresh stays a pipeline-CLI concern).
- Rank column: implemented as an AG-Grid `valueGetter` (`node.rowIndex + 1`) via `JsCode`, so it reflects whatever the grid is currently sorted by — deliberately not a precomputed SQL `_rank` column (those stay as-is for the static docx report, where there's no interactivity to hang a dynamic rank off of).
- Verified: `uv run python -c "import duckdb_pipeline.dashboard_app"` imports cleanly; `streamlit run` against a scratch copy of the real DB starts the server and responds `200` on the initial HTTP request. **Not verified by me**: full interactive click-through (filter widgets, tab switching, live sort/reorder behavior in the browser) — that needs an actual browser session, which isn't available in this environment. The query-layer correctness is what's actually load-bearing here, and that's covered by the 6 passing unit tests; the UI itself should be manually clicked through before relying on it.
- **Two UI bugs found from actual manual use** (first real click-through, run against the real `data/foothill.duckdb`): headers truncating to e.g. `"V..."`, and sorting visibly working for an instant then snapping back to the old order.
  - First-pass fix (`fit_columns_on_grid_load=False`, `update_mode=GridUpdateMode.NO_UPDATE`) **did not actually work** — those are an older `streamlit-aggrid` API. The installed version (1.2.1.post2) doesn't expose `fit_columns_on_grid_load` as a real `AgGrid()` parameter at all (it's silently swallowed), and its real rerun-control is a different parameter, `update_on`, not `update_mode`. Root-caused properly the second time by inspecting the actual installed `AgGrid()` signature and the literal dict `GridOptionsBuilder.build()` produces, rather than trusting remembered API shape from an unpinned version.
  - Real cause of the width bug: `GridOptionsBuilder.build()` **always** sets `autoSizeStrategy: {"type": "fitGridWidth"}` in the returned dict, regardless of anything passed to `AgGrid()` — that's what squeezed every column to fit the visible width and fired the "grid coming back with zero width" console warning for whichever tab wasn't currently active. Fixed by overriding `grid_options["autoSizeStrategy"] = {"type": "none"}` directly on the dict after `build()`, since there's no builder method for it.
  - Real cause of the sort-reset bug: `AgGrid()`'s actual default `update_on=['cellValueChanged', 'selectionChanged', 'filterChanged', 'sortChanged']` — `sortChanged` being in that list means every sort click reran the whole Streamlit script and rebuilt `gridOptions` from scratch, discarding the sort that had just visibly applied. Fixed with `update_on=[]`: sorting/filtering/resizing are pure client-side grid state that never needs to round-trip through Python at all.

### Rank column made direction-aware (best-by-metric, not just row position)
- User request: sorting `pass_int` ascending should put the team with the *fewest* interceptions at Rank 1 — even though that row is now at the bottom of the visible (ascending) list. A plain `rowIndex + 1` can't express that; it needs to know each metric's direction of "better."
- Added `dashboard_data.OFFENSE_METRIC_DIRECTION` (True=higher-is-better, False=lower-is-better, None=neutral/count-only stat like `games`/`pass_att`/`dropbacks`) and `metric_direction_for_side(side)`, which inverts every non-neutral entry for Defense tabs — same column name means "allowed"/"forced" there instead of "gained"/"taken" (e.g. `pass_yds` is higher-is-better on Offense, lower-is-better on Defense; `pass_int`/`sacks`/`run_stuff_rate` flip the other way, since those are good things for a defense to force). Ported the direction choices directly from the existing `RANK()` columns already in `db.py`'s `v_team_season_offense_ranked_current`/`_defense_ranked_current`, not reinvented.
- `dashboard_app.py::_rank_value_getter(side)` builds a `JsCode` valueGetter that reads the grid's current sort state via `params.api.getColumnState()`, looks up the sorted column's direction in the embedded map (JSON-serialized straight from the Python dict), and only reverses row position (`total - idx` instead of `idx + 1`) when the current sort direction doesn't already put the best team first. Columns with no direction entry (team_name, game_id, week) just fall back to plain row position, which is the only sensible behavior for a non-metric column anyway.
- Added `MetricDirectionTests` in `tests/test_dashboard_data.py` (pure-function tests, no DB needed) covering: offense map unchanged, defense inverts non-neutral entries correctly (spot-checked `pass_yds` and `pass_int` by name, not just presence), neutral entries stay neutral on both sides, invalid `side` raises. Full suite: 54 tests passing.

### Game grain: added `opponent`; pinned Rank + Team columns
- User request: on Game-grain tabs, show who each row's team actually played that game, and keep Rank/Team visible while scrolling through the (now horizontally-scrolling, since the width-squeeze fix) stat columns.
- `dashboard_data.load_team_stats`: when `grain="game"`, the inner query now also selects `MAX({opponent-side column}) AS opponent` (the other team in that specific game — safe as a `MAX()` since every play in a team's game row shares the same opponent) and passes it through in the outer `SELECT`. Season-grain rows deliberately do **not** get an `opponent` column — a team faces a different opponent every week at that grain, so there's no single value to show. Added `test_game_grain_includes_opponent` (checks both offense- and defense-side output) and `test_season_grain_has_no_opponent_column` to lock this in; all 56 tests passing.
- `dashboard_app.py::render_grid`: pinned the `team_name` column (`headerName="Team"`) to the left, alongside the already-pinned Rank column, via `GridOptionsBuilder.configure_column(..., pinned="left")`.
- Updated `DASHBOARD_SPEC.md` to reflect both the `opponent` column and the actual (direction-aware) Rank behavior, since the original spec's description was simpler than what was ultimately built based on live feedback.

### Analyst dashboard spec (DASHBOARD_SPEC.md) — content locked before choosing a tool
- Motivation: after the view-stabilization pass below, the user wanted to step back from automating more reports and build a click-through analyst dashboard instead — the original plan before reports took over. Wrote `DASHBOARD_SPEC.md` to lock down tabs/metrics/filters as a documentation-only deliverable, deliberately before picking any dashboard tool.
- Key insight (the user's own): filters like quarter/score-margin/down/distance/drive-number aren't a separate architectural tier — they're just additional `WHERE` clauses on `v_play_context_current` ahead of the same team-level aggregation already used everywhere else in this schema. One parameterized query per tab, not a combinatorial pile of new views.
- 8 tabs: Team Offense/Defense × Season/Game × Passing/Rushing. Season and Game are genuinely different `GROUP BY` grains (`team` alone vs. `team, game_id`), not the same query with a filter toggled — caught and corrected mid-review after an earlier draft wrongly collapsed them.
- Rank column: one dynamic column reflecting whatever the table is currently sorted by (a UI/grid concern), not a database column — deliberately does not reuse the existing per-metric `<metric>_rank` window-function columns built for the static docx report.
- `drive_id` used as-is for the "drive number" filter (single sequential counter per game, shared across both teams' possessions) — confirmed with the user, no per-team-possession transform needed.
- Explicitly out of scope for v1: dashboard tool choice, PPG, Team Leaders tabs, any write/edit capability.

### Stabilized gold views before building the report: drives, points/PPG, explosive/success/stuff rates, schedule running record
- Motivation: before writing any report/export code for the weekly coach report (modeled on `reports/Wk1-Butte-template.pdf`), wanted a stable, fact-checkable view layer first — `plays`, `drives`, `games`, `schedule`, `lineups` — so numbers can be manually validated against the template's known-good figures before anything gets built on top. `plays` (`v_plays_current`/`v_play_context_current`) and `lineups` (`v_player_lineup_stats_current`) were already stable; this pass covers the rest.
- **Clarified the `run_id`/append-only question for future iteration**: it only applies to Python-parsed silver tables (`plays`, `player_lineup_stats`) — never to SQL views. Views have no run_id of their own; editing a `CREATE OR REPLACE VIEW` and re-running `refresh_duckdb_views` is instant and lossless. `plays`/`lineups` are append-only by design (audit trail, safe rollback if a parse change regresses something) and already cheap to re-iterate via `rebuild_plays_from_raw`/`parse_lineup_stats`, which re-parse from already-fetched raw data rather than rescraping.
- **Exposed `offense_points`/`defense_points`** as real columns on `v_play_context_current` — the private `scoring_totals` CTE already computed these (FG/PAT/2pt/safety/pick-six/disputed-fumble-recovery-TD, via the `field_position_crosswalk` join) but only fed them into the windowed `home_score`/`away_score` sums, never surfaced them. Zero new logic, just carried two already-computed values one level further out — this unblocks both PPG and drive-scoring below without duplicating the crosswalk join anywhere else.
- **New points-per-game view chain**: `v_team_game_points_current` (via a `UNION ALL` of the offense-role and defense-role arms, so a team's own defensive scoring — safety/pick-six — correctly lands as that team's own points, not the opponent's) → `v_team_season_points_current` → `v_team_season_points_ranked_current` (`ppg`/`ppg_allowed`, ranked).
- **New combined success/explosive/stuff-rate columns**, additive on the existing offense/defense game→season→ranked view chain: combined (pass+rush) `success_rate`/`explosive_rate` (previously only pass-only/rush-only versions existed), split `rush_explosive_rate`/`pass_explosive_rate`, and `run_stuff_rate` (`stuffed_runs/rush_att` — `stuffed_runs` was already summed through to the season view but never turned into a rate). Needed `rush_explosive`/`pass_explosive` sums added at the game-view level first (the per-play booleans already existed on `v_play_context_current`, just never aggregated).
- **New drive-level rollup**, built entirely from `plays.drive_id` (already existed, nothing ever grouped by it): `v_drives_current` → `v_team_game_drives_offense_current`/`_defense_current` → season → ranked. Starting field position per drive via `ARG_MIN(yardline_100, play_id)` (first play of the drive, using the same `play_id` chronological-ordering convention `game_score_state`'s window already relies on).
  - **3-and-out definition (explicit user decision)**: `scrimmage_plays <= 3 AND NOT is_scoring_drive` — covers both a punt after ≤3 snaps and a turnover-on-downs after ≤3 snaps, does not require the drive to literally end in a punt.
  - **Naming decision**: the defense-side drive view uses the *same* column names as the offense side (no `opp_` prefix), because `drives_three_and_out` on defense means drives *forced* into a 3-and-out — good, not bad — unlike every other `opp_*` column in this schema where higher means worse for the team described. Reusing `opp_` here would have been actively misleading.
  - Season rollups carry raw per-game sums (`total_scrimmage_plays`, `total_start_yardline_100`), not pre-averaged per-game rates, so the season view is a plain `SUM/SUM` — same weighting discipline already established for `avg_distance` (`distance_sum`/`distance_n`), no average-of-averages bug.
  - This also makes the previously-noted "Drive Summary tab (`view=drives`) would be a good future HTML-parsing target" idea (see the PrestoSports JSON entries below) unnecessary — `plays.drive_id` was already sufficient.
- **Schedule running record**: `v_schedule_current` now exposes `wins_entering_game`/`losses_entering_game`/`ties_entering_game` — the team's running overall record *entering* each game (not including it), parsed from `schedule.result` (`"W, 42-7"`/`"L, 7-42"`) via the same `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING` window pattern as `game_score_state`.
  - **Known gap, documented rather than silently dropped**: this is the *overall* record only. There's no per-game conference-game flag anywhere in this pipeline (`v_standings_current`'s conference totals come from a separately-scraped season-end row, not derived from individual `schedule` rows), so a conference-specific running record entering each game isn't derivable without new data.
- Added 3 new fixture-based tests to `test_db.py` (points/rates, drives, schedule record), each hand-computed and verified against the SQL independently before running — all passed on the first attempt, a good sign the view logic matches the intended semantics. Full suite: 44 tests passing.
- **Real-data spot-check against a scratch copy of `data/foothill.duckdb`** (never the real file directly): PPG, combined success/explosive rates, run-stuff rate, and schedule running record all check out for Foothill (`ppg=20.7`, `success_rate=35.1%`, etc. — all plausible, correctly ranked among ~66-70 conference teams); the pre-existing, already-validated `pass_pct`/`rush_pct` numbers (`44.5%`/`60.4%`) are unchanged, confirming the additive edits didn't disturb anything.
  - **Found a real, pre-existing data-staleness bug this surfaced (not introduced by this session's changes)**: `avg_start_yardline_100` came back `NULL` for every team. Root cause: `yardline_100` is `NULL` for **100% of plays** in the current view, because `play_field_positions.source_plays_run_id` (frozen to whichever `plays` run existed when the `field_position` stage last ran) no longer matches the *current* `plays` run_id — the `plays` pipeline has been reparsed/rebuilt several times since (12 completed `plays`-stage runs vs. only 2 `field_position`-stage runs), so the join in `v_play_context_current` matches zero rows. Every other new metric in this pass is unaffected (none of them depend on `yardline_100` except this one column), and the view degrades gracefully (`NULL`, not a crash). Fixing this means re-running the multi-step field-position pipeline (`prepare_field_positions` → prefix review → `resolve_field_position_prefix` → `apply_field_positions`) against the current `plays` run — a real, separate follow-up task, not something to silently patch here.

### players_json parsed into player_lineup_stats (Team Leaders silver table)
- Built the silver layer on top of `raw_lineup_json`'s `players_json` rows, per the scope decision logged earlier today (Team Leaders is the primary near-term use case for this source).
- `lineup_parse.py` (new): `POSITION_GROUP_MAP` (hardcoded, decoded from `metaData/0.json`'s `positions` key — `FB`/`HB`/`SB`/`TB` → `rb`, `TE` → `wr`, `DL`/`LB`/`DB` → `d`, else `"other"`) and `parse_players_json(json_text, season, run_id) -> list[dict]`. Pure function, no DB/network dependency, mirrors `parse.py`'s separation of concerns.
- **One wide table, not per-position tables**: `player_lineup_stats` has every stat column (passing/rushing/receiving/defense) for every player regardless of `position_group` — a QB's incidental rushing still populates `rush_*`. `position_group` is for classification/filtering, not a gate on which columns get filled. Deliberately excludes kicking/punting/return categories — not needed for Team Leaders.
- Parsed once at ingest time into a real table (not a live SQL view over the raw JSON) — the source blob is ~20MB, re-parsing it on every query would be wasteful, unlike the columnar tables the rest of this pipeline's views compute over.
- Added `v_current_lineup_stats_runs` (new `pipeline_runs.stage = 'lineup_stats'`) and `v_player_lineup_stats_current`, mirroring the existing `v_current_plays_runs`/`v_plays_current` pattern exactly.
- New CLI command `parse_lineup_stats --season --source-run-id` (defaults to the latest completed `stage='lineup_json'` run), reading the stored `players_json` blob and inserting into `player_lineup_stats`.
- **Found and fixed one field-mapping bug before it shipped**: initially mapped `rec_ypg` to `watg`, but `watg` is receptions/game, not yards/game — `wyg` is yards/game. Caught by re-checking the exact legend text already recorded in this log rather than trusting memory, before writing any tests against it.
- Added `tests/test_lineup_parse.py`: a hand-built `players_json` fixture with a QB (passing + incidental rushing), a linebacker (tackles/sacks/etc.), and an offensive lineman (a real position with no individual stat category at all — exercises the `"other"` fallback instead of crashing). Covers both the pure parser and the `player_lineup_stats` → `v_player_lineup_stats_current` DB round-trip. Full suite: 41 tests passing.
- Validated end-to-end against a scratch copy of the live database: re-ran `scrape_lineup_json` (fresh fetch, 20s delays, no rate-limiting) then `parse_lineup_stats`; confirmed 86 Foothill rows, and James Maxwell's row exactly matches both the raw JSON inspected earlier this session and this project's own independently plays-derived `v_player_season_passing_current` (`pass_att=169, pass_comp=91, pass_yds=1028, pass_td=8, pass_int=3, pass_rating=117.0`).

### New source discovered: PrestoSports official season-stats JSON (Team Leaders)
- Motivation: wanted official Team Leaders (Passing/Rushing/Receiving/Tackles/Sacks) for the weekly coach report without depending on the raw `plays.passer`/`rusher`/`receiver` text-grouping approach (session's earlier passer-rating work), and without the never-run, ~3.5-hour `pipeline/10_scrape_lineup.py` overnight scrape against `cccaa.prestosports.com` (which is Cloudflare-protected and only extracts player name+slug, not actual stat lines, even where it does work).
- Discovery path (all confirmed live against `foothill`, via a manually-saved `manual/2025-26 Football Statistics - Foothill - 2025-26 - 3C2A - Print Version.html`):
  1. `https://3c2asports.org/sports/fball/{season}/teams/{team_slug}?tmpl=teaminfo-network-monospace-json-template` — a lightweight "print version" page. **Not Cloudflare-blocked** with a normal browser `User-Agent` header (unlike the old script's `cccaa.prestosports.com/.../teams/{slug}?view=season&pos={pos}` pages, which return a `403`/Cloudflare challenge from this environment). This page embeds a `ps.rendering.team.initialize(...)` call with several S3 URLs.
  2. That call includes `teamDataEndp` (e.g. `.../teamData/an42fqq3u1wiedd5.json`) — fetching it gives `sportCode` (`0` for football) and `attributes.teamId`, needed for the next step.
  3. `playersDataEndp` (e.g. `.../playersData/agwhctziptolcaqc.json`) is a **single ~20MB JSON file containing every player in the conference for the season** (5,179 individuals in the 2025-26 file) — not just one team. Confirmed via `team-page-rendering.js`: the site's own client-side JS does `playersData.individuals.filter(player => player.teamId === teamData.attributes.teamId)` to scope it down to one team in the browser. **One fetch of this file covers all 66 teams** — no per-team or per-position looping needed at all, unlike the old script's design.
  4. The abbreviated stat keys (`pa`, `ryd`, `dtt`, etc.) inside each player's `stats` object are defined in a legend file at `.../metaData/{sportCode}.json` (`sportCode` from step 2 — literally `metaData/0.json` for football). Its `briefs` key gives the full field-name legend, one object per position group (`qb`, `rb`, `wr`, `k`, `p`, `kr`, `d`, plus combined `allp`/`pts`/`all`), and `labels` gives the human-readable names for the same keys.
- **Cross-validated against this session's own plays-derived `v_player_season_passing_current`**: James Maxwell's official line (169 att, 91 comp, 1028 yds, 8 TD, 3 INT, **117.0 passer rating**) matches our independently plays-derived numbers for the same player almost exactly. Good evidence both the new source and the existing plays-derived pipeline are trustworthy.
- Decoded field legend (from `metaData/0.json` → `briefs`), the fields needed for Team Leaders:
  - **Passing (`qb`)**: `gp`, `pc`=completions, `pa`=attempts, `ppt`=comp%, `pyd`=yards, `pyg`=yards/game, `pya`=yards/att, `ptd`=TD, `pin`=INT, `plg`=long, `peff`=passer rating (NCAA formula, matches our own `passer_rating`)
  - **Rushing (`rb`)**: `gp`, `rat`=rush attempts, `ryd`=yards, `ryg`=yards/game, `rya`=yards/rush, `rtd`=TD, `rlg`=long, `fum`=fumbles, `fuml`=fumbles lost
  - **Receiving (`wr`)**: `gp`, `wat`=receptions, `watg`=rec/game, `wyd`=yards, `wyg`=yards/game, `wya`=yards/catch, `wtd`=TD, `wlg`=long
  - **Defense (`d`)**: `gp`, `dtu`=solo tackles, `dta`=assisted tackles, `dtt`=total tackles, `dtpg`=tackles/game, `dst`=sacks, `dsyd`=sack yards, `tfl`=tackles for loss, `dff`=forced fumbles, `dfr`=fumble recoveries, `di`=interceptions, `dbru`=pass breakups, `dblk`=blocked kicks
  - (also decoded but not immediately needed: `k` kicking, `p` punting, `kr`/`pr` returns)
  - Each `individual` record also carries `firstName`/`lastName`/`fullName`, `team`, `teamId`, `playerId` (stable ID), `uniform` (jersey #), `position`/`positionAbbreviation`, `year` (class) — meaningfully richer identity than anything derivable from raw PBP text, and sidesteps the player-name-crosswalk problem entirely for this purpose.
- Added bronze table `raw_lineup_json` to `db.py` (`run_id`, `season`, `source_kind` — `'players_json'` or `'metadata_legend_json'`, `fetched_at`, `source_url`, `json_text`). Schema only for now — no scraper or parser built yet, this just registers the new source and its raw storage shape. Silver-layer parsing (into a proper `player_season_stats` table or similar) and the actual fetch/ingest command are follow-up work.
- Explicitly **not** pursuing the old `pipeline/10_scrape_lineup.py` approach further for this need — it's Cloudflare-blocked from this environment, was never run to completion for 2025-26, and only captured name+slug even where reachable. This new source is faster (2 lightweight requests total instead of 462 = 66 teams × 7 positions), not blocked, and richer (real stat lines, not just identity).

### Same source, more endpoints: per-game box scores and player game logs
- Followed up on the discovery above by digging into what else this JSON ecosystem exposes, since the rendering pattern (a page embeds a `ps.rendering.X.initialize(...)` call pointing at S3 JSON files) repeats across page types.
- **`teamData` includes `events[]`** — the team's full schedule, each entry with a `boxScoreLink` (e.g. `20250906_tjag.xml`, the *same* `game_id` convention already used everywhere in this pipeline) and, for completed games, **an embedded `stats` object that is a full per-game team box score** (points, total yards, comp-att-int, rushing yards, time of possession, penalties — both for the team and, via an `opp`-suffixed key of the same name, the opponent).
  - This is the "box score layer" recommended as future work in the 2026-06-30 entry below (`raw_boxscore_html`, `box_score_team_stats`) — except the data is already sitting in JSON here, no new scrape/parse needed.
  - Cross-checked against the known swapped-offense/defense bug (`DATABASE_PLAN.md`: Foothill vs Redwoods `20250906_tjag` showed "173 PBP yards vs 317 official"). This box score's `ofyds` for that exact game reads **317** — an exact match, confirming this source can validate (and help pinpoint) that whole class of bug across the season, not just the one flagged game.
- **Individual players have their own per-game logs too, at a different endpoint than the shared season file.** A player's own profile page (`/sports/fball/{season}/players/{pageName}`, e.g. `/players/jamesmaxwell84ph`) loads `player-page-rendering.js` (singular — distinct from `players-page-rendering.js`, which handles the conference-wide leaderboard), which points at a **per-player** `playerData/{hash}.json` (singular — distinct from the shared `playersData`). That file has its own `events[]` array with a per-game `stats` object: confirmed real, game-by-game numbers for James Maxwell (e.g. his `20250906_tjag` line: `pa:26, pc:10, pyd:140, peff:83.7`, matching that specific game, not his season total). This is authoritative *weekly* per-player data — previously we could only get this by re-deriving from `plays`.
- **`teamsData` is the conference-wide team season-totals file** — all 70 teams' full season stat lines in one ~1MB JSON. Cross-checked Foothill's entry: `rat:408, ray:"408-1520"` (408 rush attempts, 1520 rush yards) — an exact match to what this session already independently computed from `plays`. Useful as a second validation source for the team-season views, though it doesn't expose anything not already derivable ourselves.
- **Confirmed negative: no play-level (down-by-down) source exists in this ecosystem.** Fetched the actual boxscore/PBP page directly (`https://3c2asports.org/sports/fball/{season}/boxscores/{game_id}.xml`) — despite the `.xml` filename convention, it returns `content-type: text/html` and has **no `ps.rendering` initialization or S3 JSON reference at all**, unlike every team/player stats page. This page is old-style server-rendered HTML. The existing scraper's HTML/regex-based `parse_pbp_html` remains the only path to real play-by-play data; this discovery doesn't change or improve that.
- Net assessment: this source is a clear upgrade for box scores and player/team stat leaders (official numbers, stable IDs, ~4 lightweight non-blocked requests total for a whole season instead of hundreds of blocked ones) but is a complementary source, not a replacement for the plays scraper.
- **Follow-up: confirmed the box-score/game-detail page family has no JSON backing either, with real (unblocked, delayed) requests.** The box score page (`boxscores/{game_id}.xml`, both bare and `?view=plays`) exposes four tabs total — `plays`, `drives`, `participation`, `starters` (the `participation` tab confirms it's the same page family the old `pipeline/02_scrape_participation.py` already scrapes) — and every one of them is plain server-rendered HTML with no `ps.rendering` call and no S3 references, same as the base page. This is a genuinely different, older subsystem than the team/player stats pages. No JSON shortcut exists for play-by-play, drives, participation, or starters — confirmed, not just inferred from one rate-limited attempt.
- **`view=drives` (Drive Summary tab) is a good next scrape target despite needing HTML parsing.** Screenshot-confirmed columns: Team, QTR, Start, Poss., Began (i.e. drive start field position, quarter, possessing team, how the drive started — kickoff/punt/turnover/etc.). This would directly fill the drive-level rollup gap this session already flagged as missing (`% Drives Score`, `% Drives 3-and-Out`, `Avg plays/drive` on the Offense/Defense Identity report page) — it just needs a parser built the same way as `parse_pbp_html`, not a JSON shortcut.
- **Rate-limiting note for future scraping sessions**: `3c2asports.org` soft-blocks with `202`/empty-body responses after a burst of quick requests (distinct from the Cloudflare `403` on `cccaa.prestosports.com`). A ~20s delay between requests was enough to get clean `200`s again in this session — worth keeping in mind as a real, observed rate limit, not just theoretical.
- Summary of this whole discovery, updated: JSON-backed and easy (team/player season stats, player game logs, team per-game box scores) vs. HTML-only same-difficulty-as-today (play-by-play, drives, participation, starters) — no exceptions found on either side after this second, unblocked round of testing.
- **Confirmed exhaustively there's no 6th JSON source**: searched every rendering script referenced by every page type found (`common-page-rendering.js`, `team-page-rendering.js`, `players-page-rendering.js`, `player-page-rendering.js`, `team-coach-view-page-rendering.js`) for the `*DataEndp` naming convention the site's own JS uses to pass these URLs around. Found exactly five: `teamDataEndp` (per-team), `playersDataEndp` / `teamsDataEndp` (conference-wide singletons), `playerDataEndp` (per-player game log), `statsDataEndp` (the metadata legend). The "Coach's View" tab on the box-score page doesn't add a new source either — it just re-renders the same `teamData`/`playersData`/`teamsData` already passed to `ps.rendering.team.initialize(...)`.

### Fetch-and-store for the JSON sources (bronze ingestion)
- Added `lineup_scrape.py`: `build_team_print_url`, `extract_s3_json_urls` (parses the `ps.rendering.team.initialize(...)` call for the `teamData`/`playersData`/`teamsData` URLs — correctly ignores the unresolved `SPORT_CODE` template placeholders rather than treating them as real endpoints), `build_metadata_legend_url`, and `fetch_lineup_json_sources` (orchestrates all four fetches for one team, reusing the existing `scrape.py::fetch()` helper — which, usefully, already retries on `202`/empty-body with exponential backoff, exactly the rate-limit behavior observed and worked around manually earlier this session).
- New CLI command `scrape_lineup_json --season --team-slug --delay` (default `--team-slug foothill`, default `--delay 20.0`), writing to `raw_lineup_json` and tracked in `pipeline_runs` under a new `stage='lineup_json'`.
- `players`/`teams` are conference-wide singletons, so fetching them via one team's page (any team) is enough to cover the whole conference — the command doesn't loop over teams for those two.
- Added `tests/test_lineup_scrape.py` (pure-function tests, no live network: URL construction, S3-URL extraction from a realistic sample script including the missing-`teamsData`-is-`null` case seen on player bio pages). Full suite: 37 tests passing.
- **Ran the real command end-to-end** against a scratch copy of the live database (`--team-slug foothill --delay 20`, never the real db file directly): all four sources fetched cleanly (`200`s throughout, no rate-limiting at this pace), stored with byte-for-byte matching sizes to what was seen fetching live earlier in this session (`players_json` = 20,714,574 bytes). Re-parsed the stored `players_json` back out of the database and confirmed all 86 Foothill players are present. `pipeline_runs` correctly recorded a `completed` run with the fetched source kinds in `notes`.
- Not yet built: any silver-layer parsing of `raw_lineup_json` into real tables/views (e.g. `player_season_stats`, `team_box_scores`) — this command only gets the raw JSON stored reliably. Also not yet built: per-player game-log fetching (`playerDataEndp`) — that needs one request per player of interest, which is a bigger/separate scrape than the four singleton-ish sources this command covers, and no specific player list has been scoped yet.
- **Scope decision: the primary near-term use of this source is the Team Leaders table** (Passing/Rushing/Receiving/Tackles/Sacks), i.e. parsing `players_json` for one team's players and their season `stats`. Team per-game box scores (swap-bug validation), `teamsData` (cross-checking this project's own season views), and per-player game logs are documented and confirmed working, but are secondary/later use cases, not the next build target. The next real implementation step is a `players_json` parser + a `player_season_stats`-style silver table/view scoped to what Team Leaders needs (`qb`/`rb`/`wr`/`d` position groups), not a general-purpose parser for every stat category this source exposes.

### NCAA passer rating added
- Added `passer_rating` (NCAA college formula — no clamps, unlike the NFL rating): `(8.4*Yds + 330*TD + 100*Comp - 200*Int) / Att`.
- Team level: added to `v_team_game_offense_current` / `_defense_current` (as `passer_rating` / `opp_passer_rating`), and ranked (with `RANK()`) on the season views `v_team_season_offense_ranked_current` / `_defense_ranked_current`.
- Player level: new `v_player_game_passing_current` / `v_player_season_passing_current`, grouped on the raw `plays.passer` text field directly — deliberately no player-identity crosswalk join. Documented the reliability posture in `METRICS.md`: solid for one team's own passing stats (typically 1-2 QBs per season, same source parsing the same spelling repeatedly), not a substitute for real identity resolution across games/teams.
- Validated against live season data: hand-computed formula matched the view's output exactly (Foothill: 268 att / 149 comp / 1657 yds / 16 TD / 7 INT → `122.0`); player split showed two Foothill QBs sharing snaps (James Maxwell 169 att, John Larios 98 att), both individually plausible.
- Added `test_passer_rating_team_and_player_views` in `tests/test_report_views.py`. Full suite: 33 tests passing.

### Weekly coach report rebuilt on DuckDB (4-page compact format)
- Replaced the old CSV-based weekly matchup preview (`analysis/*.py` + `analysis/build_preview_docx.py`, the source of `reports/Wk1-Butte.pdf`) with a DuckDB-native pipeline, per user request for a compact (4-page max, mostly tables + 1-2 charts) report and a stable way to keep generating it week to week.
- Editorial decisions locked in with the user before building:
  - drop the "Team Leaders" section entirely (depends on unresolved player-name crosswalk work)
  - replace the old full Early-Down + Third-Down rank tables with one "Success Rate by Down" line chart + a trimmed 6-row bidirectional table
  - weekly-trends page gets a sensible default metric set (success rate, explosive rate, 3rd-down conversion), but the metric list is a config list in `report_build.py`, not hardcoded per-chart code, so it's a one-line edit to swap later
- Data architecture decision: compute everything **live via `RANK() OVER (PARTITION BY season ...)` window functions in the view layer**, no new audit/snapshot table. A cross-team percentile rank is a pure, deterministic function of data that's already frozen per the existing `v_current_*_runs` resolution, so it can't drift out of sync with a metric-definition change the way a snapshot could. The actual historical record of "what the coach saw in week N" is the saved `.docx` file in `reports/`, not a database row.
- New views added to `_refresh_views()` in `db.py`:
  - `v_play_context_current` extended with `is_early_down` / `is_passing_down`, ported verbatim from `analysis/helpers.py::add_flags()` (`2nd & 8+` or `3rd/4th & 5+` = passing down; `1st/2nd` not passing down = early down). These intentionally overlap with `down = 3`/`down = 4` — a 3rd-and-8 is both `is_passing_down` and third down, matching the old pipeline's non-mutually-exclusive treatment.
  - `v_schedule_current` — trivial gap-filler mirroring `v_games_current`'s pattern, needed for the page-1 schedule table.
  - `v_team_game_situation_offense_current` / `_defense_current` and their season rollups `v_team_season_situation_offense_current` / `_defense_current` — one row per `(team, game or season, situation)` via `UNION ALL` over `situation IN ('early_down','passing_down','third_down','fourth_down')`, reusing the same aggregate column shape as the existing non-situational offense/defense views, plus `distance_sum`/`distance_n` (kept as a sum pair, not a pre-averaged `avg_distance`, so season rollups don't average-of-averages).
  - `v_team_season_offense_ranked_current` / `_defense_ranked_current` and their situational counterparts `v_team_season_situation_offense_ranked_current` / `_defense_ranked_current` — add rate columns and `RANK()` per metric, direction ported 1:1 from `analysis/table_production.py::add_ranks()`'s per-metric higher/lower-better dicts.
- **Found and fixed a real percentage-denominator bug while validating against the live season data.** Initially computed `pass_pct`/`rush_pct`/`yards_per_play` against the view's raw `play_count`, which also includes non-scrimmage rows (punts, kickoffs, PAT/two-point, drive markers) — this gave Foothill offense `34.4%` pass / `46.6%` rush against the season data, when the old pipeline's number (and the actual correct figure) is `44.5%` / `60.4%`. Root cause: the old pipeline's `load_plays()` pre-filters to `play_type in ('rush','pass')` before any percentage is computed, so its "total" denominator is scrimmage plays only. Fixed by using `pass_att + rush_att` ("scrimmage plays") as the denominator instead of `play_count` — confirmed this now matches the old pipeline's season-aggregate numbers exactly, including the sacks-double-counted-into-both-pass-and-rush convention that pushes the two percentages' sum above 100%.
- The situational views (early/passing/third/fourth down) do **not** attempt to reproduce the old `table_early_down.py`/`table_third_down.py` numbers exactly — those scripts use an inconsistent per-script sack convention (a sack silently drops out of both the pass and rush numerator while still counting in the denominator) that conflicts with this project's own canonical `is_rush_attempt` definition (includes sacks everywhere else in this schema). Applied the canonical convention uniformly instead; situational percentages come out a few points off from the old pipeline's by design, not by bug. Documented in `METRICS.md`.
- New report-generation code lives inside `duckdb_pipeline` rather than a separate top-level script — it already owns the whole data layer, and the report is a first-class consumer of it, same posture as `scrape_season_plays`/`refresh_duckdb_views`:
  - `report_data.py` (new) — pure query/shaping layer, no docx/matplotlib imports, stays unit-testable with the existing lightweight fixture pattern.
  - `report_build.py` (new) — chart rendering (ported styling from `analysis/plot_charts.py`: font registration with the existing graceful-degrade guard, Foothill palette) + docx assembly (ported table helpers from `analysis/build_preview_docx.py`). Charts stay matplotlib PNGs embedded via `doc.add_picture(...)`, matching the established `reports/build_report.py` precedent.
  - New CLI command `build_weekly_report` (added `python-docx`/`matplotlib` to `duckdb_pipeline/pyproject.toml`), refuses to overwrite an existing output file.
- **Found and fixed a real bug in `report_data.py::load_weekly_trends` during end-to-end validation**: the opponent-per-week column was derived from `pc.opponent`, which is always relative to *that row's own offense* — on the rows where the tracked team is on defense, this returned the tracked team's own name instead of the actual opponent (week 8 showed "Foothill" as its own week-8 opponent instead of "Diablo Valley"). Fixed by deriving the opponent directly from `schedule_home`/`schedule_away` relative to the tracked team, independent of which side of the ball that particular row is on.
- Added `tests/test_report_views.py`: `is_early_down`/`is_passing_down` truth table (including the known third-down/passing-down overlap case), situation-rollup row-count sanity, and rank-direction sanity (most rush yards → offensive rank 1; most yards allowed → defensive rank last). Full suite: 32 tests passing.
- End-to-end validated by generating the actual Week 1 Foothill-vs-Butte report from live data (scratch copy, never the real db file directly, until the final regenerate): confirmed 4 pages (3 page breaks), exactly 2 embedded chart images, and numbers matching the old pipeline's golden output where expected to match, diverging only where already documented as intentional (success-rate threshold change, situational sack-convention change).

### Score margin added to v_play_context_current
- Compared a hand-drafted metrics/filters checklist against `METRICS.md` and confirmed nearly every listed metric already had an exact numerator/denominator definition staged as `derived_next`. The one genuinely open filter was `score_margin`, previously `future_modeling` because no score state existed anywhere in the schema.
- Decision: derive score state directly from `plays`, no box-score dependency required.
- Added `score_margin` and `score_margin_bucket` to `v_play_context_current`, computed via two new CTEs:
  - `scoring_points`: per-play home/away points, attributing 6 to a non-conversion `is_td`, 3 to a made `field_goal`, 1 to a made `pat`, 2 to a made `two_point`, keyed to whichever of `schedule_home`/`schedule_away` matches that play's `offense`
  - `game_score_state`: a running pre-play cumulative sum per game ordered by `play_id`, using `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING` so the scoring play itself still shows the score *entering* it, matching the pre-snap semantics `down`/`distance`/`quarter` already use in this view
- `score_margin` is `offense_score - defense_score` at that pre-play state; `score_margin_bucket` buckets it into `blowout_lead` / `two_score_lead` / `one_score_lead` / `tied` / `one_score_deficit` / `two_score_deficit` / `blowout_deficit`.
- Confirmed known, permanent gaps rather than silently approximating them:
  - safeties are not parsed as an event anywhere in `parse.py`, so a scored safety's 2 points never enter `score_margin`
  - defensive/special-teams touchdowns (pick-six, fumble/blocked-kick return TD) only clear the offensive `is_td` flag (per the 2026-06-30 defensive fumble-return TD fix) — they were never turned into a scoring event for the defense, so those 6 points are also invisible
  - both gaps leave `score_margin` permanently short for the rest of that game, not just temporarily desynced, until parser support for these play types is added
- Updated `METRICS.md`: `score_margin` / `score_margin_bucket` moved from `future_modeling` to `derived_next`, with the two gaps documented inline.
- Extended `test_current_run_views_and_current_offense_rollups` in `test_db.py` to assert the running score state across the existing 3-play `g-new` fixture (TD on play 1, so play 1 itself reads `0-0` / `tied`; plays 2 and 3 read `6-0` / `one_score_lead`). Full suite (28 tests) passes.

### Safety and defensive-touchdown flags close the score_margin gaps
- Followed up on the two gaps logged above by adding `plays.is_safety` and `plays.is_defensive_td`.
- `is_safety`: a plain `\bsafety\b` regex against play text in `parse.py`. Verified real and consistent against the live `raw_text` corpus (383 historical matches) before writing it.
- `is_defensive_td`: set at parse time only for the interception-return (pick-six) case (`is_interception AND "touchdown" in text`), since that's unambiguous — no team-name matching needed, the interceptor is definitionally the defense.
- While scoping the fumble-recovery-TD half of `is_defensive_td`, found that reusing the field-position crosswalk (`field_position_crosswalk`, built from human-reviewed field-position work) resolves the exact same raw team abbreviations that the existing parse-time suppression (`_team_matches`/`_team_prefix_matches` in `parse.py`, from the 2026-06-30 defensive fumble-return TD fix) fails to match — e.g. `MSJC-FB` for `Mt. San Jacinto`, which isn't a textual prefix/substring of the canonical name at all.
- Digging further surfaced a second, more foundational bug live in the current blessed run: `RE_FUMBLE`'s capture group for the recovering team's abbreviation is polluted by the recovering player's own name, because the whole regex is compiled with `re.IGNORECASE`, which defeats the intended all-caps-vs-mixed-case boundary between the team-abbreviation group and the player-name group. Confirmed directly against `data/foothill.duckdb`: `fumble_recovered_by` stores values like `"FULLERTO Ethan"` and `"SANTA MO Chistopher"` instead of just `"FULLERTO"` / `"SANTA MO"`, breaking simple team-name matching even for straightforward, correctly-abbreviated cases (not just genuinely different abbreviations like `MSJC-FB`).
- Fix: resolve the fumble-recovery case at the view layer (`v_play_context_current` in `db.py`, `scoring_points`/`scoring_totals` CTEs) by joining `field_position_crosswalk` on `(season, game_id)` with `fumble_recovered_by LIKE prefix || '%'` — a prefix match, not exact equality, which tolerates the name-pollution bug without needing to touch the regex or reparse anything. Picks the longest matching prefix via a scalar subquery to avoid any join fan-out. Falls back to the stored (occasionally wrong) `is_td` when a game has no crosswalk entry yet.
- Validated against a scratch copy of the live `data/foothill.duckdb` (never the real file) via `init_db()`: all 4 known-bad rows in the current blessed run now correctly resolve as defensive touchdowns instead of incorrectly-credited offensive ones —
  - `20251018_k2dy` (Bakersfield/Fullerton), `20251101_1js3` (Chabot/Feather River via the `FRC` abbreviation), `20251101_ca8g` (San Diego Mesa/Mt. San Jacinto), `20251108_y7hi` (West LA/Santa Monica)
  - season-wide counts after backfill: `is_safety = 43`, `is_defensive_td = 127` (sane magnitudes for a season of ~55,850 plays)
- Schema: both columns added to `CREATE TABLE plays`, migrated via `_ensure_column`, and backfilled via a new idempotent `_backfill_plays_safety_and_defensive_td` (mirrors `_backfill_pipeline_run_stages`) — both flags are fully recoverable from already-stored `raw_text`/`is_interception`, so existing rows get them without a `rebuild_plays_from_raw` reparse.
- `v_play_context_current` now exposes a unified, fully-resolved `is_defensive_td` (parse-time pick-six OR view-level crosswalk-resolved fumble-recovery) and a pass-through `is_safety`, for reporting as well as scoring. Same bronze/silver-vs-gold naming pattern already used for `field_position` (raw token vs crosswalk-resolved token) — `plays.is_defensive_td` (pick-six only) vs `v_play_context_current.is_defensive_td` (complete).
- Remaining known gap, deliberately out of scope here: blocked-kick-return touchdowns (blocked punt/FG returned for a score) aren't covered by either resolution path. Confirmed real (~5 instances in the season's raw text) but rare enough not to hold up the rest of this fix.
- Added `test_score_margin_credits_safety_and_defensive_touchdowns` in `test_db.py`: a small synthetic game covering a non-scoring play, a safety, a pick-six, and a fumble-recovery TD with `is_td` deliberately stored as the (buggy) `True` to prove the crosswalk suppression prevents double-counting. Full suite (29 tests) passes.

## 2026-07-03

### Explicit pipeline_runs stage column
- Added `pipeline_runs.stage` (`'structure'`, `'plays'`, `'field_position'`, and later `'lineups'`) as an explicit column instead of inferring the run kind by sniffing `games_count IS NOT NULL` or JSON keys inside `notes` (`notes LIKE '%"plays_count"%'`, etc.).
- Motivation:
  - `pipeline_runs` is one shared table across every stage, and the old approach meant each new stage needed its own bespoke marker to distinguish itself from the others
  - that gets uglier as more stages (`lineups`, future stages) get added as first-class commands
  - a real `stage` column makes every `v_current_<x>_runs` view and every run-resolver function collapse to the same `WHERE stage = ? AND status = 'completed'` shape
- Decision: overwrite-in-place was rejected for run history. Keep `pipeline_runs` and all base tables (`standings`, `schedule`, `games`, `plays`) append-only and `run_id`-keyed. The entire 2026-06-30 reparse debugging session (sack accounting, quarter-start possession reset, ghost-drive residue, defensive fumble-return TD) depended on diffing an old run against a new one for the same `game_id` — overwriting would have destroyed that capability. `stage` only changes how a run's *kind* is identified, not whether runs persist.
- Migration:
  - `stage TEXT` added to the `pipeline_runs` schema for new databases
  - `_ensure_column` adds it to existing databases (same pattern already used for `plays.is_pass_attempt` / `is_rush_attempt` / `is_conversion`)
  - a one-time backfill (`_backfill_pipeline_run_stages` in `db.py`) assigns `stage` to any pre-existing row where it's still `NULL`, using the exact same signals the views used to sniff stage from before (`games_count IS NOT NULL` -> `structure`; `notes` containing `"plays_count"` -> `plays`; `notes` containing `"field_position_rows"` -> `field_position`)
  - the backfill is idempotent (`WHERE stage IS NULL`) and runs every `init_db()` call, so it applies automatically the next time any CLI command or `refresh_duckdb_views` touches an existing `.duckdb` file
- Verified against the live `data/foothill.duckdb`: after running `refresh_duckdb_views`, all `completed` runs backfilled to the correct stage (`structure=2`, `plays=12`, `field_position=2`), and `v_current_runs` still resolved to the same frozen checkpoint runs as before (`4b573736...` structure, `63fa3f95...` plays). `failed`/`running` rows correctly stayed `stage = NULL` since a run that never completed was never distinguishable as one kind or another anyway.
- Every `_insert_running_run` call site now passes `stage` explicitly (`main_structure` -> `"structure"`, `main_plays` / `main_rebuild_plays_from_raw` -> `"plays"`, `main_apply_field_positions` -> `"field_position"`, new `main_rebuild_structure_from_raw` -> `"structure"`), so a future stage that forgets to set it fails loudly (missing required arg) rather than silently landing with `stage = NULL` and never showing up as "current."

### Structure rebuild-from-raw added
- Added `main_rebuild_structure_from_raw` (console script `rebuild_structure_from_raw`), symmetric to the existing `rebuild_plays_from_raw`.
- Re-parses stored `raw_standings_html` + `raw_schedule_html` for a given structure run into a fresh `standings` / `schedule` / `games` run, without re-fetching from the network.
- Closes the asymmetry where a plays parser bug could always be fixed by re-parsing stored raw HTML, but a standings/schedule parser bug would have forced a full re-scrape.
- `--source-structure-run-id` defaults to the latest completed structure run for the season (via `pipeline_runs.stage = 'structure'`) when omitted.
- Added `test_rebuild_structure_from_raw_reparses_without_rescraping` in `test_cli.py` covering the full loop: seed `raw_standings_html`/`raw_schedule_html` fixtures, run the command, confirm `v_standings_current` and `v_games_current` reflect the reparsed run.

### Pipeline dependency breadcrumb
- Locked the current scrape dependency model in words before changing the CLI surface.
- Current working chain remains:
  - `standings scrape -> schedules scrape -> build games -> plays scrape`
- Important clarification:
  - `build_games` is not a fetch step
  - it is the canonicalization step that converts team-sided `schedule` rows into one canonical `games` row per `game_id`
- Current dependency interpretation:
  - `plays` depends on `games`
  - `games` depends on `schedule`
  - `schedule` currently depends on `standings` because standings is how team schedule URLs are discovered
- Decision for now:
  - leave the working end-to-end path untouched
  - keep `scrape_season_structure` as the convenience wrapper
  - later add smaller first-class commands around the same logic:
    - `scrape_standings`
    - `scrape_schedules`
    - `build_games`
    - separate `scrape_lineups`
- Architectural intent:
  - preserve the stable current pipeline
  - improve auditability and selective reruns by exposing smaller scrape/derive units over time

### Derived standings layer added
- Added `v_standings_current` as the first analyst-facing standings surface on top of the append-only base `standings` table.
- Decision:
  - keep `standings` unchanged as scrape truth with source-facing fields like `team_id` and `schedule_url`
  - expose a wide current-run reporting layer instead of stuffing derived report context into the base table
- `v_standings_current` now provides:
  - `season`
  - `run_id`
  - `conference`
  - `team_name`
  - `team_id`
  - `schedule_url`
  - `games`
  - `wins`
  - `losses`
  - `ties`
  - `win_pct`
  - `conference_games`
  - `conference_wins`
  - `conference_losses`
  - `conference_ties`
  - `conference_win_pct`
- Numeric-looking standings fields are cast in the view so report queries do not have to keep re-casting text columns.
- This keeps the pipeline split clean:
  - base scrape tables for audit and source fidelity
  - derived `v_*_current` views for operator/report use
- Added a small helper command for this:
  - `refresh_duckdb_views --db-path <path>`
- Intent:
  - make it explicit and low-friction to stamp the latest view definitions into the physical `.duckdb` file
  - support a quick "refresh then validate" workflow before committing pipeline changes

### Session checkpoint
- Opened a new design session around the post-validation analytics layer.
- Decision:
  - freeze the current `plays` checkpoint as the working analytics source
  - define the football metrics contract before building the first automated report
  - keep the next implementation sequence as:
    - metrics spec
    - derived context views
    - automated `team_report`
    - later dashboard

### Metrics spec v1 added
- Added `duckdb_pipeline/METRICS.md` as the canonical football metrics and filters spec for the current `plays`-driven analytics layer.
- The document is intentionally a broad draft, but every metric/filter is labeled as:
  - `supported_now`
  - `derived_next`
  - `future_modeling`
- Locked project defaults:
  - offense/defense perspective definitions
  - success-rate rule:
    - `1st down = 50%`
    - `2nd down = 70%`
    - `3rd/4th down = 100%`
  - explosive thresholds:
    - `rush >= 10`
    - completed `pass >= 20`
  - `week` as team game order within season
  - normalized field-position analysis around `yardline_100` / zones
- Explicitly documented that:
  - `score_margin` is planned but not currently supported
  - `line_yards` can be a later project-defined estimate
  - `EPA` and `expected_completion_rate` require future modeling layers
- The intended next implementation target remains:
  - derived play-context and team report views
  - then a first automated `team_report`

### Derived play-context and defense views added
- Added the first analytics-oriented derived view layer on top of `v_plays_current`.
- New per-play context view:
  - `v_play_context_current`
- New defense rollup views:
  - `v_team_game_defense_current`
  - `v_team_season_defense_current`
- Extended offense rollups:
  - `v_team_game_offense_current`
  - `v_team_season_offense_current`
  - now include:
    - opponent
    - home/away
    - week
    - success counts
    - explosive counts
    - stuffed-run counts
- `v_play_context_current` now derives:
  - `week`
  - `distance_bucket`
  - `yardline_100`
  - `field_zone`
  - `is_success`
  - `explosive_rush`
  - `explosive_pass`
  - `is_explosive`
  - `is_stuffed`
- Current first-pass assumptions:
  - `week` is offense-team game order within season on the per-play context row
  - `field_zone` buckets are:
    - `backed_up`
    - `own_territory`
    - `midfield`
    - `fringe`
    - `red_zone`
- Validation:
  - full `duckdb_pipeline` test suite passed after the new view layer was added

### Current-run helper views added
- Added a small operator-facing DuckDB view layer so routine analysis no longer has to hardcode `run_id` values.
- New current-run helper views:
  - `v_current_structure_runs`
  - `v_current_plays_runs`
  - `v_current_field_position_runs`
  - `v_current_runs`
- New current working-surface views:
  - `v_games_current`
  - `v_plays_current`
  - `v_play_field_positions_current`
- New offense rollup views:
  - `v_team_game_offense`
  - `v_team_game_offense_current`
  - `v_team_season_offense_current`
  - `v_pbp_coverage_by_team_current`
- Intent:
  - keep base tables append-only and fully auditable
  - make DBeaver / SQL work feel stable by querying a blessed "current" surface
  - reduce repeated manual use of run IDs for routine inspection
- Current behavior:
  - the `v_*_current` views follow the latest completed run for each season by pipeline timestamp
  - raw historical runs remain queryable directly in `plays`, `games`, and `pipeline_runs`

## 2026-06-28

### Milestone 1 created
- Added a new in-repo subproject at `duckdb_pipeline/`.
- Implemented a clean-room DuckDB structure pipeline for:
  - standings
  - schedule
  - games
- Added these tables:
  - `raw_standings_html`
  - `raw_schedule_html`
  - `standings`
  - `schedule`
  - `games`
  - `pipeline_runs`

### Tooling and packaging
- Added subproject packaging in `duckdb_pipeline/pyproject.toml`.
- Added CLI entry point: `python -m duckdb_pipeline.cli`.
- Added tests for:
  - standings parsing
  - schedule parsing
  - canonical game derivation
  - DuckDB initialization/inserts

### Logging improvements
- Added timestamped console logging for:
  - run start
  - stage transitions
  - wait periods
  - fetch attempts
  - successful responses
  - retries / rate limiting
  - final write summary

### Dependency status
- Installed the subproject dependencies with `uv sync`.
- Verified tests pass in the subproject environment with:
  - `uv run python -m unittest discover tests`

### Live scrape status
- A first live structure scrape for season `2025-26` was started with `--delay 8`.
- The run was intentionally stopped before completion.
- The background process was terminated.
- Result: there may be a partial DuckDB file and/or an incomplete `pipeline_runs` row from the interrupted run.

### Cleanup performed
- Removed the partial DuckDB files from the interrupted run.
- Removed the accidental nested `duckdb_pipeline/duckdb_pipeline/data/` path created by the earlier relative DB path.
- Updated the default DB path logic so the database resolves to the subproject's own `data/foothill.duckdb` regardless of the current working directory.

### Neutral-site schedule fix
- Investigated six paired games with blank `home_team_canonical` / `away_team_canonical`.
- Confirmed the affected schedule pages used `neutral` event rows with wording like `Team A vs. Team B @ site`.
- Updated the schedule parser to infer home/away from the box-score `aria-label` for `neutral` rows.
- Added a second safety fallback in `build_games_rows()` that uses consistent `schedule_home` / `schedule_away` values when canonical home/away are still blank.
- Added parser tests covering neutral-site schedule handling and canonical home/away fallback.

### Fresh validation rerun
- Re-ran the full `2025-26` structure scrape after the neutral-row fix.
- Completed run ID: `471e4a97-8818-40b4-822e-93cf8134dc02`
- Verified counts:
  - `standings = 66`
  - `schedule = 694`
  - `games = 347`
- Verified all `347` games are `paired`.
- Verified `0` paired games have blank `home_team_canonical` or `away_team_canonical`.

### Milestone 2 scaffold started
- Added append-only `raw_pbp_html` table.
- Added base `plays` table keyed by `run_id`, `season`, and `game_id`.
- Added `failed_game_fetches` audit table for missing or zero-play game fetches.
- Added a new console command:
  - `scrape_season_plays`
- Plays runs now point back to a structure snapshot via `source_run_id` stored in run notes and raw/failure tables.

### Base PBP parser scope
- Parses drive headers, quarter changes, down-distance, field-position token, and base play actors.
- Keeps this milestone intentionally limited:
  - no field-position owner crosswalk yet
  - no `yardline_100` yet
  - no participation join yet
  - no player identity crosswalk yet

### Validation
- Added tests for:
  - neutral-site schedule handling
  - canonical game fallback logic
  - base PBP parsing for rush/pass/penalty rows
  - DuckDB schema initialization for the new PBP tables
- Added a `--limit` option to `scrape_season_plays` for small validation runs before full-season ingest.
- Updated interrupted plays runs to mark the `pipeline_runs` row as failed instead of leaving it stuck at `running`.
- Verified local test suite passes:

```powershell
uv run --active python -m unittest discover tests
```

### Field-position workflow added
- Added `field_position_prefixes` to store detected per-game prefixes from a specific `plays` run.
- Added `field_position_crosswalk` to store manual prefix-to-team decisions.
- Added `play_field_positions` as a rebuildable derived layer keyed back to the source `plays` run.
- Added console commands:
  - `prepare_field_positions`
  - `resolve_field_position_prefix`
  - `apply_field_positions`
- The resolution workflow now supports:
  - displaying canonical team names with both detected prefixes
  - manually selecting one prefix/team mapping
  - automatically assigning the other prefix to the other team

### Field-position validation
- Tested prefix detection on the 10-game plays validation run:
  - `440482d8-cb31-4388-9396-8103a16b07d2`
- Verified sample review output for truncated prefixes like:
  - `LONG BEA`
  - `RIVERSID`
  - `SADDLEBA`
- Tested manual resolution for:
  - `20250830_2nv6`
  - `LONG BEA -> Long Beach`
  - auto-filled `RIVERSID -> Riverside`
- Tested enrichment materialization for the 10-game sample:
  - `1638` derived field-position rows written
  - unresolved rows remained high because only one game had been manually resolved, which is expected for the current validation state

### Review queue breadcrumb
- Updated the field-position review flow to better match the real in-season workflow.
- `prepare_field_positions` now prints an unresolved review queue with:
  - sequential `queue` index
  - canonical teams
  - `schedule_home` / `schedule_away`
  - `prefix_a` / `prefix_b`
  - `resolved_count`
- `resolve_field_position_prefix` now supports queue-driven review with:
  - `--queue-index`
  - `--which a|b`
- This keeps the older explicit mode available:
  - `--game-id`
  - `--prefix`
- Rationale:
  - when new weekly games arrive, the operator usually does not know the `game_id` or raw prefix in advance
  - a console review queue lets the operator just work top-to-bottom and assign one side per game
  - the opposite prefix is still auto-filled, keeping the manual step small and auditable

### Interactive review loop
- Added a one-command interactive mode:
  - `prepare_field_positions --review`
- This mode:
  - rebuilds detected prefixes
  - shows the next unresolved game
  - prompts `Which prefix belongs to <team_1>? [a/b/s/q]`
  - auto-fills the opposite side after a single answer
- Verified the interactive flow across the unresolved sample queue for the 10-game validation run.
- Confirmed the loop reaches:
  - `No unresolved field-position games remain for this plays run.`
- Confirmed the queue display intentionally resets to `Queue 1` after each answer because it always reloads the next unresolved game rather than preserving a stale queue index.

### Historical vs in-season note
- Documented that the current field-position review flow is optimized for week-by-week in-season ingest.
- Expected in-season pattern:
  - scrape new games
  - review a small unresolved queue
  - apply the crosswalked field-position layer
- Historical backfill can still use the same manual review flow for now.
- If the historical scope becomes large, flag a future improvement for:
  - batched review
  - suggested mappings
  - partial automation with manual confirmation
- Decision for now:
  - keep the workflow manual-first and stable
  - defer larger historical automation until it is clearly worth the added complexity

### Full-season 2025-26 plays run completed
- Re-ran the full `2025-26` plays scrape after confirming that the earlier interrupted run had not fully committed.
- Successful completed plays run:
  - `3e4103ae-62c3-4195-9c45-71df4fcc23ce`
- Final logged counts:
  - `games = 347`
  - `raw_pbp = 344`
  - `plays = 55548`
  - `failed = 15`
- Important operational note:
  - the console `WRITE plays ...` line is emitted before DuckDB finishes the heavy insert/commit phase
  - on this full-season run, `WRITE` to `DONE` took roughly 6 minutes 38 seconds
- future runs should be treated as incomplete until the console prints `DONE run_id=...` and returns to the prompt
- Next intended step after returning to this project:
  - run `prepare_field_positions --review` against plays run `3e4103ae-62c3-4195-9c45-71df4fcc23ce`

### Team-prefix memory review flow
- Updated field-position review memory to follow confirmed `canonical_team + prefix` pairs rather than treating prefixes as globally exclusive.
- This keeps the workflow aligned with the operator's real mental model:
  - confirm which observed prefix belongs to the displayed canonical school
  - reuse that same pairing in future games for the same school
  - allow the same raw prefix text to appear for different schools in different games when the source site is ambiguous
- `prepare_field_positions --review` now:
  - prints progress while reviewing
  - auto-seeds future games when a previously confirmed team-prefix pairing appears again
  - keeps the review interactive instead of silently resolving the whole queue

### Field-position apply validation
- Applied field-position enrichment to the full-season `2025-26` plays run:
  - source plays run: `3e4103ae-62c3-4195-9c45-71df4fcc23ce`
- Validation result:
  - `49,277` rows resolved
  - `6,271` rows marked `no-field-position`
  - `0` rows marked `unresolved-prefix`
- Spot-checked sample `no-field-position` rows and confirmed they are expected non-scrimmage cases such as:
  - `kickoff`
  - `pat`
- Takeaway:
  - the crosswalk covered every row that actually carried a resolvable field-position token
  - the remaining unresolved count is normal pipeline residue, not a mapping failure

### Team-level rushing accounting decision
- Spot-checked Foothill's season rushing totals from the completed `2025-26` plays run against the official online box-score total.
- Parsed totals using only `play_type = 'rush'` produced:
  - `375` rushing attempts
  - `1723` rushing yards
  - `12` rushing touchdowns
- Official site total was:
  - `408` rushing attempts
  - `1520` rushing yards
  - `12` rushing touchdowns
- The gap reconciled exactly once sacks were included:
  - `33` sacks
  - `-203` sack yards
  - `375 + 33 = 408` rush attempts
  - `1723 - 203 = 1520` rush yards
- Schema decision going forward:
  - official team rushing should include sacks
  - play-level context should still distinguish:
    - designed runs
    - dropback passes
    - sacks
- Planned derived flags for downstream aggregates:
  - `is_rush_att` for official rushing attempts, including sacks
  - `is_dropback` for pass attempts and sacks
  - keep `play_type = 'rush' and not is_sack` as the designed-run slice
- Rationale:
  - this preserves exact reconciliation with official box scores
  - while still keeping cleaner contextual features for later analytics

### Dropback / pass-attempt / rush-attempt split
- Updated the `plays` schema to add explicit derived attempt flags:
  - `is_pass_attempt`
  - `is_rush_attempt`
- Kept `is_dropback` as the play-context flag.
- Confirmed intended sack behavior:
  - `is_dropback = true`
  - `is_pass_attempt = false`
  - `is_rush_attempt = true`
  - `is_sack = true`
- This reflects the intended accounting split:
  - sacks belong to pass-play context
  - sacks do not count as official pass attempts
  - sacks do count toward official team rushing attempts and rushing yards
- Ran a one-time backfill on the existing full-season `plays` rows so the new columns were populated for historical data already stored in DuckDB.
- Foothill validation after backfill for plays run `3e4103ae-62c3-4195-9c45-71df4fcc23ce`:
  - `dropbacks = 303`
  - `pass_attempts = 270`
  - `rush_attempts = 408`
  - `sacks = 33`
- Sample sack rows now correctly show:
  - `play_type = 'pass'`
  - `is_dropback = true`
  - `is_pass_attempt = false`
  - `is_rush_attempt = true`

### Team-stat validation order
- Decided to validate season team offense in two passes instead of treating every mismatch the same.
- Validation pass 1:
  - check coverage first
  - compare scheduled game count versus distinct play-by-play game count by team
  - use this to identify teams that are probably missing one or more logged games entirely
- Validation pass 2:
  - only after coverage is understood, inspect teams with full game counts but remaining stat mismatches
  - these are the better parser/accounting audit targets because missing PBP coverage is no longer a confounder
- Current examples:
  - missing-game-coverage checks are useful for teams like `Reedley`, `Riverside`, `Sequoias`, and others that appear short on distinct PBP games
  - full-coverage stat-mismatch checks are more appropriate for teams like `Ventura`, `Long Beach`, and `San Francisco`
- Immediate operator workflow:
  - list the exact games currently present in DuckDB for a team
  - compare those games against the official season schedule or stat page
  - identify whether the discrepancy is a missing game versus an accounting mismatch inside covered games

### Missing-PBP opponent pattern
- After fixing `pbp_url` construction to use canonical season-level boxscore paths built from `season + game_id`, several teams recovered to full play-by-play coverage.
- Remaining missing-game checks now appear to surface source-availability patterns more than scraper-path bugs.
- First confirmed example:
  - `Hartnell` appears as the opponent in `6` still-missing games
- Enumerated missing Hartnell-involved game IDs:
  - `20250830_l13b` — `Hartnell vs Chabot`
  - `20250913_cupn` — `Hartnell vs Los Medanos`
  - `20250920_33gi` — `Feather River vs Hartnell`
  - `20250927_2b9n` — `Hartnell vs Contra Costa`
  - `20251025_3ap7` — `Hartnell vs Merced`
  - `20251108_t19u` — `Hartnell vs Gavilan`
- Interpretation:
  - this no longer looks like six unrelated parser misses
  - it looks like a Hartnell-centered low- or no-PBP coverage pattern in the source data
- Next diagnostic path:
  - repeat the same missing-game breakdown for other high-frequency missing opponents such as `Feather River` and `Gavilan`
  - maintain a running list of likely low-PBP-coverage schools so future aggregate mismatches can be interpreted correctly

### Low-PBP coverage cluster
- Follow-up missing-game breakdowns suggest that some of the remaining gaps are better understood as a source-coverage cluster rather than isolated one-off misses.
- Confirmed overlapping missing-game patterns:
  - `Hartnell`
  - `Feather River`
  - `Gavilan`
  - `Siskiyous`
- Supporting examples:
  - `Feather River` missing-game set includes games versus `Gavilan`, `Hartnell`, `Cabrillo`, and `Siskiyous`
  - `Gavilan` missing-game set includes games versus `Siskiyous`, `Feather River`, `San Joaquin Delta`, and `Hartnell`
- Interpretation:
  - remaining missing play-by-play coverage is not purely school-by-school
  - some schools appear in a small low-coverage network where games involving either side are more likely to have no usable PBP
- Practical validation takeaway:
  - when a team's season totals are short by exactly one or a few games, check whether the missing opponent falls inside this low-coverage cluster before assuming a parsing bug
- Additional one-off checks reinforced the same cluster interpretation:
  - `Cabrillo`'s remaining missing game is against `Feather River`
  - `San Joaquin Delta`'s remaining missing game is against `Gavilan`
- This suggests some apparent single-school one-off gaps are really edges of the same low-PBP network rather than independent failures.

## 2026-06-30

### Interception return yardage bug found
- While reconciling Ventura team passing against the official season log, identified a play-level accounting bug in:
  - `20251011_cdcb` (`Ventura at Allan Hancock`)
- Symptom:
  - official Ventura passing for the game was `11-22-1` for `173` yards
  - DuckDB matched attempts, completions, interceptions, and touchdowns, but only produced `132` passing yards
- Root cause:
  - an intercepted pass was correctly parsed as:
    - `is_pass_attempt = true`
    - `completion = false`
    - `is_interception = true`
    - `yards_gained = 0`
  - but later in `parse_pbp_html()`, the generic fumble-recovery yardage adjustment overwrote that with `-41`
  - the trigger was an interception return that itself ended with a defensive fumble/recovery, causing the parser to treat the defender return location as offensive pass yardage
- Fix direction:
  - keep offensive pass yardage at `0` for intercepted passes
  - skip the fumble-based yardage rewrite when the parsed play is already marked `is_interception`
- Why this matters:
  - the same pattern can appear in other games
  - this is a clean parser/accounting bug, not a scraping coverage issue
- Data refresh note:
  - this fix should only require re-parsing from stored `raw_pbp_html`
  - no re-scrape should be needed unless the raw source itself was missing

### Offensive yardage semantics
- Clarified the intended meaning of offensive `yards_gained` for team-stat reconciliation.
- Rule:
  - offensive yardage should stop at the point where possession changes
  - any later return yards belong to the return event, not to offensive production
- Confirmed implications:
  - offensive pass yards are always `0` on any interception
  - interception return yards should not count as offensive passing yards
  - interception-return fumble yards should not count as offensive passing yards either
  - fumble return yards after an offensive fumble should not add to offensive rushing or passing totals
- Practical interpretation:
  - the offense keeps only the gain/loss up to the turnover spot
  - post-turnover movement is separate context for later analysis, not part of team offense
- Parser consequence:
  - once a play is classified as a turnover event, downstream return/recovery location text must not overwrite offensive `yards_gained`
- Why this breadcrumb matters:
  - it gives a stable accounting rule for future parser edge cases
  - it keeps team rushing, passing, and total offense aligned with official box-score semantics

### Quarter-start possession reset bug found
- While continuing Ventura/Bakersfield validation, found a second structural parser bug in:
  - `20250913_z92j`
- Symptom:
  - a third-quarter `Chase Furtado -> Dylan Johnson for 6 yards` completion was being credited to `Ventura`
  - that produced an extra `+1 completion`, `+1 attempt`, and `+6 passing yards` for Ventura
- Root cause:
  - the raw PBP used a quarter-start line with embedded possession text:
    - `Start of 3rd quarter, clock 15:00, BAKERSFI ball on BAKERSFI25.`
  - the parser recognized the quarter change but did not reset offense/defense from the embedded `TEAM ball on ...` token
  - offense therefore leaked forward from the prior half until a cleaner possession cue appeared
- Fix direction:
  - treat quarter-start lines with embedded `TEAM ball on ...` text as valid possession resets
  - reuse the same possession-resolution logic for:
    - standalone `TEAM ball on ...` rows
    - quarter-start rows that embed the same phrase
- Why this matters:
  - this is not a one-off Ventura bug
  - it affects any source page that compresses quarter start and possession reset into a single sentence

### Conversion-try accounting rule added
- While validating `20250830_fzzx` (`Ventura at Palomar`), isolated a remaining season-passing mismatch to a post-touchdown try play:
  - `Braesen Leon pass attempt to TEAM failed (intercepted), returned by Hunter Stowe.`
- Surrounding sequence confirmed this occurs:
  - immediately after a Ventura rushing touchdown
  - immediately before the ensuing kickoff
- Accounting interpretation:
  - this is a conversion try, not a standard offensive passing play
  - it should not count toward official team passing attempts, interceptions, or yards
- Schema / parser decision:
  - added explicit `plays.is_conversion`
  - explicit pass-try rows now parse as:
    - `play_type = 'two_point'`
    - `is_conversion = true`
    - `is_dropback = false`
    - `is_pass_attempt = false`
    - `is_rush_attempt = false`
    - `is_interception = false`
- Aggregate rule going forward:
  - conversion tries should add no normal passing, rushing, or interception stats even before aggregation
- Why this is better than a one-off patch:
  - it preserves the raw football event for context
  - it makes future audits easy if another try-format edge case appears
  - it keeps official team stat reconciliation correct by parsed-play semantics, not just downstream filtering

### Conversion-try reparse validation
- Rebuilt `plays` from stored `raw_pbp_html` after the try-play semantic change.
- New completed reparse run:
  - `85e57f9b-2363-4244-8d23-a1085093dcc7`
- Confirmed the motivating Palomar check now matches the official team line exactly for `Ventura` in `20250830_fzzx`:
  - `37` pass attempts
  - `19` completions
  - `220` passing yards
  - `0` interceptions
  - `1` passing touchdown
- Takeaway:
  - the post-touchdown try is now retained as an event in `plays`
  - but it no longer leaks into standard passing/interception accounting

### Defensive fumble-return touchdown fix
- While validating Long Beach season passing totals, found one remaining extra passing touchdown.
- The bad row was:
  - `20250906_t3z9`
  - `play_id 44`
  - `Wyatt McCauley sacked for loss of 1 yard ... fumble ... recovered by MT. SAN ... TOUCHDOWN`
- Root cause:
  - sacks are intentionally kept as `play_type = 'pass'` for dropback context
  - but the parser was letting a defensive fumble-return touchdown stay attached to the offensive row as `is_td = true`
- Fix direction:
  - when a fumble row ends in a touchdown and the recovery team matches the defense, clear offensive `is_td`
  - keep offensive yards only to the turnover point
- Additional hardening:
  - widened the defensive-recovery team matching logic for source tokens like `MT. SAN ...`
- Validation after reparse:
  - Long Beach season passing now matches the official site exactly:
    - `393` attempts
    - `220` completions
    - `3129` passing yards
    - `9` interceptions
    - `30` passing touchdowns

### Contradictory drive-label possession fix
- While validating San Francisco season passing, found a fragile source-format issue in:
  - `20250927_6pu6` (`San Francisco vs Sierra`)
- Symptom:
  - four real San Francisco completions were present in raw HTML but were not being credited to `offense = 'San Francisco'`
  - the missing chunk was exactly:
    - `4` completions
    - `60` passing yards
    - `1` passing touchdown
- Root cause:
  - the source emitted contradictory possession cues in this order:
    - stale/bad drive header: `Sierra at 00:56`
    - `Sierra drive start at 00:56.`
    - `CCSF ball on CCSF40, clock 00:56.`
    - `San Francisco drive start at 00:56.`
  - the parser previously ignored explicit `Team drive start at ...` rows
  - it also allowed unknown `TEAM ball on ...` tokens to overwrite offense with non-canonical junk like `CCSF`
- Fix direction:
  - treat explicit `Team drive start at ...` rows as authoritative possession resets
  - keep drive headers as weaker hints only
  - ignore unknown `TEAM ball on ...` abbreviations unless they map cleanly to the known home/away teams
- Why this is an important weakness breadcrumb:
  - the source can contradict itself mid-drive
  - future failures may come from malformed possession labels rather than missing games
  - this class of bug is a good candidate for later automated anomaly detection when raw HTML contains conflicting possession cues for the same timestamp

### Ghost-drive residue after possession fix
- After the contradictory-drive possession fix was reparsed into:
  - `ec2b4ae5-7bbb-403d-84bc-71f16339ba3a`
- San Francisco vs Sierra (`20250927_6pu6`) improved to the correct:
  - `18` completions
  - `320` passing yards
  - `0` interceptions
  - `2` passing touchdowns
- But the game still shows an attempts mismatch:
  - DuckDB: `27 att / 18 comp`
  - official: `22 att / 18 comp`
- This indicates the main ghost-drive possession error is fixed, but malformed source rows still survive as parsed football events.
- Current smoking-gun example:
  - parsed `play_id 88`
  - `Andre Watson punt no gain to the CCSF40, downed.`
- Why this matters:
  - the row appears immediately after Sierra's real punt and immediately before the restored San Francisco completion sequence
  - that strongly suggests we still need a second layer of control-row / duplicate-event hardening for malformed ghost-drive regions
- Working interpretation:
  - possession attribution is now mostly correct
  - event suppression for malformed duplicate rows is still incomplete

### San Francisco vs Sierra attempts reconciliation
- Follow-up validation for `20250927_6pu6` showed the remaining `27 att / 18 comp / 320 yds / 0 int / 2 td` line is supported by:
  - the raw play-by-play page
  - the game-level box score
- Important correction:
  - the earlier `official: 22 att / 18 comp` comparison came from a season-level stats page and does **not** appear to match the game-level source documents for this game
- Decision:
  - keep the narrow suppression for the clearly bogus ghost-drive punt residue:
    - `Andre Watson punt no gain to the CCSF40, downed.`
  - do **not** add any broader pass-attempt suppression rules for this game
- Rationale:
  - the fake punt is malformed source residue and should not survive parsing
  - the remaining San Francisco incompletions are present as ordinary football plays in the raw PBP and should be preserved
  - we should prefer the game-level raw/box sources over a contradictory season aggregate page when deciding whether to suppress parsed events

### Passing validation checkpoint
- Rebuilt full-season `plays` from stored raw HTML into:
  - `63fa3f95-a627-44fe-851a-d7463fcab7b6`
- Confirmed exact season passing matches against the official `2025-26` site for:
  - `Riverside`
  - `Moorpark`
  - `Citrus`
  - `San Francisco`
  - `Long Beach`
  - `Foothill`
- Confirmed additional strong matches or near-matches that no longer look urgent:
  - `Ventura`
  - `Pasadena City`
  - `Golden West`
  - `Mt. San Antonio`
  - `Southwestern`
  - `Fullerton`
  - `Reedley`
  - `Shasta`
  - `San Mateo`
  - `Laney`
  - `Compton`
- Remaining weaker teams fall into two broad buckets:
  - likely low-/missing-PBP coverage cluster:
    - `Hartnell`
    - `Feather River`
    - `Gavilan`
    - related schools already seen in that network such as `Cabrillo`, `Chabot`, `Merced`, `San Joaquin Delta`, `Siskiyous`
  - meaningful remaining validation targets where parser/accounting issues may still exist:
    - `Los Medanos`
    - `Victor Valley`
    - `Monterey Peninsula`
    - `Santa Monica`
    - `Mt. San Jacinto`
    - `Fresno City`
    - `LA Valley`
    - `Contra Costa`
- Most promising next targeted parser audit when work resumes:
  - `Los Medanos`
- Reason:
  - it is high on the passing leaderboard
  - the gap is large enough to be worth attention
  - and it may expose either a small number of missing games or a real remaining parser issue rather than just the already-known low-coverage school cluster

### Victor Valley vs Santa Monica source-side discrepancy
- Investigated `Victor Valley` passing mismatch for:
  - `20251116_5n02`
  - `Santa Monica at Victor Valley`
  - `November 16, 2025`
- DuckDB / parsed public PBP currently shows:
  - `29 comp`
  - `39 att`
  - `248 yds`
  - `3 pass TD`
  - `1 INT`
- Official game-level box-score passing table shows:
  - `Seth Burbine 30-38, 339 yds, 4 TD, 1 INT`
  - `Ricky Sampson 0-1, 0 yds, 0 TD, 0 INT`
- Confirmed:
  - the stored `raw_pbp_html` rows for `20251116_5n02` are all correctly tied to the `November 16, 2025` game
  - this is **not** a bad `game_id` / opponent-pairing issue despite Victor Valley playing Santa Monica twice in `2025-26`
  - the public `?view=plays` page itself only exposes `3` Victor Valley passing touchdowns:
    - `Seth Burbine -> Darren Gandy` for `4`
    - `Seth Burbine -> Darren Gandy` for `2`
    - `Seth Burbine -> Cael Meisman` for `19`
- Additional important clue from the site scoring summary:
  - one `4th quarter` summary row is mislabeled as:
    - `Victor Valley - Dylan Moreno pass complete to Bryson Wood for 39 yards ...`
  - but `Dylan Moreno` and `Bryson Wood` are `Santa Monica`, and the surrounding score flow confirms it is a `Santa Monica` touchdown
- Working conclusion:
  - DuckDB is matching the visible public play-by-play for this game
  - the `3C2A` source pages are internally inconsistent for this game
  - this is best treated as a **source-side stat discrepancy**, not a current parser bug
- Current policy implication:
  - keep `plays` as `PBP-truth` for play-derived modeling
  - note that some team-level validations against official aggregate/box pages may require a future box-score reconciliation layer

### Passing checkpoint: good enough to proceed
- Current `2025-26` season passing totals are in a usable place for play-by-play-driven tendency work.
- Decision:
  - do **not** keep chasing exact official season passing reconciliation right now
  - accept remaining mismatches where they are clearly driven by:
    - low / missing public PBP coverage
    - source-side page inconsistencies
    - noisy control/state rows in public PBP
- Teams that now look broadly reliable for PBP-derived passing work include:
  - `Riverside`
  - `Diablo Valley`
  - `Sequoias`
  - `Ventura`
  - `Moorpark`
  - `Citrus`
  - `Pasadena City`
  - `Golden West`
  - `Long Beach`
  - `De Anza`
  - `Cerritos`
  - `San Francisco`
  - `Grossmont`
  - `Mt. San Antonio`
  - `Southwestern`
  - `Palomar`
  - `Coalinga`
  - `Antelope Valley`
  - `Glendale`
  - `El Camino`
  - `Saddleback`
  - `Fullerton`
  - `West LA`
  - `Reedley`
  - `Shasta`
  - `San Mateo`
  - `Laney`
  - `Foothill`
- Teams with remaining known weakness / unresolved passing reconciliation are left as future work, especially:
  - `Los Medanos`
  - `Victor Valley`
  - `Monterey Peninsula`
  - `Santa Monica`
  - `Mt. San Jacinto`
  - `LA Valley`
  - `Contra Costa`
  - `San Joaquin Delta`
  - `Cabrillo`
  - `Desert`
  - `American River`
  - `Chabot`
  - `Merced`
  - `LA Pierce`
  - `Feather River`
  - `Gavilan`
  - `Hartnell`
- Next step after this checkpoint:
  - shift validation attention to `rushing`, using the same philosophy:
    - prefer public PBP as modeling truth
    - log known source mismatches
    - avoid forcing exact official reconciliation where source pages conflict

### Rushing checkpoint: missing-game coverage is real for some programs
- While reviewing the `2025-26` rushing mismatches, separated two different failure shapes:
  - real missing-game public PBP coverage
  - games present in public PBP but still disagreeing with official totals
- Using:
  - structure run `4b573736-96bb-4939-8ea8-661f0e51ddfc`
  - rebuilt plays run `63fa3f95-a627-44fe-851a-d7463fcab7b6`
- Confirmed missing-PBP cluster counts for the weaker teams:
  - `Hartnell`: `6` missing games
  - `Feather River`: `4` missing games
  - `Gavilan`: `4` missing games
  - `Siskiyous`: `2` missing games
  - `Cabrillo`: `1` missing game
  - `Chabot`: `1` missing game
  - `Contra Costa`: `1` missing game
  - `LA Valley`: `1` missing game
  - `Los Medanos`: `1` missing game
  - `Merced`: `1` missing game
  - `San Joaquin Delta`: `1` missing game
- Confirmed the main missing-opponent islands are:
  - `Hartnell` (`6` distinct games)
  - `Feather River` (`4`)
  - `Gavilan` (`4`)
  - `Siskiyous` (`2`)
- Practical interpretation:
  - for programs like `Hartnell`, `Feather River`, `Gavilan`, `Siskiyous`, `Cabrillo`, `Chabot`, `Contra Costa`, `Los Medanos`, `Merced`, and `San Joaquin Delta`, a meaningful share of the rushing gap is explained by **real absent public PBP**, not just parser logic
  - this makes those teams weak candidates for exact season-total reconciliation from `plays` alone
- Also useful to note the opposite case:
  - some teams still look off **without** a corresponding missing-game explanation, so they stay in the "source weirdness / accounting / future audit" bucket
  - especially `Victor Valley`, `San Francisco`, `De Anza`, `West LA`, `LA Southwest`, `Monterey Peninsula`, and `LA Pierce`
- Takeaway:
  - "missing games is real for some programs" is now a documented fact, not just a suspicion
  - future validation should first ask:
    - is this team inside a missing-PBP cluster?
    - or is this a present-but-weird source/accounting case?

### Session wrap / frozen checkpoint
- Freeze decision for `2025-26`:
  - treat the current rebuilt `plays` layer as stable enough for team tendency/context work
  - do **not** keep trying to force exact official stat-page reconciliation inside the `plays` parser
  - keep known weak programs documented rather than silently "fixing" them with overrides
- Frozen working baseline:
  - structure run: `4b573736-96bb-4939-8ea8-661f0e51ddfc`
  - plays scrape source run: `75e20b24-e705-463c-b966-59d32dd2d361`
  - current frozen full reparse baseline: `63fa3f95-a627-44fe-851a-d7463fcab7b6`
- Current high-level stance:
  - `plays` = tendency/context truth
  - future `box score` layer = official game-performance / validation truth
  - reconciliation should live in an explicit audit layer later, not as silent overwrite logic
- Recommended next implementation track:
  - create a parallel box-score layer for later validation and missing-PBP coverage support
  - suggested tables:
    - `raw_boxscore_html`
    - `box_score_team_stats`
  - keep this separate from `plays`
- Recommended derived-football track after that:
  - build `team_game_stats` from `plays`
  - build `team_season_stats` on top of `team_game_stats`
  - preserve the current semantics:
    - `is_dropback`
    - `is_pass_attempt`
    - `is_rush_attempt`
    - `is_sack`
  - then add situational rollups such as:
    - down / distance
    - normalized field position
    - red zone
    - quarter / clock bucket
    - score margin
- Practical plan for next session:
  - `1.` scaffold the box-score ingestion layer without changing the existing `plays` pipeline
  - `2.` scrape/store one season of raw box-score pages by `game_id`
  - `3.` parse team-level official game stats into a separate curated table
  - `4.` compare `plays`-derived `team_game_stats` vs `box_score_team_stats` game by game
  - `5.` only then decide if any targeted reconciliation rules are worth adding
