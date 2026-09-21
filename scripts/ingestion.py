"""Idempotent ingestion for one PUUID: watermark -> fetch new matches -> upsert -> advance watermark.

The commit/rollback shape mirrors prototypes/ingestion-watermark-transaction.PROTOTYPE.html:
everything for a run happens in one transaction, so a mid-batch failure leaves
zero rows committed and the watermark untouched.
"""
from datetime import datetime, timezone

from db import session
from riot_client import get_json

REGION = "americas"
MATCH_IDS_PAGE_SIZE = 100  # Riot's max page size for this endpoint


def fetch_match_ids_page(puuid: str, start: int, count: int) -> list[str]:
    """One page of most-recent-first ranked solo/duo match IDs for this PUUID."""
    url = f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {"queue": 420, "type": "ranked", "start": start, "count": count}
    return get_json(url, params)


def _fetch_all_candidate_ids(puuid: str, fetch_page) -> list[str]:
    """Paginate through fetch_page until a short page signals no more history.

    Without this, a backlog larger than one page would be silently dropped:
    the watermark would still advance past matches that were never fetched.
    """
    ids: list[str] = []
    start = 0
    while True:
        page = fetch_page(puuid, start=start, count=MATCH_IDS_PAGE_SIZE)
        if not page:
            break
        ids.extend(page)
        if len(page) < MATCH_IDS_PAGE_SIZE:
            break
        start += MATCH_IDS_PAGE_SIZE
    return ids


def fetch_match_detail(match_id: str) -> dict:
    url = f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    return get_json(url)


def _parse_match(detail: dict) -> dict:
    info = detail["info"]
    return {
        "match_id": detail["metadata"]["matchId"],
        "platform": info["platformId"],
        "queue_id": info["queueId"],
        "game_creation": datetime.fromtimestamp(info["gameCreation"] / 1000, tz=timezone.utc),
        "game_duration_seconds": info["gameDuration"],
        "game_version": info["gameVersion"],
    }


def _parse_participants(detail: dict) -> list[dict]:
    match_id = detail["metadata"]["matchId"]
    rows = []
    for p in detail["info"]["participants"]:
        rows.append({
            "match_id": match_id,
            "puuid": p["puuid"],
            "team_id": p["teamId"],
            "team_position": p.get("teamPosition") or None,
            "win": p["win"],
            "kills": p["kills"],
            "deaths": p["deaths"],
            "assists": p["assists"],
            "gold_earned": p["goldEarned"],
            "damage_dealt_to_champions": p.get("totalDamageDealtToChampions"),
        })
    return rows


def _upsert_match(cur, match_row: dict) -> None:
    cur.execute(
        """
        INSERT INTO matches (match_id, platform, queue_id, game_creation, game_duration_seconds, game_version)
        VALUES (%(match_id)s, %(platform)s, %(queue_id)s, %(game_creation)s, %(game_duration_seconds)s, %(game_version)s)
        ON CONFLICT (match_id) DO UPDATE SET
            platform = EXCLUDED.platform,
            queue_id = EXCLUDED.queue_id,
            game_creation = EXCLUDED.game_creation,
            game_duration_seconds = EXCLUDED.game_duration_seconds,
            game_version = EXCLUDED.game_version
        """,
        match_row,
    )


def _upsert_participant(cur, row: dict) -> None:
    cur.execute(
        """
        INSERT INTO participants (match_id, puuid, team_id, team_position, win, kills, deaths, assists, gold_earned, damage_dealt_to_champions)
        VALUES (%(match_id)s, %(puuid)s, %(team_id)s, %(team_position)s, %(win)s, %(kills)s, %(deaths)s, %(assists)s, %(gold_earned)s, %(damage_dealt_to_champions)s)
        ON CONFLICT (match_id, puuid) DO UPDATE SET
            team_id = EXCLUDED.team_id,
            team_position = EXCLUDED.team_position,
            win = EXCLUDED.win,
            kills = EXCLUDED.kills,
            deaths = EXCLUDED.deaths,
            assists = EXCLUDED.assists,
            gold_earned = EXCLUDED.gold_earned,
            damage_dealt_to_champions = EXCLUDED.damage_dealt_to_champions
        """,
        row,
    )


def run_ingestion(
    puuid: str,
    conn=None,
    fetch_match_ids_page=fetch_match_ids_page,
    fetch_match_detail=fetch_match_detail,
) -> dict:
    with session(conn) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_match_game_creation FROM ingestion_watermark WHERE puuid = %s",
                    (puuid,),
                )
                row = cur.fetchone()
                watermark_time = row[0] if row else None

                candidate_ids = _fetch_all_candidate_ids(puuid, fetch_match_ids_page)

                # Fetch and write each match in the same pass (rather than
                # fetching everything first, then writing): a failure partway
                # through must roll back matches already written this run,
                # not just abort before any writes happened.
                processed_matches = []
                for match_id in candidate_ids:
                    detail = fetch_match_detail(match_id)
                    match_row = _parse_match(detail)
                    if watermark_time is not None and match_row["game_creation"] <= watermark_time:
                        continue

                    _upsert_match(cur, match_row)
                    for participant_row in _parse_participants(detail):
                        _upsert_participant(cur, participant_row)
                    processed_matches.append(match_row)

                if not processed_matches:
                    return {"status": "noop", "new_matches": 0}

                newest_match_row = max(processed_matches, key=lambda m: m["game_creation"])
                cur.execute(
                    """
                    INSERT INTO ingestion_watermark (puuid, last_match_id, last_match_game_creation, updated_at)
                    VALUES (%(puuid)s, %(match_id)s, %(game_creation)s, now())
                    ON CONFLICT (puuid) DO UPDATE SET
                        last_match_id = EXCLUDED.last_match_id,
                        last_match_game_creation = EXCLUDED.last_match_game_creation,
                        updated_at = now()
                    """,
                    {
                        "puuid": puuid,
                        "match_id": newest_match_row["match_id"],
                        "game_creation": newest_match_row["game_creation"],
                    },
                )

            return {"status": "success", "new_matches": len(processed_matches)}
