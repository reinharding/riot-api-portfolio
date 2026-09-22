from game_floor import check_game_floor

PUUID = "puuid-1"


def _insert_match(db_conn, match_id, game_duration_seconds=1800):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO matches (match_id, platform, queue_id, game_creation, game_duration_seconds, game_version)
            VALUES (%s, 'NA1', 420, now(), %s, '14.1')
            """,
            (match_id, game_duration_seconds),
        )


def _insert_participant(db_conn, match_id, puuid=PUUID):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO participants (match_id, puuid, team_id, win, kills, deaths, assists, gold_earned, damage_dealt_to_champions)
            VALUES (%s, %s, 100, true, 5, 1, 3, 12000, 20000)
            """,
            (match_id, puuid),
        )


def _seed_games(db_conn, count, puuid=PUUID):
    for i in range(count):
        match_id = f"NA1_{i}"
        _insert_match(db_conn, match_id)
        _insert_participant(db_conn, match_id, puuid)
    db_conn.commit()


def test_reports_not_enough_data_below_floor(db_conn):
    _seed_games(db_conn, 29)
    result = check_game_floor(PUUID, conn=db_conn, floor=30)
    assert result == {"status": "not_enough_data", "game_count": 29}


def test_reports_ready_at_floor(db_conn):
    _seed_games(db_conn, 30)
    result = check_game_floor(PUUID, conn=db_conn, floor=30)
    assert result == {"status": "ready", "game_count": 30}


def test_remade_games_do_not_count_toward_floor(db_conn):
    _seed_games(db_conn, 30)
    _insert_match(db_conn, "NA1_REMAKE", game_duration_seconds=84)
    _insert_participant(db_conn, "NA1_REMAKE")
    db_conn.commit()

    result = check_game_floor(PUUID, conn=db_conn, floor=30)
    assert result == {"status": "ready", "game_count": 30}
