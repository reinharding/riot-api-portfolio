import pytest

from ingestion import run_ingestion

PUUID = "puuid-1"


def _fake_detail(match_id: str, game_creation_ms: int) -> dict:
    return {
        "metadata": {"matchId": match_id},
        "info": {
            "platformId": "NA1",
            "queueId": 420,
            "gameCreation": game_creation_ms,
            "gameDuration": 1800,
            "gameVersion": "14.1.1.1",
            "participants": [
                {
                    "puuid": PUUID,
                    "teamId": 100,
                    "teamPosition": "MID",
                    "win": True,
                    "kills": 5,
                    "deaths": 1,
                    "assists": 3,
                    "goldEarned": 12000,
                    "totalDamageDealtToChampions": 20000,
                },
                {
                    "puuid": "puuid-enemy",
                    "teamId": 200,
                    "teamPosition": "MID",
                    "win": False,
                    "kills": 1,
                    "deaths": 5,
                    "assists": 0,
                    "goldEarned": 8000,
                    "totalDamageDealtToChampions": 9000,
                },
            ],
        },
    }


MATCHES = {
    "NA1_1": _fake_detail("NA1_1", 1_000_000),
    "NA1_2": _fake_detail("NA1_2", 2_000_000),
    "NA1_3": _fake_detail("NA1_3", 3_000_000),
}


def _counts(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM matches")
        matches = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM participants")
        participants = cur.fetchone()[0]
    return matches, participants


def _single_page(ids: list[str]):
    """Fake fetch_match_ids_page returning all ids on the first page, none after."""
    def _fetch(puuid, start, count):
        return ids if start == 0 else []
    return _fetch


def _watermark(db_conn, puuid=PUUID):
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT last_match_id, last_match_game_creation FROM ingestion_watermark WHERE puuid = %s",
            (puuid,),
        )
        return cur.fetchone()


def test_run_ingestion_with_new_games_creates_rows_and_advances_watermark(db_conn):
    ids = ["NA1_1", "NA1_2"]
    result = run_ingestion(
        PUUID,
        conn=db_conn,
        fetch_match_ids_page=_single_page(ids),
        fetch_match_detail=lambda match_id: MATCHES[match_id],
    )
    db_conn.commit()

    assert result == {"status": "success", "new_matches": 2}
    matches, participants = _counts(db_conn)
    assert matches == 2
    assert participants == 4
    last_match_id, _ = _watermark(db_conn)
    assert last_match_id == "NA1_2"


def test_run_ingestion_rerun_with_no_new_games_is_a_safe_noop(db_conn):
    ids = ["NA1_1", "NA1_2"]
    run_ingestion(
        PUUID,
        conn=db_conn,
        fetch_match_ids_page=_single_page(ids),
        fetch_match_detail=lambda match_id: MATCHES[match_id],
    )
    db_conn.commit()

    before_matches, before_participants = _counts(db_conn)
    before_watermark = _watermark(db_conn)

    result = run_ingestion(
        PUUID,
        conn=db_conn,
        fetch_match_ids_page=_single_page(ids),
        fetch_match_detail=lambda match_id: MATCHES[match_id],
    )
    db_conn.commit()

    assert result == {"status": "noop", "new_matches": 0}
    assert _counts(db_conn) == (before_matches, before_participants)
    assert _watermark(db_conn) == before_watermark


def test_run_ingestion_rolls_back_completely_on_mid_batch_failure(db_conn):
    ids = ["NA1_1", "NA1_2", "NA1_3"]

    def flaky_fetch_detail(match_id):
        if match_id == "NA1_3":
            raise RuntimeError("simulated crash mid-batch")
        return MATCHES[match_id]

    with pytest.raises(RuntimeError, match="simulated crash mid-batch"):
        run_ingestion(
            PUUID,
            conn=db_conn,
            fetch_match_ids_page=_single_page(ids),
            fetch_match_detail=flaky_fetch_detail,
        )

    assert _counts(db_conn) == (0, 0)
    assert _watermark(db_conn) is None
