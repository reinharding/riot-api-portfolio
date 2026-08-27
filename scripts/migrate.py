"""Apply schema.sql to the target database. Idempotent (CREATE TABLE IF NOT EXISTS)."""
from pathlib import Path

from db import get_connection

SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


def apply_schema(conn=None) -> None:
    sql = SCHEMA_PATH.read_text()
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


if __name__ == "__main__":
    apply_schema()
    print("Schema applied.")
