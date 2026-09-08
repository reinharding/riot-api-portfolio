import os

import psycopg
import pytest
from dotenv import load_dotenv

from migrate import apply_schema

load_dotenv()

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def _schema_ready():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set — no test Postgres available")
    try:
        conn = psycopg.connect(TEST_DATABASE_URL, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"test Postgres not reachable: {exc}")
    try:
        apply_schema(conn)
    finally:
        conn.close()


@pytest.fixture
def db_conn(_schema_ready):
    conn = psycopg.connect(TEST_DATABASE_URL, connect_timeout=3)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE matches, participants, ingestion_watermark, pipeline_runs")
    conn.commit()
    yield conn
    conn.close()
