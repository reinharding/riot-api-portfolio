# LoL Analytics (Riot API Portfolio Project)

4-week data engineering/analytics portfolio project built on the Riot Games API (League of Legends, NA region).
Goal: demonstrate ingestion, pipeline hardening, analysis, and dashboarding skills for data analyst/data engineer roles.

## Plan

- **Week 1**: API ingestion + schema design (match IDs/details/timelines, tables for matches/participants/teams/champions/patches)
- **Week 2**: Pipeline hardening (rate-limit handling, incremental loads, idempotency, patch-version tracking)
- **Week 3**: SQL/pandas analysis (win rates by champion/role/patch, first-blood/tower impact, gold-diff-at-15 predictor)
- **Week 4**: Streamlit dashboard + README/case study + architecture diagram

## Setup

1. Get a dev API key from the [Riot Developer Portal](https://developer.riotgames.com/) (expires every 24h, regenerate as needed).
2. Put it in `.env`: `RIOT_API_KEY=your-key-here`
3. `pip install -r requirements.txt`
4. `python scripts/test_api.py` — sanity check the key works
5. `python scripts/seed_players.py` — pull Challenger/GM/Master NA players -> PUUIDs -> ranked match IDs

## Region routing notes

- Platform routing (`na1`) for summoner/league endpoints
- Regional routing (`americas`) for match-v5 endpoints
- Dev key limits: 20 req/sec, 100 req/2min

## Scripts

- `scripts/riot_client.py` — shared request helper (auth header, throttling, 429 retry)
- `scripts/test_api.py` — confirms API key + routing work
- `scripts/seed_players.py` — seed-list puller: apex-tier players -> PUUIDs -> match IDs
