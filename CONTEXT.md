# Riot API Tilt/Session-Fatigue Pipeline

A portfolio data pipeline over League of Legends match history for a small, known pool of players, built to demonstrate idempotent ingestion and systems-engineering discipline as the headline skill, with a within-player statistical analysis of performance decline as the secondary (but deliberately unrushed) phase.

## Language

**PUUID**:
Riot's permanent, non-reassignable player identifier. The sole identity key used everywhere in this pipeline (ingestion, watermarking, data quality checks) — never the player's display name.
_Avoid_: Summoner name, Riot ID, gameName#tagLine (these can change and must never be used as a storage key; a prior project broke silently on player renames by keying on summoner name instead)

**Watermark**:
The `ingestion_watermark` table's per-PUUID record of the last successfully processed match, used to make re-running ingestion safe (no duplicate or lost rows).
_Avoid_: Checkpoint, cursor (as far as this project's code/docs go, use "watermark" consistently)

**Trigger Type**:
The `pipeline_runs.trigger_type` column recording whether a given ingestion run was started manually (daily key refresh) or on a schedule. Exists so the manual-refresh design is a documented, visible tradeoff rather than an invisible limitation.

**Session** *(under active definition — gap threshold not yet locked)*:
A run of games by one player treated as temporally contiguous, bounded by a maximum gap between consecutive game-end and next game-start. The exact gap threshold is being decided via sensitivity testing (Phase 4), not assumed.
