-- Tilt/session-fatigue pipeline schema.
-- PUUID is the sole identity key (see CONTEXT.md) -- never summoner name / Riot ID.

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    queue_id INT NOT NULL,
    game_creation TIMESTAMPTZ NOT NULL,
    game_duration_seconds INT NOT NULL,
    game_version TEXT NOT NULL
);

-- No FK to matches: referential integrity between participants and matches is
-- verified by the data-quality checks (ticket 04), not enforced at the DB
-- layer, so a partially-ingested state is inspectable rather than blocked.
CREATE TABLE IF NOT EXISTS participants (
    match_id TEXT NOT NULL,
    puuid TEXT NOT NULL,
    team_id INT NOT NULL,
    team_position TEXT,
    win BOOLEAN NOT NULL,
    kills INT NOT NULL,
    deaths INT NOT NULL,
    assists INT NOT NULL,
    gold_earned INT NOT NULL,
    damage_dealt_to_champions INT,
    PRIMARY KEY (match_id, puuid)
);
CREATE INDEX IF NOT EXISTS idx_participants_puuid ON participants(puuid);

CREATE TABLE IF NOT EXISTS ingestion_watermark (
    puuid TEXT PRIMARY KEY,
    last_match_id TEXT,
    last_match_game_creation TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id BIGSERIAL PRIMARY KEY,
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('manual', 'scheduled')),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')) DEFAULT 'running',
    error_message TEXT
);
