"""Sanity check: confirm the Riot API key and platform routing work."""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["RIOT_API_KEY"]
PLATFORM = "na1"
REGION = "americas"

TIERS = {
    "CHALLENGER": "challengerleagues/by-queue/RANKED_SOLO_5x5",
    "GRANDMASTER": "grandmasterleagues/by-queue/RANKED_SOLO_5x5",
    "MASTER": "masterleagues/by-queue/RANKED_SOLO_5x5",
}

all_puuids = []

for tier, path in TIERS.items():
    full_url = f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/{path}"
    resp = requests.get(full_url, headers={"X-Riot-Token": API_KEY})
    resp.raise_for_status()

    data = resp.json()
    for entry in data["entries"]:
        all_puuids.append(entry["puuid"])
    print(f"{tier}: {len(data['entries'])} entries")

print(len(all_puuids))

with open("data/seed_puuids.json", "w") as f:
    json.dump(all_puuids, f, indent=2)

test_puuid = all_puuids[0]