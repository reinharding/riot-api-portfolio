# LoL Tilt/Session-Fatigue Pipeline

A local, Postgres-backed data pipeline that ingests League of Legends ranked match history for one consenting player ("Player A") by PUUID, then runs a within-player statistical analysis of whether performance predictably declines the longer a play session runs.

**What this project is a portfolio piece for:** systems-engineering discipline first, statistical rigor second. The engineering layer — idempotent ingestion, run-history logging, data-quality checks, all keyed on PUUID rather than a renameable summoner name — is the intended headline differentiator. Phase 4's statistical model is real and honestly reported, but its time investment reflects front-loaded effort on a skill I'm actively building, not the primary claim of this project. If the code and the write-up seem to spend disproportionate care on the engineering plumbing relative to the final statistical result, that's deliberate, not an oversight.

## Architecture

Every stage is a small, independently-runnable script under `scripts/`, backed by a local Postgres instance (`docker-compose.yml`).

1. **`scripts/migrate.py`** — applies `schema.sql` (idempotent: `CREATE TABLE IF NOT EXISTS`).
2. **`scripts/ingestion.py`** (`run_ingestion(puuid)`) — reads the PUUID's `ingestion_watermark`, fetches new match IDs from the Riot API, upserts `matches`/`participants` rows, and advances the watermark, all inside one transaction. Re-running it is always safe: no duplicate rows, and a mid-batch failure rolls back completely.
3. **`scripts/pipeline.py`** (`run_pipeline(trigger_type)`) — wraps `run_ingestion` with a `pipeline_runs` row (start/end time, status, `trigger_type`), so every run has an operational record instead of being a black box.
4. **`scripts/data_quality.py`** (`run_data_quality_checks()`) — freshness (relative to the last successful watermark advance, not wall-clock time), row-count bounds, null rates, and referential integrity, read directly from Postgres after each run.
5. **Phase 4 analysis** — `scripts/composite_metric.py`, `scripts/session_boundary_analysis.py`, `scripts/session_assignment.py`, and `scripts/tilt_model.py`, gated on a 30-game floor (`scripts/game_floor.py`). See [Phase 4 findings](#phase-4-findings) below.

PUUID (Riot's permanent player identifier) is the only identity key used anywhere in this pipeline — never summoner name or Riot ID, which can change and previously broke a prior version of this project silently. See `CONTEXT.md` for this project's full glossary.

## Setup

1. Get a dev API key from the [Riot Developer Portal](https://developer.riotgames.com/) (expires every 24h; regenerate and re-paste into `.env` as needed — this is a deliberate design tradeoff, see [ADR 0002](docs/adr/0002-personal-key-manual-refresh.md)).
2. Copy `.env.example` to `.env` and fill in `RIOT_API_KEY`, `DATABASE_URL`, `TEST_DATABASE_URL`, and `TRACKED_PUUIDS` (Player A's PUUID — never their Riot ID).
3. `pip install -r requirements.txt`
4. `docker compose up -d` — starts local Postgres.
5. `python scripts/migrate.py` — applies the schema.
6. `python scripts/pipeline.py` — runs one manual ingestion pass for every PUUID in `TRACKED_PUUIDS`.
7. `pytest` — runs the test suite against `TEST_DATABASE_URL`, a real Postgres instance rather than a mocked DB layer, consistent with [ADR 0001](docs/adr/0001-postgres-over-sqlite.md)'s rationale for choosing Postgres in the first place.

To re-run ingestion later (e.g. after the dev key expires), just regenerate the key and re-run step 6 — `pipeline_runs.trigger_type` records that this was a manual run, not a scheduled one, making that limitation visible rather than hidden.

## Design decisions

Every non-obvious architectural choice is captured as an ADR:

- [0001 — Postgres over SQLite](docs/adr/0001-postgres-over-sqlite.md)
- [0002 — Personal API key with manual refresh, not a production key](docs/adr/0002-personal-key-manual-refresh.md)
- [0003 — Closed player pool, no public-facing deployment](docs/adr/0003-closed-player-pool-no-public-deployment.md)
- [0004 — Data freshness measured relative to the watermark, not wall-clock time](docs/adr/0004-freshness-relative-to-watermark.md)
- [0005 — Session gap threshold frozen at 45 minutes via sensitivity testing](docs/adr/0005-session-gap-threshold-45-minutes.md)

Together, ADRs 0002 and 0003 are the project's core constraint: a personal Riot API key only covers personal use by a small, known pool of players, not a publicly-hosted app. Rather than fight that constraint, this project is designed around it — one consenting friend's account ("Player A," never identified by real name or Riot ID in anything public-facing), no live deployment, and a manual daily key refresh instead of unattended 24/7 automation.

## Phase 4 findings

Once 30 non-remake ranked games are ingested for Player A (`scripts/game_floor.py`'s gate), a within-player fixed-effects model (`scripts/tilt_model.py`) tests whether the composite performance metric (`scripts/composite_metric.py`: kill participation, damage share, deaths, gold/min, z-scored within role) declines across a session, where "session" is a run of games separated by no more than 45 minutes ([ADR 0005](docs/adr/0005-session-gap-threshold-45-minutes.md)), a threshold locked via sensitivity testing on raw timestamps *before* the composite metric was ever consulted, to avoid tuning the session definition to manufacture a result.

The current finding, on 36 ingested games (23 sessions, only 6 with more than one game): **no statistically significant decline was detected** (coefficient +0.168, SE 0.139, p = 0.252 — nominally an improvement, not a decline). Full write-up, including the survivorship-bias caveat and why the effective sample is smaller than the headline game count, is in [docs/analysis/phase4-tilt-findings.md](docs/analysis/phase4-tilt-findings.md). This is reported as-is rather than re-tuned toward a more publishable-looking result, consistent with the anti-circularity design in ADR 0005.
