# Runs

This file is the quick operator ledger for important DuckDB pipeline runs.

- Use commits / `LOGS.md` for code and parser-history breadcrumbs.
- Use this file for the current reference run IDs and their relationships.

## 2025-26

### Structure

- `4b573736-96bb-4939-8ea8-661f0e51ddfc`
  - status: completed
  - counts: `66 standings`, `694 schedule`, `347 games`
  - note: current canonical structure run after schedule/home-away and canonical boxscore URL fixes

### Full-season plays scrape

- `75e20b24-e705-463c-b966-59d32dd2d361`
  - status: completed
  - source_run_id: `4b573736-96bb-4939-8ea8-661f0e51ddfc`
  - counts: `347 raw_pbp`, `56067 plays`
  - note: base full-season plays scrape for 2025-26

### Full-season reparses from stored raw PBP

- `ac58ada2-fcea-4a0c-af92-a7c13ccfe853`
  - status: completed
  - reparsed_from_plays_run_id: `75e20b24-e705-463c-b966-59d32dd2d361`
  - note: validated interception offensive-yardage fix (`INT => 0 offensive pass yards`)

- `9ef1d1d6-d9b0-4441-86d4-bedf315f0487`
  - status: completed
  - reparsed_from_plays_run_id: `75e20b24-e705-463c-b966-59d32dd2d361`
  - counts: `347 raw_pbp`, `55853 plays`
  - zero-play games:
    - `20250830_l13b`
    - `20250830_nxac`
    - `20250906_huxe`
    - `20250913_cupn`
    - `20250920_33gi`
    - `20250920_kk57`
    - `20250927_2b9n`
    - `20250927_xlfo`
    - `20251025_3ap7`
    - `20251108_t19u`
    - `20251108_xgqv`
    - `20251108_xpmu`
  - note: validated quarter-start embedded possession reset and zero-row reporting

### Field-position workflow checkpoints

- `3e4103ae-62c3-4195-9c45-71df4fcc23ce`
  - status: completed
  - note: full-season plays run used for the full field-position review/apply workflow

- `440482d8-cb31-4388-9396-8103a16b07d2`
  - status: completed
  - note: 10-game sample plays run used for early field-position validation

## Conventions

- `source_run_id`
  - the structure run that a plays run was built from

- `reparsed_from_plays_run_id`
  - a new plays run rebuilt from stored `raw_pbp_html`, not re-scraped from the site

- `current best 2025-26 structure run`
  - `4b573736-96bb-4939-8ea8-661f0e51ddfc`

- `current best 2025-26 full reparse run`
  - `9ef1d1d6-d9b0-4441-86d4-bedf315f0487`
