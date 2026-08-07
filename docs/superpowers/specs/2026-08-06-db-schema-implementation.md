# Database Schema — Implementation Spec

**Date:** 2026-08-06
**Status:** Approved
**Companion doc:** [2026-08-06-db-schema-design.md](./2026-08-06-db-schema-design.md) (rationale, in plain language — read that first for *why*)

This document is the implementation-level companion: exact DDL, derivation rules, file paths, and edge cases needed to build the ingestion + transform pipeline. If anything here conflicts with the design doc, this document wins for implementation details. This spec covers schema only — no task breakdown or step ordering; that belongs to the implementation plan.

## Environment assumptions

- Project root: `C:\Users\Soi\comp sci\projects\riot-api-portfolio`
- Python 3.13, existing venv at `.venv/`
- Target DB: PostgreSQL 15+ (local via Docker for dev; a free-tier hosted instance such as Supabase or Neon for the Week 4 dashboard deploy)
- Existing `.gitignore` already excludes `data/*.json`, `data/*.csv`, `data/*.db`, `.env`

## File layout for raw data

- `data/raw/matches/{match_id}.json` — raw response from `GET /lol/match/v5/matches/{matchId}` (regional routing, e.g. `americas`)
- `data/raw/timelines/{match_id}.json` — raw response from `GET /lol/match/v5/matches/{matchId}/timeline`
- Raw files are kept permanently (not deleted after parsing). They're covered by the existing `data/*.json` gitignore rule — no new gitignore entry needed.

## Full DDL

```sql
CREATE TABLE patches (
    patch_version TEXT PRIMARY KEY,
    notes TEXT
);

CREATE TABLE champions (
    champion_id INT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE matches (
    match_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    game_creation TIMESTAMPTZ NOT NULL,
    game_start TIMESTAMPTZ NOT NULL,
    game_duration_seconds INT NOT NULL,
    game_version TEXT NOT NULL,
    patch_version TEXT NOT NULL REFERENCES patches(patch_version),
    queue_id INT NOT NULL,
    winning_team_id INT NOT NULL CHECK (winning_team_id IN (100, 200))
);

CREATE TABLE teams (
    match_id TEXT NOT NULL REFERENCES matches(match_id),
    team_id INT NOT NULL CHECK (team_id IN (100, 200)),
    win BOOLEAN NOT NULL,
    first_blood BOOLEAN NOT NULL,
    first_tower BOOLEAN NOT NULL,
    baron_kills INT NOT NULL,
    dragon_kills INT NOT NULL,
    herald_kills INT NOT NULL,
    tower_kills INT NOT NULL,
    inhibitor_kills INT NOT NULL,
    PRIMARY KEY (match_id, team_id)
);

CREATE TABLE team_bans (
    match_id TEXT NOT NULL,
    team_id INT NOT NULL,
    champion_id INT NOT NULL REFERENCES champions(champion_id),
    pick_turn INT NOT NULL,
    PRIMARY KEY (match_id, team_id, pick_turn),
    FOREIGN KEY (match_id, team_id) REFERENCES teams(match_id, team_id)
);

CREATE TABLE participants (
    match_id TEXT NOT NULL,
    participant_id INT NOT NULL CHECK (participant_id BETWEEN 1 AND 10),
    puuid TEXT NOT NULL,
    team_id INT NOT NULL,
    champion_id INT NOT NULL REFERENCES champions(champion_id),
    team_position TEXT NOT NULL,
    kills INT NOT NULL,
    deaths INT NOT NULL,
    assists INT NOT NULL,
    gold_earned INT NOT NULL,
    damage_dealt_to_champions INT NOT NULL,
    damage_taken INT NOT NULL,
    total_cs INT NOT NULL,
    vision_score INT NOT NULL,
    items INT[] NOT NULL,
    summoner_spell_1 INT NOT NULL,
    summoner_spell_2 INT NOT NULL,
    PRIMARY KEY (match_id, participant_id),
    FOREIGN KEY (match_id, team_id) REFERENCES teams(match_id, team_id)
);
CREATE INDEX idx_participants_puuid ON participants(puuid);
CREATE INDEX idx_participants_champion ON participants(champion_id);

CREATE TABLE participant_frames (
    match_id TEXT NOT NULL,
    participant_id INT NOT NULL,
    frame_timestamp_ms INT NOT NULL,
    total_gold INT NOT NULL,
    xp INT NOT NULL,
    level INT NOT NULL,
    minions_killed INT NOT NULL,
    jungle_minions_killed INT NOT NULL,
    position_x INT,
    position_y INT,
    PRIMARY KEY (match_id, participant_id, frame_timestamp_ms),
    FOREIGN KEY (match_id, participant_id) REFERENCES participants(match_id, participant_id)
);
CREATE INDEX idx_participant_frames_timestamp ON participant_frames(match_id, frame_timestamp_ms);

CREATE TABLE events (
    event_id BIGSERIAL PRIMARY KEY,
    match_id TEXT NOT NULL REFERENCES matches(match_id),
    timestamp_ms INT NOT NULL,
    event_type TEXT NOT NULL,
    participant_id INT,
    team_id INT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_events_match_type ON events(match_id, event_type);
CREATE INDEX idx_events_details ON events USING GIN (details);

CREATE TABLE ingestion_log (
    match_id TEXT PRIMARY KEY,
    fetched_match_at TIMESTAMPTZ,
    fetched_timeline_at TIMESTAMPTZ,
    parsed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'fetched', 'parsed', 'error')),
    error_message TEXT
);

CREATE TABLE seed_players (
    puuid TEXT PRIMARY KEY,
    tier TEXT NOT NULL CHECK (tier IN ('CHALLENGER', 'GRANDMASTER', 'MASTER')),
    rank TEXT NOT NULL,
    league_points INT NOT NULL,
    wins INT NOT NULL,
    losses INT NOT NULL,
    pulled_at TIMESTAMPTZ NOT NULL
);
```

## Derivation rules (exact — implement these literally, don't reinterpret)

- **`patch_version`**: take `info.gameVersion` (e.g. `"14.15.567.1234"`), split on `.`, join the first two segments with `.` → `"14.15"`.
- **`game_creation` / `game_start`**: Riot returns epoch milliseconds (`info.gameCreation`, `info.gameStartTimestamp`) — convert to UTC `TIMESTAMPTZ`.
- **`game_duration_seconds`**: `info.gameDuration` is already in seconds for current-format matches (patch ≥ 11.20). This project only ingests current apex-ladder matches, so no legacy millisecond-format handling is needed.
- **`team_position`**: use `participant.teamPosition` (not the deprecated `lane`/`role` pair — those are unreliable on recent patches).
- **`total_cs`**: `participant.totalMinionsKilled + participant.neutralMinionsKilled`.
- **`items`**: `[item0, item1, item2, item3, item4, item5, item6]` from the participant object, in slot order. Do **not** filter out `0` values — slot position is meaningful (empty slot), not just presence.
- **`first_blood` / `first_tower`**: `team.objectives.champion.first` / `team.objectives.tower.first`.
- **Objective kill counts**: `team.objectives.{baron,dragon,riftHerald,tower,inhibitor}.kills`. Note the source field is `riftHerald`, mapped to column `herald_kills`.
- **`team_bans`**: from `team.bans[]` — each entry has `championId` and `pickTurn`. Skip entries where `championId == -1` (means no ban was made in that draft slot).
- **Timeline frames**: `info.frames[].participantFrames` is keyed by participant ID as a **string** (`"1"`–`"10"`) in the raw JSON — cast to int on insert.
- **Timeline events**: `info.frames[].events[]`. `event_type` = the raw `type` field, unchanged (e.g. `"CHAMPION_KILL"`). For the `details` JSONB column, store the event dict with the fields already promoted to real columns removed (`type` → `event_type`, `timestamp` → `timestamp_ms`, `participantId` → `participant_id`, `teamId` → `team_id`) — don't duplicate data between real columns and `details`.
- **Queue filter**: only ingest queue ID `420` (ranked solo/duo) matches, consistent with the existing seed-pull scripts.
- **`champions` dimension source**: `https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/champion.json` (Data Dragon), refreshed using the latest patch seen in `matches` — not re-fetched per match.

## Idempotency contract

- `ingestion_log.status` transitions: `pending → fetched → parsed`, or `→ error` from any state.
- A `match_id` is only (re-)fetched from the Riot API if there is no `ingestion_log` row for it, or its status is `error`.
- The transform step is a full upsert per table (`INSERT ... ON CONFLICT (...) DO UPDATE`), so re-running transform on an already-fetched match is always safe and idempotent — no special-casing needed for "already parsed" matches beyond the upsert itself.

## Explicitly out of scope for this spec

- Retry/backoff policy for API errors (Week 2 pipeline hardening)
- Incremental/scheduled re-crawling of the ladder (Week 2)
- Any actual ingestion or transform code — this spec defines the target schema only; implementation steps belong in the plan produced by the writing-plans skill.
