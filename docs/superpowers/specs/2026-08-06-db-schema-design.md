# Database Schema Design — LoL Analytics Portfolio Project

**Date:** 2026-08-06
**Status:** Approved
**Companion doc:** [2026-08-06-db-schema-implementation.md](./2026-08-06-db-schema-implementation.md) (full DDL + exact derivation rules, for implementation)

## Purpose

Design the storage layer for Week 1 of the Riot API portfolio project: how raw API data becomes queryable tables that support Week 3 analysis (win rates by champion/role/patch, first-blood/tower impact, gold-diff-at-15 predictor) and a Week 4 Streamlit dashboard.

## Key decisions

| Decision | Choice | Why |
|---|---|---|
| Database engine | PostgreSQL | Reads as more "production-relevant" to data analyst/data engineer recruiters than SQLite. Pairs with a free-tier hosted Postgres (Supabase/Neon) for a live, clickable Week 4 dashboard instead of a screenshot. |
| Data granularity | Match + participant + full timeline (per-minute frames *and* discrete events) | Needed for gold-diff-at-15 (frames) and first-blood/tower-impact analysis (events), not just final match summaries. |
| Raw data handling | Raw JSON kept permanently on disk, tracked via a Postgres `ingestion_log` table | Riot's rate limits make re-fetching expensive. Keeping raw files means you can fix a parsing bug and re-populate normalized tables without re-hitting the API. Keeping raw blobs *out* of Postgres avoids burning through free-tier hosted storage (~500MB–1GB) before you even get to Week 4. |

## Architecture / data flow

```
Riot API ──▶ raw files (data/raw/matches/*.json, data/raw/timelines/*.json)
                    │
                    ▼
            ingestion_log (Postgres) — tracks fetched_at / parsed_at / status per match_id
                    │
                    ▼
            transform step (Python) reads raw files ──▶ normalized Postgres tables
```

A match's life cycle: seed player → match ID discovered → raw match + timeline JSON fetched and written to disk → `ingestion_log` row marked `fetched` → transform script parses the files into normalized tables → `ingestion_log` row marked `parsed`. Failures land in `status = 'error'`, so a retry pass can just query `WHERE status != 'parsed'`.

## Tables

### Dimension tables

- **`patches`** — one row per patch version (e.g. `"14.15"`), lets `matches` and analysis queries group by patch.
- **`champions`** — champion ID → name, sourced once from Data Dragon (not from match data). Gives `participants.champion_id` a clean, human-readable join.

### Core match tables

- **`matches`** — one row per match: teams, duration, patch, winning side.
- **`teams`** — one row per side per match: win/loss, first blood/tower, objective counts (baron/dragon/herald/tower/inhibitor kills).
- **`team_bans`** — one row per banned champion per team, normalized out of `teams` so ban-rate analysis ("most banned champions this patch") is a plain `GROUP BY` instead of unpacking a JSON array.

### Participant-level tables

- **`participants`** — one row per player per match (~10/match): champion, role, KDA, gold, damage, CS, vision score, items (stored as a plain array — item-level analysis isn't a stated goal, so a full items table would be premature).
- **`participant_frames`** — per-minute timeline snapshots (gold, XP, level, CS, position) per participant. This is what powers gold-diff-at-15.
- **`events`** — discrete timeline events (kills, objective takes, wards, etc.). Common fields (`event_type`, `timestamp_ms`, `participant_id`, `team_id`) are real columns for fast filtering; type-specific extras (varies a lot by event type) live in a `details` JSONB column instead of a wide table full of nullable columns.

### Pipeline tracking

- **`ingestion_log`** — per-match_id pipeline state (`pending`/`fetched`/`parsed`/`error`), the seam Week 2 hardening builds on.
- **`seed_players`** — promotes the current `data/seed_puuids.json` file into the DB (tier, rank, LP, wins/losses, pull timestamp). Documents your sample population for the portfolio write-up ("population = N apex-tier NA players as of date X") and gives match-ID discovery a real table to query.

## Testing approach

- **Parser unit tests**: feed saved sample raw match/timeline JSON fixtures through the transform functions, assert correct normalized output — especially the `game_version` → `patch_version` truncation and `details` JSONB shaping for a couple of `event_type`s.
- **Schema constraints do a lot of the work for free**: foreign keys and primary keys catch data-quality bugs without needing custom validation code.
- **No live-API end-to-end tests in CI** — rate-limited and flaky. Fixture-based tests cover the logic that's actually likely to break.

## Explicitly out of scope

- Player-identity rollups (e.g. per-player career stats) — not needed for the stated analysis goals, which are match/participant level.
- Item-level normalization — items stored as a plain array, not a separate table.
- Champion base-stat/balance history — not modeled; `champions` is identity-only.
- Retry/backoff policy and incremental/scheduled re-crawling — deferred to Week 2 pipeline hardening.
