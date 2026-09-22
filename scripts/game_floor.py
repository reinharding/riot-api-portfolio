"""30-ranked-game floor gate (ticket 05): blocks Phase 4's model until enough data exists."""
from db import session

# Riot voids a game (no LP change, degenerate stats) when it ends this early,
# e.g. an early-surrender/AFK remake -- these aren't real ranked games and
# must not count toward the floor or feed the composite metric's baselines.
REMAKE_THRESHOLD_SECONDS = 300


def check_game_floor(puuid: str, conn=None, floor: int = 30) -> dict:
    """Count puuid's non-remake ranked games and report whether the floor is met."""
    with session(conn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM participants p
                JOIN matches m ON m.match_id = p.match_id
                WHERE p.puuid = %s AND m.game_duration_seconds >= %s
                """,
                (puuid, REMAKE_THRESHOLD_SECONDS),
            )
            game_count = cur.fetchone()[0]

    status = "ready" if game_count >= floor else "not_enough_data"
    return {"status": status, "game_count": game_count}
