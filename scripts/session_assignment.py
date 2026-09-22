"""Assign session identity and within-session game order (ticket 07).

Uses the frozen 45-minute gap threshold (ADR 0005): a game starting more
than SESSION_GAP_MINUTES after the previous game ended starts a new session.
"""
SESSION_GAP_MINUTES = 45


def assign_sessions(game_windows: list[dict]) -> list[dict]:
    """game_windows: dicts with game_start/game_end, oldest first.

    Returns each window's dict plus session_id (int, increasing) and
    game_index_within_session (1-based order inside that session).
    """
    rows = []
    session_id = 0
    game_index = 0
    prev_end = None
    for window in game_windows:
        if prev_end is None or (window["game_start"] - prev_end).total_seconds() / 60 > SESSION_GAP_MINUTES:
            session_id += 1
            game_index = 1
        else:
            game_index += 1
        rows.append({**window, "session_id": session_id, "game_index_within_session": game_index})
        prev_end = window["game_end"]
    return rows
