# LoL Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Postgres schema and the six-stage ingestion pipeline (seed players → match ID discovery → raw fetch → parse → load) that turns Riot API data into the normalized tables specified in the schema design docs.

**Architecture:** Raw match/timeline JSON is fetched from the Riot API and written to disk (`data/raw/`), tracked by a Postgres `ingestion_log` table. A separate transform step reads the raw files, runs them through pure parser functions, and upserts the results into normalized Postgres tables. Every stage is a small, independently-runnable CLI script under `scripts/`.

**Tech Stack:** Python 3.13, PostgreSQL 16 (local via Docker Compose), `psycopg[binary]` (psycopg 3, raw SQL — no ORM), `requests`, `python-dotenv`, `pytest`.

**Spec references:**
- [docs/superpowers/specs/2026-08-06-db-schema-design.md](../specs/2026-08-06-db-schema-design.md) — rationale
- [docs/superpowers/specs/2026-08-06-db-schema-implementation.md](../specs/2026-08-06-db-schema-implementation.md) — DDL + derivation rules

## Global Constraints

- Target DB: PostgreSQL 15+ (spec: "Target DB: PostgreSQL 15+")
- Only ingest queue ID `420` (ranked solo/duo) matches (spec: "Queue filter: only ingest queue ID `420`")
- Raw JSON files are kept permanently on disk, never deleted (spec: "Raw files are kept permanently (not deleted after parsing)")
- `team_position` is sourced from `participant.teamPosition`, never the deprecated `lane`/`role` fields (spec: "not the deprecated `lane`/`role` pair")
- `items` array must retain `0` values in their original slot position, never filtered out (spec: "Do not filter out `0` values — slot position is meaningful")
- `champions` dimension is refreshed from Data Dragon independently of match ingestion, never derived from match JSON (spec: "not re-fetched per match")
- No tests may depend on a live call to the real Riot API — all parser tests use committed JSON fixtures (spec: "No live-API end-to-end tests in CI")
- `ingestion_log.status` only takes the values `pending`, `fetched`, `parsed`, `error` (spec DDL `CHECK` constraint)

**Two corrections to the approved spec, made during planning (flagging per plan, not silently deviating):**
1. The spec's derivation rule said event `participant_id` comes from a `participantId` field, but Riot's real timeline events use different field names per event type (`killerId` for `CHAMPION_KILL`/`BUILDING_KILL`, `creatorId` for `WARD_PLACED`, etc.). Task 6 below implements a small fallback-lookup (`participantId` → `killerId` → `creatorId`, and `teamId` → `killerTeamId`) instead of assuming one fixed field name.
2. The spec's idempotency contract assumed a straightforward upsert works for every table, but `events` has only a surrogate `BIGSERIAL` primary key with no natural unique constraint, so a plain upsert would insert duplicate rows on every rerun. Task 11 below uses delete-then-insert for `events` specifically (all other tables use their natural composite keys for `ON CONFLICT` upserts, exactly as specified).

---

### Task 1: Local Postgres + connection helper + test tooling

**Files:**
- Create: `docker-compose.yml`
- Create: `pytest.ini`
- Create: `scripts/db.py`
- Test: `tests/test_db.py`
- Modify: `requirements.txt`
- Modify: `.env`, `.env.example`

**Interfaces:**
- Produces: `db.get_connection() -> psycopg.Connection` — every later task that touches Postgres calls this.

- [ ] **Step 1: Add `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: lol_analytics
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

- [ ] **Step 2: Start Postgres and confirm it's reachable**

Run: `docker compose up -d`
Expected: container starts; `docker compose ps` shows `db` as `running`/`healthy`.

- [ ] **Step 3: Add `DATABASE_URL` to env files**

Add this line to both `.env` and `.env.example`:

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/lol_analytics
```

- [ ] **Step 4: Add dependencies to `requirements.txt`**

```
requests
python-dotenv
psycopg[binary]
pytest
```

Run: `.venv/Scripts/pip install -r requirements.txt`

- [ ] **Step 5: Add `pytest.ini` so tests can import scripts as plain modules**

```ini
[pytest]
pythonpath = scripts
```

- [ ] **Step 6: Write the failing test**

`tests/test_db.py`:

```python
from db import get_connection


def test_get_connection_executes_select_1():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
    finally:
        conn.close()
```

- [ ] **Step 7: Run test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 8: Implement `scripts/db.py`**

```python
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])
```

- [ ] **Step 9: Run test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add docker-compose.yml pytest.ini scripts/db.py tests/test_db.py requirements.txt .env.example
git commit -m "Add local Postgres, connection helper, and test tooling"
```

---

### Task 2: Schema DDL + apply script

**Files:**
- Create: `schema.sql`
- Create: `scripts/init_db.py`
- Test: `tests/test_init_db.py`

**Interfaces:**
- Consumes: `db.get_connection()` (Task 1)
- Produces: `init_db.apply_schema() -> None` — Task 11's tests rely on the schema already being applied to the test database.

- [ ] **Step 1: Write `schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS patches (
    patch_version TEXT PRIMARY KEY,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS champions (
    champion_id INT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
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

CREATE TABLE IF NOT EXISTS teams (
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

CREATE TABLE IF NOT EXISTS team_bans (
    match_id TEXT NOT NULL,
    team_id INT NOT NULL,
    champion_id INT NOT NULL REFERENCES champions(champion_id),
    pick_turn INT NOT NULL,
    PRIMARY KEY (match_id, team_id, pick_turn),
    FOREIGN KEY (match_id, team_id) REFERENCES teams(match_id, team_id)
);

CREATE TABLE IF NOT EXISTS participants (
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
CREATE INDEX IF NOT EXISTS idx_participants_puuid ON participants(puuid);
CREATE INDEX IF NOT EXISTS idx_participants_champion ON participants(champion_id);

CREATE TABLE IF NOT EXISTS participant_frames (
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
CREATE INDEX IF NOT EXISTS idx_participant_frames_timestamp ON participant_frames(match_id, frame_timestamp_ms);

CREATE TABLE IF NOT EXISTS events (
    event_id BIGSERIAL PRIMARY KEY,
    match_id TEXT NOT NULL REFERENCES matches(match_id),
    timestamp_ms INT NOT NULL,
    event_type TEXT NOT NULL,
    participant_id INT,
    team_id INT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_events_match_type ON events(match_id, event_type);
CREATE INDEX IF NOT EXISTS idx_events_details ON events USING GIN (details);

CREATE TABLE IF NOT EXISTS ingestion_log (
    match_id TEXT PRIMARY KEY,
    fetched_match_at TIMESTAMPTZ,
    fetched_timeline_at TIMESTAMPTZ,
    parsed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'fetched', 'parsed', 'error')),
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS seed_players (
    puuid TEXT PRIMARY KEY,
    tier TEXT NOT NULL CHECK (tier IN ('CHALLENGER', 'GRANDMASTER', 'MASTER')),
    rank TEXT NOT NULL,
    league_points INT NOT NULL,
    wins INT NOT NULL,
    losses INT NOT NULL,
    pulled_at TIMESTAMPTZ NOT NULL
);
```

- [ ] **Step 2: Write the failing test**

`tests/test_init_db.py`:

```python
from db import get_connection
from init_db import apply_schema

EXPECTED_TABLES = {
    "patches", "champions", "matches", "teams", "team_bans",
    "participants", "participant_frames", "events",
    "ingestion_log", "seed_players",
}


def test_apply_schema_creates_all_tables():
    apply_schema()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            tables = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    assert EXPECTED_TABLES.issubset(tables)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_init_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'init_db'`

- [ ] **Step 4: Implement `scripts/init_db.py`**

```python
from pathlib import Path

from db import get_connection

SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


def apply_schema() -> None:
    sql = SCHEMA_PATH.read_text()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    apply_schema()
    print("Schema applied.")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_init_db.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add schema.sql scripts/init_db.py tests/test_init_db.py
git commit -m "Add schema DDL and apply script"
```

---

### Task 3: Riot API client helper (throttling + 429 retry)

**Files:**
- Create: `scripts/riot_client.py`
- Test: `tests/test_riot_client.py`

**Interfaces:**
- Produces: `riot_client.get_json(url: str, params: dict | None = None, api_key: str | None = None) -> dict` — used by every script that calls the Riot API (Tasks 8, 9, 10).

- [ ] **Step 1: Write the failing tests**

`tests/test_riot_client.py`:

```python
from unittest.mock import MagicMock, patch

import riot_client


def test_get_json_returns_parsed_response(monkeypatch):
    monkeypatch.setattr(riot_client, "_last_call", 0.0)
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"hello": "world"}
    with patch("riot_client.requests.get", return_value=mock_resp) as mock_get, \
         patch("riot_client.time.sleep"):
        result = riot_client.get_json("https://example.com", api_key="key123")
    assert result == {"hello": "world"}
    mock_get.assert_called_once_with(
        "https://example.com", headers={"X-Riot-Token": "key123"}, params=None
    )


def test_get_json_retries_after_429(monkeypatch):
    monkeypatch.setattr(riot_client, "_last_call", 0.0)
    rate_limited = MagicMock(status_code=429, headers={"Retry-After": "0"})
    success = MagicMock(status_code=200)
    success.json.return_value = {"ok": True}
    with patch("riot_client.requests.get", side_effect=[rate_limited, success]), \
         patch("riot_client.time.sleep"):
        result = riot_client.get_json("https://example.com", api_key="key123")
    assert result == {"ok": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_riot_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'riot_client'`

- [ ] **Step 3: Implement `scripts/riot_client.py`**

```python
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

# Dev key limits: 20 req/sec, 100 req/2min. Sleeping this long between calls
# keeps us comfortably under the 2-minute bucket (~85 req/2min).
MIN_INTERVAL_SECONDS = 1.3

_last_call = 0.0


def get_json(url: str, params: dict | None = None, api_key: str | None = None) -> dict:
    global _last_call
    api_key = api_key or os.environ["RIOT_API_KEY"]

    elapsed = time.monotonic() - _last_call
    if elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)

    resp = requests.get(url, headers={"X-Riot-Token": api_key}, params=params)
    _last_call = time.monotonic()

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "5"))
        time.sleep(retry_after)
        return get_json(url, params, api_key)

    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_riot_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/riot_client.py tests/test_riot_client.py
git commit -m "Add throttled Riot API client with 429 retry"
```

---

### Task 4: Parsers — match, teams, bans

**Files:**
- Create: `scripts/parsers.py`
- Create: `tests/fixtures/sample_match.json`
- Test: `tests/test_parsers.py`

**Interfaces:**
- Produces: `parsers.parse_patch_version(game_version: str) -> str`, `parsers.parse_match(raw_match: dict) -> dict`, `parsers.parse_teams(raw_match: dict) -> list[dict]`, `parsers.parse_bans(raw_match: dict) -> list[dict]` — Task 11 calls all of these.

- [ ] **Step 1: Write the match fixture**

`tests/fixtures/sample_match.json`:

```json
{
  "metadata": {
    "matchId": "NA1_9999999999"
  },
  "info": {
    "gameCreation": 1700000000000,
    "gameStartTimestamp": 1700000010000,
    "gameDuration": 1800,
    "gameVersion": "14.15.567.1234",
    "platformId": "NA1",
    "queueId": 420,
    "teams": [
      {
        "teamId": 100,
        "win": true,
        "objectives": {
          "champion": {"first": true},
          "tower": {"first": true, "kills": 8},
          "baron": {"kills": 1},
          "dragon": {"kills": 2},
          "riftHerald": {"kills": 1},
          "inhibitor": {"kills": 2}
        },
        "bans": [
          {"championId": 266, "pickTurn": 1},
          {"championId": -1, "pickTurn": 2}
        ]
      },
      {
        "teamId": 200,
        "win": false,
        "objectives": {
          "champion": {"first": false},
          "tower": {"first": false, "kills": 3},
          "baron": {"kills": 0},
          "dragon": {"kills": 1},
          "riftHerald": {"kills": 0},
          "inhibitor": {"kills": 0}
        },
        "bans": [
          {"championId": 64, "pickTurn": 1}
        ]
      }
    ],
    "participants": [
      {
        "participantId": 1,
        "puuid": "puuid-player-one",
        "teamId": 100,
        "championId": 266,
        "teamPosition": "TOP",
        "kills": 5,
        "deaths": 1,
        "assists": 3,
        "goldEarned": 12500,
        "totalDamageDealtToChampions": 21000,
        "totalDamageTaken": 15000,
        "totalMinionsKilled": 180,
        "neutralMinionsKilled": 10,
        "visionScore": 22,
        "item0": 3153, "item1": 3071, "item2": 3072,
        "item3": 0, "item4": 0, "item5": 0, "item6": 3364,
        "summoner1Id": 4, "summoner2Id": 12
      },
      {
        "participantId": 2,
        "puuid": "puuid-player-two",
        "teamId": 200,
        "championId": 64,
        "teamPosition": "JUNGLE",
        "kills": 2,
        "deaths": 4,
        "assists": 6,
        "goldEarned": 9800,
        "totalDamageDealtToChampions": 14000,
        "totalDamageTaken": 18000,
        "totalMinionsKilled": 20,
        "neutralMinionsKilled": 120,
        "visionScore": 30,
        "item0": 1400, "item1": 0, "item2": 0,
        "item3": 0, "item4": 0, "item5": 0, "item6": 3340,
        "summoner1Id": 11, "summoner2Id": 4
      }
    ]
  }
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parsers.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from parsers import parse_patch_version, parse_match, parse_teams, parse_bans

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sample_match.json").read_text())


def test_parse_patch_version_truncates_to_major_minor():
    assert parse_patch_version("14.15.567.1234") == "14.15"


def test_parse_match_extracts_core_fields():
    result = parse_match(FIXTURE)
    assert result["match_id"] == "NA1_9999999999"
    assert result["platform"] == "NA1"
    assert result["patch_version"] == "14.15"
    assert result["winning_team_id"] == 100
    assert result["game_creation"] == datetime.fromtimestamp(1700000000000 / 1000, tz=timezone.utc)


def test_parse_teams_extracts_objectives_and_first_blood():
    rows = parse_teams(FIXTURE)
    assert len(rows) == 2
    team_100 = next(r for r in rows if r["team_id"] == 100)
    assert team_100["win"] is True
    assert team_100["first_blood"] is True
    assert team_100["baron_kills"] == 1
    assert team_100["herald_kills"] == 1


def test_parse_bans_skips_missing_ban_slots():
    rows = parse_bans(FIXTURE)
    assert len(rows) == 2
    assert {"match_id": "NA1_9999999999", "team_id": 100, "champion_id": 266, "pick_turn": 1} in rows
    assert all(r["champion_id"] != -1 for r in rows)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'parsers'`

- [ ] **Step 4: Implement `scripts/parsers.py` (part 1)**

```python
from datetime import datetime, timezone


def parse_patch_version(game_version: str) -> str:
    parts = game_version.split(".")
    return ".".join(parts[:2])


def parse_match(raw_match: dict) -> dict:
    info = raw_match["info"]
    return {
        "match_id": raw_match["metadata"]["matchId"],
        "platform": info["platformId"],
        "game_creation": datetime.fromtimestamp(info["gameCreation"] / 1000, tz=timezone.utc),
        "game_start": datetime.fromtimestamp(info["gameStartTimestamp"] / 1000, tz=timezone.utc),
        "game_duration_seconds": info["gameDuration"],
        "game_version": info["gameVersion"],
        "patch_version": parse_patch_version(info["gameVersion"]),
        "queue_id": info["queueId"],
        "winning_team_id": next(t["teamId"] for t in info["teams"] if t["win"]),
    }


def parse_teams(raw_match: dict) -> list[dict]:
    match_id = raw_match["metadata"]["matchId"]
    rows = []
    for team in raw_match["info"]["teams"]:
        objectives = team["objectives"]
        rows.append({
            "match_id": match_id,
            "team_id": team["teamId"],
            "win": team["win"],
            "first_blood": objectives["champion"]["first"],
            "first_tower": objectives["tower"]["first"],
            "baron_kills": objectives["baron"]["kills"],
            "dragon_kills": objectives["dragon"]["kills"],
            "herald_kills": objectives["riftHerald"]["kills"],
            "tower_kills": objectives["tower"]["kills"],
            "inhibitor_kills": objectives["inhibitor"]["kills"],
        })
    return rows


def parse_bans(raw_match: dict) -> list[dict]:
    match_id = raw_match["metadata"]["matchId"]
    rows = []
    for team in raw_match["info"]["teams"]:
        for ban in team["bans"]:
            if ban["championId"] == -1:
                continue
            rows.append({
                "match_id": match_id,
                "team_id": team["teamId"],
                "champion_id": ban["championId"],
                "pick_turn": ban["pickTurn"],
            })
    return rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/parsers.py tests/fixtures/sample_match.json tests/test_parsers.py
git commit -m "Add match/teams/bans parsers"
```

---

### Task 5: Parsers — participants

**Files:**
- Modify: `scripts/parsers.py`
- Modify: `tests/test_parsers.py`

**Interfaces:**
- Consumes: `tests/fixtures/sample_match.json` (Task 4)
- Produces: `parsers.parse_participants(raw_match: dict) -> list[dict]` — Task 11 calls this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parsers.py`:

```python
from parsers import parse_participants


def test_parse_participants_extracts_all_players():
    rows = parse_participants(FIXTURE)
    assert len(rows) == 2
    p1 = next(r for r in rows if r["participant_id"] == 1)
    assert p1["puuid"] == "puuid-player-one"
    assert p1["total_cs"] == 190
    assert p1["items"] == [3153, 3071, 3072, 0, 0, 0, 3364]


def test_parse_participants_uses_team_position_not_lane():
    rows = parse_participants(FIXTURE)
    positions = {r["participant_id"]: r["team_position"] for r in rows}
    assert positions == {1: "TOP", 2: "JUNGLE"}
```

(Update the `from parsers import ...` line at the top of the file to include `parse_participants` instead of adding a second import line, if you prefer a single import — either works.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_participants'`

- [ ] **Step 3: Implement `parse_participants` in `scripts/parsers.py`**

Append:

```python
def parse_participants(raw_match: dict) -> list[dict]:
    match_id = raw_match["metadata"]["matchId"]
    rows = []
    for p in raw_match["info"]["participants"]:
        rows.append({
            "match_id": match_id,
            "participant_id": p["participantId"],
            "puuid": p["puuid"],
            "team_id": p["teamId"],
            "champion_id": p["championId"],
            "team_position": p["teamPosition"],
            "kills": p["kills"],
            "deaths": p["deaths"],
            "assists": p["assists"],
            "gold_earned": p["goldEarned"],
            "damage_dealt_to_champions": p["totalDamageDealtToChampions"],
            "damage_taken": p["totalDamageTaken"],
            "total_cs": p["totalMinionsKilled"] + p["neutralMinionsKilled"],
            "vision_score": p["visionScore"],
            "items": [p[f"item{i}"] for i in range(7)],
            "summoner_spell_1": p["summoner1Id"],
            "summoner_spell_2": p["summoner2Id"],
        })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/parsers.py tests/test_parsers.py
git commit -m "Add participants parser"
```

---

### Task 6: Parsers — timeline frames and events (with actor/team fallback lookup)

**Files:**
- Modify: `scripts/parsers.py`
- Create: `tests/fixtures/sample_timeline.json`
- Modify: `tests/test_parsers.py`

**Interfaces:**
- Produces: `parsers.parse_participant_frames(raw_timeline: dict, match_id: str) -> list[dict]`, `parsers.parse_events(raw_timeline: dict, match_id: str) -> list[dict]` — Task 11 calls both.

- [ ] **Step 1: Write the timeline fixture**

`tests/fixtures/sample_timeline.json`:

```json
{
  "info": {
    "frames": [
      {
        "timestamp": 60000,
        "participantFrames": {
          "1": {"totalGold": 500, "xp": 200, "level": 2, "minionsKilled": 4, "jungleMinionsKilled": 0, "position": {"x": 1200, "y": 3400}},
          "2": {"totalGold": 480, "xp": 190, "level": 2, "minionsKilled": 0, "jungleMinionsKilled": 5, "position": {"x": 8500, "y": 7600}}
        },
        "events": [
          {"timestamp": 45000, "type": "CHAMPION_KILL", "killerId": 1, "victimId": 2, "assistingParticipantIds": [], "position": {"x": 1500, "y": 3200}}
        ]
      },
      {
        "timestamp": 120000,
        "participantFrames": {
          "1": {"totalGold": 1100, "xp": 700, "level": 3, "minionsKilled": 10, "jungleMinionsKilled": 0, "position": {"x": 1300, "y": 3500}},
          "2": {"totalGold": 950, "xp": 650, "level": 3, "minionsKilled": 2, "jungleMinionsKilled": 9, "position": {"x": 8600, "y": 7700}}
        },
        "events": [
          {"timestamp": 95000, "type": "BUILDING_KILL", "teamId": 200, "killerId": 1, "buildingType": "TOWER_BUILDING", "laneType": "MID_LANE", "towerType": "OUTER_TURRET"},
          {"timestamp": 110000, "type": "WARD_PLACED", "creatorId": 2, "wardType": "YELLOW_TRINKET"}
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_parsers.py`:

```python
from parsers import parse_participant_frames, parse_events

TIMELINE_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sample_timeline.json").read_text())
MATCH_ID = "NA1_9999999999"


def test_parse_participant_frames_casts_string_keys_to_int():
    rows = parse_participant_frames(TIMELINE_FIXTURE, MATCH_ID)
    assert len(rows) == 4
    frame_60s = [r for r in rows if r["frame_timestamp_ms"] == 60000]
    p1_frame = next(r for r in frame_60s if r["participant_id"] == 1)
    assert isinstance(p1_frame["participant_id"], int)
    assert p1_frame["total_gold"] == 500
    assert p1_frame["position_x"] == 1200


def test_parse_events_extracts_champion_kill_killer_as_participant_id():
    rows = parse_events(TIMELINE_FIXTURE, MATCH_ID)
    kill = next(r for r in rows if r["event_type"] == "CHAMPION_KILL")
    assert kill["participant_id"] == 1
    assert kill["team_id"] is None
    assert kill["details"]["victimId"] == 2
    assert "killerId" not in kill["details"]


def test_parse_events_extracts_building_kill_team_and_killer():
    rows = parse_events(TIMELINE_FIXTURE, MATCH_ID)
    building = next(r for r in rows if r["event_type"] == "BUILDING_KILL")
    assert building["participant_id"] == 1
    assert building["team_id"] == 200
    assert building["details"]["buildingType"] == "TOWER_BUILDING"


def test_parse_events_extracts_ward_placed_creator_as_participant_id():
    rows = parse_events(TIMELINE_FIXTURE, MATCH_ID)
    ward = next(r for r in rows if r["event_type"] == "WARD_PLACED")
    assert ward["participant_id"] == 2
    assert ward["details"]["wardType"] == "YELLOW_TRINKET"
    assert "creatorId" not in ward["details"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_participant_frames'`

- [ ] **Step 4: Implement in `scripts/parsers.py`**

Append:

```python
PARTICIPANT_ID_KEYS = ("participantId", "killerId", "creatorId")
TEAM_ID_KEYS = ("teamId", "killerTeamId")
_PROMOTED_EVENT_KEYS = ("type", "timestamp") + PARTICIPANT_ID_KEYS + TEAM_ID_KEYS


def _extract_first_present(event: dict, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key in event:
            return event[key]
    return None


def parse_participant_frames(raw_timeline: dict, match_id: str) -> list[dict]:
    rows = []
    for frame in raw_timeline["info"]["frames"]:
        frame_timestamp_ms = frame["timestamp"]
        for participant_id_str, pframe in frame["participantFrames"].items():
            position = pframe.get("position", {})
            rows.append({
                "match_id": match_id,
                "participant_id": int(participant_id_str),
                "frame_timestamp_ms": frame_timestamp_ms,
                "total_gold": pframe["totalGold"],
                "xp": pframe["xp"],
                "level": pframe["level"],
                "minions_killed": pframe["minionsKilled"],
                "jungle_minions_killed": pframe["jungleMinionsKilled"],
                "position_x": position.get("x"),
                "position_y": position.get("y"),
            })
    return rows


def parse_events(raw_timeline: dict, match_id: str) -> list[dict]:
    rows = []
    for frame in raw_timeline["info"]["frames"]:
        for event in frame["events"]:
            participant_id = _extract_first_present(event, PARTICIPANT_ID_KEYS)
            team_id = _extract_first_present(event, TEAM_ID_KEYS)
            details = {k: v for k, v in event.items() if k not in _PROMOTED_EVENT_KEYS}
            rows.append({
                "match_id": match_id,
                "timestamp_ms": event["timestamp"],
                "event_type": event["type"],
                "participant_id": participant_id,
                "team_id": team_id,
                "details": details,
            })
    return rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/parsers.py tests/fixtures/sample_timeline.json tests/test_parsers.py
git commit -m "Add timeline frame/event parsers with actor-field fallback lookup"
```

---

### Task 7: Champions dimension loader

**Files:**
- Modify: `scripts/parsers.py`
- Create: `tests/fixtures/sample_champions.json`
- Modify: `tests/test_parsers.py`
- Create: `scripts/load_champions.py`

**Interfaces:**
- Consumes: `db.get_connection()` (Task 1), `riot_client.get_json()` (Task 3)
- Produces: populated `champions` table — required before Task 11's tests can insert `participants`/`team_bans` rows (their `champion_id` has an FK to `champions`).

- [ ] **Step 1: Write the champions fixture**

`tests/fixtures/sample_champions.json`:

```json
{
  "data": {
    "Aatrox": {"key": "266", "name": "Aatrox"},
    "Ahri": {"key": "103", "name": "Ahri"}
  }
}
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_parsers.py`:

```python
from parsers import parse_champions


def test_parse_champions_extracts_id_and_name():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "sample_champions.json").read_text())
    rows = parse_champions(fixture)
    assert {"champion_id": 266, "name": "Aatrox"} in rows
    assert len(rows) == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_champions'`

- [ ] **Step 4: Implement `parse_champions` in `scripts/parsers.py`**

Append:

```python
def parse_champions(raw_champion_data: dict) -> list[dict]:
    return [
        {"champion_id": int(champ["key"]), "name": champ["name"]}
        for champ in raw_champion_data["data"].values()
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: PASS

- [ ] **Step 6: Implement `scripts/load_champions.py`**

```python
from db import get_connection
from parsers import parse_champions
from riot_client import get_json

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"


def latest_patch() -> str:
    versions = get_json(DDRAGON_VERSIONS_URL)
    return versions[0]


def fetch_champions(patch: str) -> dict:
    url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/champion.json"
    return get_json(url)


def upsert_champions(rows: list[dict]) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO champions (champion_id, name)
                    VALUES (%(champion_id)s, %(name)s)
                    ON CONFLICT (champion_id) DO UPDATE SET name = EXCLUDED.name
                    """,
                    row,
                )
        conn.commit()
    finally:
        conn.close()


def main():
    patch = latest_patch()
    raw = fetch_champions(patch)
    rows = parse_champions(raw)
    upsert_champions(rows)
    print(f"Upserted {len(rows)} champions (patch {patch})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the loader against your local Postgres**

Run: `.venv/Scripts/python scripts/init_db.py` (if not already applied), then `.venv/Scripts/python scripts/load_champions.py`
Expected: prints `Upserted <N> champions (patch <version>)` with N in the 160s+ range.

- [ ] **Step 8: Commit**

```bash
git add scripts/parsers.py scripts/load_champions.py tests/fixtures/sample_champions.json tests/test_parsers.py
git commit -m "Add champions dimension loader"
```

---

### Task 8: Seed players loader

**Files:**
- Modify: `scripts/parsers.py`
- Modify: `tests/test_parsers.py`
- Create: `scripts/seed_players.py`

**Interfaces:**
- Consumes: `db.get_connection()`, `riot_client.get_json()`
- Produces: populated `seed_players` table — Task 9 queries this table for PUUIDs.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_parsers.py`:

```python
from parsers import parse_seed_entry


def test_parse_seed_entry_attaches_tier_and_pulled_at():
    entry = {"puuid": "abc", "rank": "I", "leaguePoints": 500, "wins": 10, "losses": 5}
    pulled_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    result = parse_seed_entry(entry, "CHALLENGER", pulled_at)
    assert result == {
        "puuid": "abc", "tier": "CHALLENGER", "rank": "I",
        "league_points": 500, "wins": 10, "losses": 5, "pulled_at": pulled_at,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_seed_entry'`

- [ ] **Step 3: Implement `parse_seed_entry` in `scripts/parsers.py`**

Append:

```python
def parse_seed_entry(entry: dict, tier: str, pulled_at: datetime) -> dict:
    return {
        "puuid": entry["puuid"],
        "tier": tier,
        "rank": entry["rank"],
        "league_points": entry["leaguePoints"],
        "wins": entry["wins"],
        "losses": entry["losses"],
        "pulled_at": pulled_at,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_parsers.py -v`
Expected: PASS

- [ ] **Step 5: Implement `scripts/seed_players.py`**

```python
from datetime import datetime, timezone

from db import get_connection
from parsers import parse_seed_entry
from riot_client import get_json

PLATFORM = "na1"
QUEUE = "RANKED_SOLO_5x5"

APEX_TIERS = {
    "CHALLENGER": f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/challengerleagues/by-queue/{QUEUE}",
    "GRANDMASTER": f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/grandmasterleagues/by-queue/{QUEUE}",
    "MASTER": f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/masterleagues/by-queue/{QUEUE}",
}


def fetch_seed_rows() -> list[dict]:
    pulled_at = datetime.now(timezone.utc)
    rows = []
    for tier, url in APEX_TIERS.items():
        data = get_json(url)
        for entry in data["entries"]:
            rows.append(parse_seed_entry(entry, tier, pulled_at))
        print(f"{tier}: {len(data['entries'])} players")
    return rows


def upsert_seed_players(rows: list[dict]) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO seed_players (puuid, tier, rank, league_points, wins, losses, pulled_at)
                    VALUES (%(puuid)s, %(tier)s, %(rank)s, %(league_points)s, %(wins)s, %(losses)s, %(pulled_at)s)
                    ON CONFLICT (puuid) DO UPDATE SET
                        tier = EXCLUDED.tier, rank = EXCLUDED.rank,
                        league_points = EXCLUDED.league_points,
                        wins = EXCLUDED.wins, losses = EXCLUDED.losses,
                        pulled_at = EXCLUDED.pulled_at
                    """,
                    row,
                )
        conn.commit()
    finally:
        conn.close()


def main():
    rows = fetch_seed_rows()
    upsert_seed_players(rows)
    print(f"Upserted {len(rows)} seed players")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the loader against your local Postgres**

Run: `.venv/Scripts/python scripts/seed_players.py`
Expected: prints per-tier counts and a final `Upserted <N> seed players` line (N in the 1000+ range, matching your earlier `data/seed_puuids.json` pull).

- [ ] **Step 7: Commit**

```bash
git add scripts/parsers.py scripts/seed_players.py tests/test_parsers.py
git commit -m "Add seed players loader"
```

---

### Task 9: Match ID discovery

**Files:**
- Create: `scripts/discover_match_ids.py`
- Test: `tests/test_discover_match_ids.py`

**Interfaces:**
- Consumes: `db.get_connection()`, `riot_client.get_json()`, populated `seed_players` table (Task 8)
- Produces: `ingestion_log` rows with `status = 'pending'` — Task 10 queries this.

- [ ] **Step 1: Write the failing test**

`tests/test_discover_match_ids.py`:

```python
from db import get_connection
from discover_match_ids import insert_pending_match_ids


def _cleanup(match_ids):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.executemany("DELETE FROM ingestion_log WHERE match_id = %s", [(m,) for m in match_ids])
    conn.commit()
    conn.close()


def test_insert_pending_match_ids_is_idempotent():
    match_ids = ["TEST_MATCH_1", "TEST_MATCH_2"]
    try:
        insert_pending_match_ids(match_ids)
        insert_pending_match_ids(match_ids)
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT match_id, status FROM ingestion_log WHERE match_id = ANY(%s)",
                (match_ids,),
            )
            rows = cur.fetchall()
        conn.close()
        assert len(rows) == 2
        assert all(status == "pending" for _, status in rows)
    finally:
        _cleanup(match_ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_discover_match_ids.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'discover_match_ids'`

- [ ] **Step 3: Implement `scripts/discover_match_ids.py`**

```python
from db import get_connection
from riot_client import get_json

REGION = "americas"


def get_seed_puuids() -> list[str]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT puuid FROM seed_players")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def fetch_match_ids_for_puuid(puuid: str, count: int = 20) -> list[str]:
    url = f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {"queue": 420, "type": "ranked", "start": 0, "count": count}
    return get_json(url, params)


def insert_pending_match_ids(match_ids: list[str]) -> None:
    if not match_ids:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ingestion_log (match_id) VALUES (%s) ON CONFLICT (match_id) DO NOTHING",
                [(mid,) for mid in match_ids],
            )
        conn.commit()
    finally:
        conn.close()


def main():
    puuids = get_seed_puuids()
    print(f"Discovering match IDs for {len(puuids)} seed players...")
    for i, puuid in enumerate(puuids, 1):
        match_ids = fetch_match_ids_for_puuid(puuid)
        insert_pending_match_ids(match_ids)
        if i % 25 == 0:
            print(f"  {i}/{len(puuids)} players processed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_discover_match_ids.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/discover_match_ids.py tests/test_discover_match_ids.py
git commit -m "Add match ID discovery"
```

---

### Task 10: Raw fetch step

**Files:**
- Create: `scripts/fetch_raw.py`
- Test: `tests/test_fetch_raw.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `db.get_connection()`, `riot_client.get_json()`, `ingestion_log` rows with `status = 'pending'` (Task 9)
- Produces: files in `data/raw/matches/` and `data/raw/timelines/`, `ingestion_log` rows updated to `status = 'fetched'` (or `'error'`) — Task 11 reads both.

- [ ] **Step 1: Add `data/raw/` to `.gitignore`**

Append this line to `.gitignore`:

```
data/raw/
```

(The existing `data/*.json` rule only matches files directly inside `data/`, not the nested `data/raw/matches/*.json` / `data/raw/timelines/*.json` paths this task introduces — this explicit rule is needed.)

- [ ] **Step 2: Write the failing tests**

`tests/test_fetch_raw.py`:

```python
import json
from unittest.mock import patch

import fetch_raw
from db import get_connection
from fetch_raw import mark_error, mark_fetched


def test_fetch_and_save_raw_writes_match_and_timeline_files(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_raw, "RAW_MATCHES_DIR", tmp_path / "matches")
    monkeypatch.setattr(fetch_raw, "RAW_TIMELINES_DIR", tmp_path / "timelines")

    responses = [{"metadata": {"matchId": "NA1_1"}}, {"info": {"frames": []}}]
    with patch("fetch_raw.get_json", side_effect=responses):
        fetch_raw.fetch_and_save_raw("NA1_1")

    match_file = tmp_path / "matches" / "NA1_1.json"
    timeline_file = tmp_path / "timelines" / "NA1_1.json"
    assert match_file.exists()
    assert timeline_file.exists()
    assert json.loads(match_file.read_text())["metadata"]["matchId"] == "NA1_1"


def test_mark_fetched_and_mark_error_update_status():
    match_id = "TEST_FETCH_STATUS"
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_log (match_id) VALUES (%s) ON CONFLICT (match_id) DO NOTHING",
                (match_id,),
            )
        conn.commit()

        mark_fetched(match_id)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, fetched_match_at FROM ingestion_log WHERE match_id = %s", (match_id,)
            )
            status, fetched_at = cur.fetchone()
        assert status == "fetched"
        assert fetched_at is not None

        mark_error(match_id, "boom")
        with conn.cursor() as cur:
            cur.execute("SELECT status, error_message FROM ingestion_log WHERE match_id = %s", (match_id,))
            status, error_message = cur.fetchone()
        assert status == "error"
        assert error_message == "boom"
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ingestion_log WHERE match_id = %s", (match_id,))
        conn.commit()
        conn.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_fetch_raw.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fetch_raw'`

- [ ] **Step 4: Implement `scripts/fetch_raw.py`**

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from db import get_connection
from riot_client import get_json

REGION = "americas"
RAW_MATCHES_DIR = Path(__file__).parent.parent / "data" / "raw" / "matches"
RAW_TIMELINES_DIR = Path(__file__).parent.parent / "data" / "raw" / "timelines"


def get_pending_match_ids() -> list[str]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT match_id FROM ingestion_log WHERE status = 'pending'")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def fetch_and_save_raw(match_id: str) -> None:
    RAW_MATCHES_DIR.mkdir(parents=True, exist_ok=True)
    RAW_TIMELINES_DIR.mkdir(parents=True, exist_ok=True)

    match_url = f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    timeline_url = f"{match_url}/timeline"

    match_data = get_json(match_url)
    (RAW_MATCHES_DIR / f"{match_id}.json").write_text(json.dumps(match_data))

    timeline_data = get_json(timeline_url)
    (RAW_TIMELINES_DIR / f"{match_id}.json").write_text(json.dumps(timeline_data))


def mark_fetched(match_id: str) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_log
                SET fetched_match_at = %(now)s, fetched_timeline_at = %(now)s, status = 'fetched'
                WHERE match_id = %(match_id)s
                """,
                {"now": datetime.now(timezone.utc), "match_id": match_id},
            )
        conn.commit()
    finally:
        conn.close()


def mark_error(match_id: str, error_message: str) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_log SET status = 'error', error_message = %s WHERE match_id = %s",
                (error_message, match_id),
            )
        conn.commit()
    finally:
        conn.close()


def main():
    match_ids = get_pending_match_ids()
    print(f"Fetching raw data for {len(match_ids)} pending matches...")
    for i, match_id in enumerate(match_ids, 1):
        try:
            fetch_and_save_raw(match_id)
            mark_fetched(match_id)
        except Exception as exc:
            mark_error(match_id, str(exc))
        if i % 25 == 0:
            print(f"  {i}/{len(match_ids)} processed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_fetch_raw.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/fetch_raw.py tests/test_fetch_raw.py .gitignore
git commit -m "Add raw match/timeline fetch step"
```

---

### Task 11: DB loader (transform + upsert) and README pipeline docs

**Files:**
- Create: `scripts/load_match.py`
- Test: `tests/test_load_match.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `parsers.parse_match/parse_teams/parse_bans/parse_participants/parse_participant_frames/parse_events` (Tasks 4–6), raw files written by Task 10, `db.get_connection()`
- Produces: populated `matches`/`teams`/`team_bans`/`participants`/`participant_frames`/`events` tables, `ingestion_log` rows updated to `status = 'parsed'`

- [ ] **Step 1: Write the failing test**

`tests/test_load_match.py`:

```python
import json
from pathlib import Path

from db import get_connection

FIXTURES = Path(__file__).parent / "fixtures"
MATCH_ID = "NA1_9999999999"


def test_load_match_populates_all_tables(tmp_path, monkeypatch):
    import load_match

    raw_match = json.loads((FIXTURES / "sample_match.json").read_text())
    raw_timeline = json.loads((FIXTURES / "sample_timeline.json").read_text())

    matches_dir = tmp_path / "matches"
    timelines_dir = tmp_path / "timelines"
    matches_dir.mkdir()
    timelines_dir.mkdir()
    (matches_dir / f"{MATCH_ID}.json").write_text(json.dumps(raw_match))
    (timelines_dir / f"{MATCH_ID}.json").write_text(json.dumps(raw_timeline))

    monkeypatch.setattr(load_match, "RAW_MATCHES_DIR", matches_dir)
    monkeypatch.setattr(load_match, "RAW_TIMELINES_DIR", timelines_dir)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO champions (champion_id, name) VALUES (266, 'Aatrox') ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO champions (champion_id, name) VALUES (64, 'Lee Sin') ON CONFLICT DO NOTHING")
            cur.execute(
                """
                INSERT INTO ingestion_log (match_id, status) VALUES (%s, 'fetched')
                ON CONFLICT (match_id) DO UPDATE SET status = 'fetched'
                """,
                (MATCH_ID,),
            )
        conn.commit()

        load_match.load_match(MATCH_ID)
        load_match.load_match(MATCH_ID)  # second call: must not error or duplicate rows

        with conn.cursor() as cur:
            cur.execute("SELECT status FROM ingestion_log WHERE match_id = %s", (MATCH_ID,))
            assert cur.fetchone()[0] == "parsed"

            cur.execute("SELECT count(*) FROM participants WHERE match_id = %s", (MATCH_ID,))
            assert cur.fetchone()[0] == 2

            cur.execute("SELECT count(*) FROM participant_frames WHERE match_id = %s", (MATCH_ID,))
            assert cur.fetchone()[0] == 4

            cur.execute("SELECT count(*) FROM events WHERE match_id = %s", (MATCH_ID,))
            assert cur.fetchone()[0] == 3
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM events WHERE match_id = %s", (MATCH_ID,))
            cur.execute("DELETE FROM participant_frames WHERE match_id = %s", (MATCH_ID,))
            cur.execute("DELETE FROM team_bans WHERE match_id = %s", (MATCH_ID,))
            cur.execute("DELETE FROM participants WHERE match_id = %s", (MATCH_ID,))
            cur.execute("DELETE FROM teams WHERE match_id = %s", (MATCH_ID,))
            cur.execute("DELETE FROM ingestion_log WHERE match_id = %s", (MATCH_ID,))
            cur.execute("DELETE FROM matches WHERE match_id = %s", (MATCH_ID,))
        conn.commit()
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_load_match.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'load_match'`

- [ ] **Step 3: Implement `scripts/load_match.py`**

```python
import json
from pathlib import Path

from db import get_connection
from parsers import (
    parse_bans,
    parse_events,
    parse_match,
    parse_participant_frames,
    parse_participants,
    parse_teams,
)

RAW_MATCHES_DIR = Path(__file__).parent.parent / "data" / "raw" / "matches"
RAW_TIMELINES_DIR = Path(__file__).parent.parent / "data" / "raw" / "timelines"


def get_fetched_match_ids() -> list[str]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT match_id FROM ingestion_log WHERE status = 'fetched'")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def load_match(match_id: str) -> None:
    raw_match = json.loads((RAW_MATCHES_DIR / f"{match_id}.json").read_text())
    raw_timeline = json.loads((RAW_TIMELINES_DIR / f"{match_id}.json").read_text())

    match_row = parse_match(raw_match)
    team_rows = parse_teams(raw_match)
    ban_rows = parse_bans(raw_match)
    participant_rows = parse_participants(raw_match)
    frame_rows = parse_participant_frames(raw_timeline, match_id)
    event_rows = parse_events(raw_timeline, match_id)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO patches (patch_version) VALUES (%s) ON CONFLICT DO NOTHING",
                (match_row["patch_version"],),
            )
            cur.execute(
                """
                INSERT INTO matches (match_id, platform, game_creation, game_start,
                    game_duration_seconds, game_version, patch_version, queue_id, winning_team_id)
                VALUES (%(match_id)s, %(platform)s, %(game_creation)s, %(game_start)s,
                    %(game_duration_seconds)s, %(game_version)s, %(patch_version)s, %(queue_id)s, %(winning_team_id)s)
                ON CONFLICT (match_id) DO UPDATE SET
                    game_duration_seconds = EXCLUDED.game_duration_seconds,
                    winning_team_id = EXCLUDED.winning_team_id
                """,
                match_row,
            )
            for row in team_rows:
                cur.execute(
                    """
                    INSERT INTO teams (match_id, team_id, win, first_blood, first_tower,
                        baron_kills, dragon_kills, herald_kills, tower_kills, inhibitor_kills)
                    VALUES (%(match_id)s, %(team_id)s, %(win)s, %(first_blood)s, %(first_tower)s,
                        %(baron_kills)s, %(dragon_kills)s, %(herald_kills)s, %(tower_kills)s, %(inhibitor_kills)s)
                    ON CONFLICT (match_id, team_id) DO UPDATE SET
                        win = EXCLUDED.win, baron_kills = EXCLUDED.baron_kills,
                        dragon_kills = EXCLUDED.dragon_kills, herald_kills = EXCLUDED.herald_kills,
                        tower_kills = EXCLUDED.tower_kills, inhibitor_kills = EXCLUDED.inhibitor_kills
                    """,
                    row,
                )
            for row in ban_rows:
                cur.execute(
                    """
                    INSERT INTO team_bans (match_id, team_id, champion_id, pick_turn)
                    VALUES (%(match_id)s, %(team_id)s, %(champion_id)s, %(pick_turn)s)
                    ON CONFLICT (match_id, team_id, pick_turn) DO UPDATE SET champion_id = EXCLUDED.champion_id
                    """,
                    row,
                )
            for row in participant_rows:
                cur.execute(
                    """
                    INSERT INTO participants (match_id, participant_id, puuid, team_id, champion_id,
                        team_position, kills, deaths, assists, gold_earned, damage_dealt_to_champions,
                        damage_taken, total_cs, vision_score, items, summoner_spell_1, summoner_spell_2)
                    VALUES (%(match_id)s, %(participant_id)s, %(puuid)s, %(team_id)s, %(champion_id)s,
                        %(team_position)s, %(kills)s, %(deaths)s, %(assists)s, %(gold_earned)s,
                        %(damage_dealt_to_champions)s, %(damage_taken)s, %(total_cs)s, %(vision_score)s,
                        %(items)s, %(summoner_spell_1)s, %(summoner_spell_2)s)
                    ON CONFLICT (match_id, participant_id) DO UPDATE SET
                        kills = EXCLUDED.kills, deaths = EXCLUDED.deaths, assists = EXCLUDED.assists,
                        gold_earned = EXCLUDED.gold_earned
                    """,
                    row,
                )
            for row in frame_rows:
                cur.execute(
                    """
                    INSERT INTO participant_frames (match_id, participant_id, frame_timestamp_ms,
                        total_gold, xp, level, minions_killed, jungle_minions_killed, position_x, position_y)
                    VALUES (%(match_id)s, %(participant_id)s, %(frame_timestamp_ms)s, %(total_gold)s,
                        %(xp)s, %(level)s, %(minions_killed)s, %(jungle_minions_killed)s, %(position_x)s, %(position_y)s)
                    ON CONFLICT (match_id, participant_id, frame_timestamp_ms) DO UPDATE SET
                        total_gold = EXCLUDED.total_gold, xp = EXCLUDED.xp
                    """,
                    row,
                )
            # events has only a surrogate primary key (no natural unique constraint), so a
            # plain upsert can't detect "this row already exists" — delete and reinsert instead.
            cur.execute("DELETE FROM events WHERE match_id = %s", (match_id,))
            for row in event_rows:
                cur.execute(
                    """
                    INSERT INTO events (match_id, timestamp_ms, event_type, participant_id, team_id, details)
                    VALUES (%(match_id)s, %(timestamp_ms)s, %(event_type)s, %(participant_id)s, %(team_id)s, %(details)s)
                    """,
                    {**row, "details": json.dumps(row["details"])},
                )
            cur.execute(
                "UPDATE ingestion_log SET parsed_at = now(), status = 'parsed' WHERE match_id = %s",
                (match_id,),
            )
        conn.commit()
    finally:
        conn.close()


def main():
    match_ids = get_fetched_match_ids()
    print(f"Loading {len(match_ids)} matches into normalized tables...")
    for i, match_id in enumerate(match_ids, 1):
        try:
            load_match(match_id)
        except Exception as exc:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE ingestion_log SET status = 'error', error_message = %s WHERE match_id = %s",
                        (str(exc), match_id),
                    )
                conn.commit()
            finally:
                conn.close()
        if i % 25 == 0:
            print(f"  {i}/{len(match_ids)} processed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_load_match.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `.venv/Scripts/pytest -v`
Expected: all tests pass (Tasks 1–11 combined).

- [ ] **Step 6: Update `README.md` with the pipeline run order**

Add this section to `README.md`:

```markdown
## Running the ingestion pipeline

Requires Postgres running (`docker compose up -d`) and `RIOT_API_KEY` / `DATABASE_URL` set in `.env`.

1. `python scripts/init_db.py` — create tables (safe to rerun)
2. `python scripts/load_champions.py` — populate the champions dimension (rerun after a new champion release)
3. `python scripts/seed_players.py` — pull Challenger/GM/Master NA players
4. `python scripts/discover_match_ids.py` — find ranked solo/duo match IDs for seed players
5. `python scripts/fetch_raw.py` — fetch raw match + timeline JSON for pending matches
6. `python scripts/load_match.py` — parse raw JSON and load normalized tables

Steps 3-6 are safe to rerun — matches already `fetched`/`parsed` are skipped by `ingestion_log.status`.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/load_match.py tests/test_load_match.py README.md
git commit -m "Add DB loader tying parsers together, update README with pipeline run order"
```
