EXPECTED_TABLES = {"matches", "participants", "ingestion_watermark", "pipeline_runs"}


def test_apply_schema_creates_all_tables(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_TABLES.issubset(tables)


def test_matches_and_participants_support_on_conflict_upsert(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO matches (match_id, platform, queue_id, game_creation, game_duration_seconds, game_version)
            VALUES ('NA1_1', 'NA1', 420, now(), 1800, '14.1')
            ON CONFLICT (match_id) DO UPDATE SET game_duration_seconds = EXCLUDED.game_duration_seconds
            """
        )
        cur.execute(
            """
            INSERT INTO participants (match_id, puuid, team_id, win, kills, deaths, assists, gold_earned)
            VALUES ('NA1_1', 'puuid-1', 100, true, 5, 1, 3, 12000)
            ON CONFLICT (match_id, puuid) DO UPDATE SET kills = EXCLUDED.kills
            """
        )
    db_conn.commit()


def test_ingestion_watermark_keyed_per_puuid(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_watermark (puuid, last_match_id) VALUES ('puuid-1', 'NA1_1')"
        )
        cur.execute(
            "INSERT INTO ingestion_watermark (puuid, last_match_id) VALUES ('puuid-1', 'NA1_2') "
            "ON CONFLICT (puuid) DO UPDATE SET last_match_id = EXCLUDED.last_match_id"
        )
        cur.execute("SELECT last_match_id FROM ingestion_watermark WHERE puuid = 'puuid-1'")
        assert cur.fetchone() == ("NA1_2",)
    db_conn.commit()


def test_pipeline_runs_includes_trigger_type(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (trigger_type, started_at) VALUES ('manual', now()) RETURNING trigger_type"
        )
        assert cur.fetchone() == ("manual",)
    db_conn.commit()
