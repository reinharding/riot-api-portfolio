from datetime import datetime, timedelta, timezone

from data_quality import run_data_quality_checks

NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def _insert_match(db_conn, match_id="NA1_1", game_creation=None):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO matches (match_id, platform, queue_id, game_creation, game_duration_seconds, game_version)
            VALUES (%s, 'NA1', 420, %s, 1800, '14.1')
            """,
            (match_id, game_creation or NOW),
        )


def _insert_participant(db_conn, match_id="NA1_1", puuid="puuid-1", damage=20000):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO participants (match_id, puuid, team_id, win, kills, deaths, assists, gold_earned, damage_dealt_to_champions)
            VALUES (%s, %s, 100, true, 5, 1, 3, 12000, %s)
            """,
            (match_id, puuid, damage),
        )


def _insert_watermark(db_conn, puuid="puuid-1", last_match_id="NA1_1", updated_at=None):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_watermark (puuid, last_match_id, updated_at) VALUES (%s, %s, %s)",
            (puuid, last_match_id, updated_at or NOW),
        )


def _seed_healthy(db_conn):
    _insert_match(db_conn)
    _insert_participant(db_conn, puuid="puuid-1")
    _insert_participant(db_conn, puuid="puuid-2")
    _insert_watermark(db_conn)
    db_conn.commit()


def test_all_checks_pass_on_healthy_seeded_data(db_conn):
    _seed_healthy(db_conn)
    report = run_data_quality_checks(conn=db_conn, now=NOW)
    assert report["all_passed"] is True
    assert all(check["passed"] for check in report["checks"].values())


def test_freshness_fails_when_watermark_is_stale(db_conn):
    _insert_match(db_conn)
    _insert_participant(db_conn)
    _insert_watermark(db_conn, updated_at=NOW - timedelta(days=10))
    db_conn.commit()

    report = run_data_quality_checks(conn=db_conn, now=NOW, freshness_max_days=3)
    assert report["checks"]["freshness"]["passed"] is False


def test_freshness_passes_when_watermark_recently_advanced(db_conn):
    _insert_match(db_conn)
    _insert_participant(db_conn)
    _insert_watermark(db_conn, updated_at=NOW - timedelta(hours=1))
    db_conn.commit()

    report = run_data_quality_checks(conn=db_conn, now=NOW, freshness_max_days=3)
    assert report["checks"]["freshness"]["passed"] is True


def test_days_since_last_run_is_tracked_but_does_not_fail_freshness(db_conn):
    _seed_healthy(db_conn)
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (trigger_type, started_at, status) VALUES ('manual', %s, 'success')",
            (NOW - timedelta(days=30),),
        )
    db_conn.commit()

    report = run_data_quality_checks(conn=db_conn, now=NOW, freshness_max_days=3)
    assert report["metrics"]["days_since_last_run"] == 30
    assert report["checks"]["freshness"]["passed"] is True
    assert report["all_passed"] is True


def test_orphaned_participant_row_fails_referential_integrity(db_conn):
    _insert_participant(db_conn, match_id="NA1_MISSING")
    db_conn.commit()

    report = run_data_quality_checks(conn=db_conn, now=NOW)
    assert report["checks"]["referential_integrity"]["passed"] is False


def test_dangling_watermark_fails_referential_integrity(db_conn):
    _insert_watermark(db_conn, last_match_id="NA1_DOES_NOT_EXIST")
    db_conn.commit()

    report = run_data_quality_checks(conn=db_conn, now=NOW)
    assert report["checks"]["referential_integrity"]["passed"] is False


def test_out_of_bounds_participant_count_fails_row_count_check(db_conn):
    _insert_match(db_conn)
    for i in range(11):
        _insert_participant(db_conn, puuid=f"puuid-{i}")
    db_conn.commit()

    report = run_data_quality_checks(conn=db_conn, now=NOW)
    assert report["checks"]["row_count_bounds"]["passed"] is False


def test_null_required_field_fails_null_rate_check(db_conn):
    _insert_match(db_conn)
    _insert_participant(db_conn, damage=None)
    db_conn.commit()

    report = run_data_quality_checks(conn=db_conn, now=NOW)
    assert report["checks"]["null_rates"]["passed"] is False
