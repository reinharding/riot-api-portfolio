---
status: ready-for-agent
tracker: local (.scratch/tilt-pipeline/issues/ — created by /to-tickets)
---

# League of Legends Session-Fatigue / Tilt-Detection Pipeline

## Problem Statement

The author is building a portfolio project to support Riot Games Summer 2027 internship applications (Data Science Intern / Insights Analyst Intern tracks). A prior attempt at a similar project had a disqualifying flaw — it keyed ingestion on summoner name instead of PUUID, so it silently broke whenever a tracked player renamed their account — and, more fundamentally, it read as a one-off analysis script rather than evidence of systems-engineering judgment. The author needs a project that demonstrates continuous, safely-repeatable data engineering (not just "a script that pulled data once") alongside genuine statistical rigor, without requiring production infrastructure, a public deployment, or a production Riot API key — none of which fit a solo, unpaid, personal project.

## Solution

A local, Postgres-backed pipeline that ingests League of Legends match history by PUUID for a single consenting player, using idempotent upsert-plus-watermark tracking so any run is safely repeatable; logs every run (manual or scheduled) to a run-history table so the pipeline's operational behavior is visible and auditable; validates its own output with data-quality checks tuned to its real, manually-triggered operating cadence rather than an idealized always-on one; and, once enough data has accumulated, runs a within-player statistical analysis to detect in-session performance decline ("tilt"). Every methodology choice in the statistical phase (role-adjusted composite metric, a session-boundary threshold frozen before looking at outcomes, a pre-committed minimum sample size) was chosen specifically to survive scrutiny from a technical interviewer, not just to produce a result. The deliverable is the local pipeline, its repository, its documentation (README, `CONTEXT.md`, ADRs), and the Phase 4 findings — not a hosted, publicly-accessible product.

## User Stories

1. As the pipeline operator, I want to ingest a player's match history keyed by PUUID rather than summoner name, so that a renamed account doesn't silently break ingestion the way it did in a prior project.
2. As the pipeline operator, I want each ingestion run to resume from a per-PUUID watermark rather than re-fetching all history, so that re-running the pipeline doesn't waste API calls or redo finished work.
3. As the pipeline operator, I want new match and participant rows written via an idempotent upsert (`ON CONFLICT DO UPDATE`), so that running ingestion twice on the same data never produces duplicates or corrupted state.
4. As the pipeline operator, I want the row upserts and the watermark advance to happen inside a single database transaction, so that a failure partway through a run never leaves the watermark pointing past data that wasn't actually saved, or vice versa.
5. As a technical interviewer reviewing this project, I want to see a testable idempotency guarantee, so that I can trust the engineering claim is demonstrated, not just asserted.
6. As the pipeline operator, I want ingestion scoped to a small, known pool of players (starting with one consenting friend's account), so that the personal Riot API key's usage stays unambiguously within Riot's personal-key policy.
7. As the friend whose account is the data source, I want my real identity kept out of anything public-facing, so that my match history is used with my consent but without exposing who I am.
8. As the pipeline operator, I want every ingestion run logged to a `pipeline_runs` table with start time, end time, and status, so that I have an operational history instead of a black box.
9. As the pipeline operator, I want each run tagged with a `trigger_type` of manual or scheduled, so that the manual-key-refresh limitation is a visible, documented fact in the data rather than a hidden gap.
10. As a technical interviewer, I want to see the author design for the real constraint of a personal API key (no unattended 24/7 automation) rather than pretend it doesn't exist, so that I trust their judgment about production tradeoffs.
11. As the pipeline operator, I want automated data-quality checks (freshness, row-count bounds, null rates, referential integrity) run after each ingestion, so that data problems are caught before reaching the statistical analysis.
12. As the pipeline operator, I want the freshness check defined relative to the last successful watermark advance rather than wall-clock time, so that it doesn't false-alarm under a deliberately manual/irregular schedule.
13. As the pipeline operator, I want data-quality results recorded durably, so that I can show a track record of the pipeline's data health, not just one passing run.
14. As a technical interviewer, I want to see quality checks tuned to the system's actual operating cadence, so that I can tell the difference between a textbook DQ check and one fitted to the real architecture.
15. As the project author, I want in-game performance converted to a role-adjusted composite z-score rather than a raw stat like KDA, so that role differences aren't mistaken for a tilt signal.
16. As the project author, I want the session-boundary gap threshold frozen via sensitivity testing on play-pattern data alone, before looking at any performance outcome, so that the threshold isn't tuned to manufacture the effect I'm trying to detect.
17. As the project author, I want a pre-committed minimum sample size (30 ranked games) before running the within-player model, so that an underpowered result never gets presented as a finished, trustworthy finding.
18. As the project author, I want a within-player fixed-effects/hazard-style model of performance across a session, so that I can detect whether performance predictably declines the longer a session runs.
19. As a technical interviewer, I want to see the author acknowledge and design around selection/survivorship bias (e.g., players quitting when they're losing badly), so that I trust the statistical conclusions weren't naively drawn.
20. As the project author, I want the pipeline to keep ingesting rather than run the model early if the 30-game floor isn't met, so that I never ship a result I know is underpowered.
21. As the project author, I want the README to explicitly state that the engineering layer (Phases 1-3) is the intended headline differentiator while Phase 4's rigor reflects front-loaded effort on a skill I'm actively building, so that a reviewer doesn't read the time-allocation mismatch as inconsistency.
22. As the project author, I want every non-obvious architectural decision (Postgres over SQLite, personal key with manual refresh, closed player pool, watermark-relative freshness) captured as an ADR, so that a reviewer, or future me, can see the reasoning behind the code.
23. As the project author, I want a living glossary (`CONTEXT.md`) of this project's terms (PUUID, watermark, trigger type, session), so that the codebase and documentation stay consistent and unambiguous.
24. As the project author, I want the entire system runnable locally with no live public deployment, so that I never expose my personal API key to uncontrolled public traffic or take on hosting.

## Implementation Decisions

- **Modules:**
  - `ingestion`: `run_ingestion(puuid) -> IngestionResult`. Given a PUUID, reads its `ingestion_watermark`, fetches match IDs newer than that watermark from the Riot API, upserts rows into `matches` and `participants`, then advances the watermark — the upsert and the watermark advance happen inside one transaction.
  - `scheduling`: `run_pipeline(trigger_type)`, a thin wrapper around `run_ingestion` that writes a row to `pipeline_runs` (start time, end time, status, `trigger_type`).
  - `data_quality`: `run_data_quality_checks() -> list[CheckResult]`, standalone, reads directly from the Postgres tables independent of the ingestion flow.
  - `analysis` (Phase 4): a validated script/notebook, not a general-purpose tested module — implements the z-score composite metric, the frozen session definition, and the within-player mixed-effects/hazard model, gated behind the 30-game floor.
- **Schema:** Postgres tables `matches`, `participants`, `ingestion_watermark` (per-PUUID), `pipeline_runs` (includes `trigger_type`). Session boundaries are not a precomputed schema value — the gap threshold is determined at analysis time via sensitivity testing (Phase 4), per `CONTEXT.md`'s "Session" entry.
- **Test subject:** one consenting friend's account, referred to only as "Player A" in anything public-facing (README, writeup, charts); their real PUUID/Riot ID may remain in local, git-ignored data (e.g. `data/seed_puuids.json`, `.env`) per ADR 0003.
- **Minimum sample:** 30 ranked games required before Phase 4's model runs. If unmet, Phase 4 is explicitly blocked — the pipeline keeps ingesting rather than running an underpowered model.
- **Freshness semantics:** per ADR 0004, defined relative to the last successful `ingestion_watermark` advance, not wall-clock time; "days since last run" is tracked as a separate, non-alerting metric.
- **API usage:** personal Riot API developer key with manual daily refresh (ADR 0002) — no production key, no requirement for an unattended 24/7 scheduler.
- **Deployment:** none. Local pipeline + repository + README is the entire deliverable (ADR 0003).

## Testing Decisions

- Tests exercise real behavior against a real test Postgres instance — no mocking the database layer, consistent with the project's reasoning for choosing Postgres over SQLite in the first place (ADR 0001).
- `run_ingestion(puuid)`: test (a) correct row creation on a first run, (b) no duplicate/corrupted rows when re-run against the same source data, (c) correct watermark advance, (d) full rollback with no partial writes when a failure is simulated mid-batch.
- `run_pipeline(trigger_type)`: test that `pipeline_runs` rows are written with correct status, `trigger_type`, and timestamps — does not need to re-verify `run_ingestion`'s internal logic, only that the wrapper logs correctly around a call to it.
- `run_data_quality_checks()`: test by seeding deliberately bad rows (a stale watermark, an orphaned participant row, an out-of-bounds row count, a null in a required field) and asserting each specific check fires — and test that no check fires on healthy seeded data (no false positives).
- Phase 4 (`analysis`) is explicitly excluded from the automated test suite (see Out of Scope); it is instead validated against documented acceptance criteria — the session threshold was sensitivity-tested, the 30-game floor was met, and the z-score computation matches hand-calculated spot checks.
- No existing test suite in this repo yet (fresh start after archiving the prior design) — Phase 1's tests set the pattern the later phases follow.

## Out of Scope

- Kafka, Spark, Kubernetes, dbt, feature stores, deep learning, SQLite, or any live public deployment.
- Automated unit testing of the Phase 4 statistical analysis as if it were a standard software module — validated via acceptance criteria instead.
- Expanding the player pool beyond the one consenting friend's account — a future multi-player expansion would be a separate spec.
- Obtaining a production Riot API key or going through Riot's app-review process.
- Real-time or streaming ingestion — this is a batch, on-demand pipeline.
- Building a UI or dashboard beyond the README write-up of findings.
- Setting up a real issue tracker (GitHub Issues, Linear, etc.) — this project is tracked locally under `.scratch/tilt-pipeline/issues/`.

## Further Notes

- Earlier artifacts from an abandoned prior design (`.worktrees/lol-ingestion-pipeline/`, `docs/superpowers/{plans,specs}/2026-08-06-*`) remain in the repository but are superseded and not referenced by this spec.
- This is a multi-week, multi-session build. Tickets generated from this spec via `/to-tickets` should declare blocking edges and be implemented one at a time with context cleared between them, since each phase is self-contained once its blockers are satisfied.
- `CONTEXT.md`'s "Session" glossary entry is intentionally left under active definition — the exact gap threshold is a Phase 4 deliverable determined via sensitivity testing, not something this spec pre-decides.
