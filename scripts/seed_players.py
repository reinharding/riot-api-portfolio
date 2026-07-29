"""
Seed-list puller: Challenger/GM/Master NA players -> PUUIDs -> recent ranked match IDs.

Writes:
  data/seed_players.json  - one entry per player (tier, rank, lp, puuid)
  data/match_ids.json     - deduped list of ranked solo/duo match IDs pulled from those players
"""
import json
import os
from pathlib import Path

from riot_client import get_json

PLATFORM = "na1"
REGION = "americas"
QUEUE = "RANKED_SOLO_5x5"
MATCHES_PER_PLAYER = 20

# Match-id collection costs one throttled call per player, so the full ~11k-player
# seed list takes about 4 hours. Set MAX_PLAYERS for a quick run that still
# produces real output; 0 pulls everything.
MAX_PLAYERS = int(os.environ.get("MAX_PLAYERS", "0"))

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

APEX_TIERS = {
    "CHALLENGER": f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/challengerleagues/by-queue/{QUEUE}",
    "GRANDMASTER": f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/grandmasterleagues/by-queue/{QUEUE}",
    "MASTER": f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/masterleagues/by-queue/{QUEUE}",
}


def fetch_puuid_by_summoner_id(summoner_id: str) -> str:
    url = f"https://{PLATFORM}.api.riotgames.com/lol/summoner/v4/summoners/{summoner_id}"
    return get_json(url)["puuid"]


def collect_seed_players() -> list[dict]:
    players = []
    for tier, url in APEX_TIERS.items():
        data = get_json(url)
        entries = data["entries"]
        print(f"{tier}: {len(entries)} players")

        for entry in entries:
            puuid = entry.get("puuid") or fetch_puuid_by_summoner_id(entry["summonerId"])
            players.append(
                {
                    "puuid": puuid,
                    "tier": tier,
                    "rank": entry["rank"],
                    "league_points": entry["leaguePoints"],
                    "wins": entry["wins"],
                    "losses": entry["losses"],
                }
            )
    return players


def collect_match_ids(players: list[dict]) -> list[str]:
    match_ids: set[str] = set()
    for i, player in enumerate(players, 1):
        url = f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/{player['puuid']}/ids"
        params = {"queue": 420, "type": "ranked", "start": 0, "count": MATCHES_PER_PLAYER}
        ids = get_json(url, params)
        match_ids.update(ids)
        if i % 25 == 0:
            print(f"  {i}/{len(players)} players processed, {len(match_ids)} unique matches so far")
    return sorted(match_ids)


def main():
    print("Pulling seed players (Challenger/GM/Master, NA)...")
    players = collect_seed_players()
    (DATA_DIR / "seed_players.json").write_text(json.dumps(players, indent=2))
    print(f"Saved {len(players)} seed players -> data/seed_players.json")

    # The tier pull above is only 3 calls, so seed_players.json always covers
    # everyone; the cap applies to the expensive per-player match-id stage.
    if MAX_PLAYERS:
        players = players[:MAX_PLAYERS]
        print(f"MAX_PLAYERS={MAX_PLAYERS}: pulling match IDs for the first {len(players)} only")

    print("Pulling ranked match IDs for seed players...")
    match_ids = collect_match_ids(players)
    (DATA_DIR / "match_ids.json").write_text(json.dumps(match_ids, indent=2))
    print(f"Saved {len(match_ids)} unique match IDs -> data/match_ids.json")
    for match_id in match_ids[:3]:
        print(f"  sample: {match_id}")


if __name__ == "__main__":
    main()
