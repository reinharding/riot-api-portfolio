"""Small shared HTTP helper for the Riot API: auth header + basic rate-limit/retry handling."""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["RIOT_API_KEY"]

# Dev key limits: 20 req/sec, 100 req/2min. Sleeping this long between calls
# keeps us comfortably under the 2-minute bucket (~85 req/2min).
MIN_INTERVAL_SECONDS = 1.3

# Without an explicit timeout requests waits forever, so a single stalled TLS
# handshake hangs the whole run with no output. Retry before giving up.
REQUEST_TIMEOUT_SECONDS = 10
TIMEOUT_ATTEMPTS = 3

_last_call = 0.0


def _throttle() -> None:
    elapsed = time.monotonic() - _last_call
    if elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)


def get_json(url: str, params: dict | None = None) -> dict:
    global _last_call

    for attempt in range(1, TIMEOUT_ATTEMPTS + 1):
        _throttle()
        try:
            resp = requests.get(
                url,
                headers={"X-Riot-Token": API_KEY},
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout:
            _last_call = time.monotonic()
            if attempt == TIMEOUT_ATTEMPTS:
                raise
            print(f"Timed out (attempt {attempt}/{TIMEOUT_ATTEMPTS}), retrying...")
            continue

        _last_call = time.monotonic()

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            print(f"Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            return get_json(url, params)

        resp.raise_for_status()
        return resp.json()

    raise AssertionError("unreachable")
