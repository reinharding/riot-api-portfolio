from db import get_connection


def test_get_connection_executes_select_1(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
