"""Apply schema.sql to the target database. Idempotent (CREATE TABLE IF NOT EXISTS)."""
from pathlib import Path

from db import session

SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


def apply_schema(conn=None) -> None:
    sql = SCHEMA_PATH.read_text()
    with session(conn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


if __name__ == "__main__":
    apply_schema()
    print("Schema applied.")
