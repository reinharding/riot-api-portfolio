"""Session gap-threshold sensitivity testing (ticket 06).

Reads only raw game timestamps/durations -- never the composite metric
(ticket 05) or any other performance data -- so the frozen threshold
can't be accused of being tuned to manufacture a tilt effect (ADR 0005).
"""
from psycopg.rows import dict_row

from db import session
from game_floor import REMAKE_THRESHOLD_SECONDS

CANDIDATE_THRESHOLDS_MIN = (10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 90, 120, 150, 180, 240)


def fetch_game_windows(puuid: str, conn=None) -> list[dict]:
    """game_start/game_end for puuid's non-remake ranked games, oldest first."""
    with session(conn) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    m.game_creation AS game_start,
                    m.game_creation + (m.game_duration_seconds * interval '1 second') AS game_end
                FROM matches m
                JOIN participants p ON p.match_id = m.match_id
                WHERE p.puuid = %s AND m.game_duration_seconds >= %s
                ORDER BY m.game_creation
                """,
                (puuid, REMAKE_THRESHOLD_SECONDS),
            )
            return cur.fetchall()


def compute_gaps_minutes(game_windows: list[dict]) -> list[float]:
    """Gap between each game's end and the next game's start, in minutes."""
    return [
        (next_window["game_start"] - window["game_end"]).total_seconds() / 60
        for window, next_window in zip(game_windows, game_windows[1:])
    ]


def sensitivity_table(gaps: list[float], candidate_thresholds=CANDIDATE_THRESHOLDS_MIN) -> list[dict]:
    n_games = len(gaps) + 1
    rows = []
    for threshold in candidate_thresholds:
        breaks_over_threshold = sum(1 for g in gaps if g > threshold)
        session_count = 1 + breaks_over_threshold
        rows.append({
            "threshold_min": threshold,
            "session_count": session_count,
            "avg_games_per_session": n_games / session_count,
        })
    return rows
