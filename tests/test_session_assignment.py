from datetime import datetime, timedelta, timezone

from session_assignment import assign_sessions

START = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


def _window(start, duration_min):
    end = start + timedelta(minutes=duration_min)
    return {"match_id": f"M-{start.isoformat()}", "game_start": start, "game_end": end}


def test_assigns_session_id_and_index_using_45_minute_gap():
    # Session 1: two back-to-back games (10 min gap). Session 2: a lone game
    # after a 60-minute break (over the 45-minute threshold).
    game_a = _window(START, duration_min=25)
    game_b = _window(game_a["game_end"] + timedelta(minutes=10), duration_min=25)
    game_c = _window(game_b["game_end"] + timedelta(minutes=60), duration_min=25)

    rows = assign_sessions([game_a, game_b, game_c])

    by_match = {r["match_id"]: r for r in rows}
    assert by_match[game_a["match_id"]]["session_id"] == by_match[game_b["match_id"]]["session_id"]
    assert by_match[game_b["match_id"]]["session_id"] != by_match[game_c["match_id"]]["session_id"]
    assert by_match[game_a["match_id"]]["game_index_within_session"] == 1
    assert by_match[game_b["match_id"]]["game_index_within_session"] == 2
    assert by_match[game_c["match_id"]]["game_index_within_session"] == 1
