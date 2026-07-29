"""Sanity check: confirm the Riot API key and platform routing work."""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["RIOT_API_KEY"]
PLATFORM = "na1"

url = f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5"
resp = requests.get(url, headers={"X-Riot-Token": API_KEY})
resp.raise_for_status()

data = resp.json()
print(f"Queue: {data['queue']}")
print(f"Entries: {len(data['entries'])}")
print("First entry:", data["entries"][0])
