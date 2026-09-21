"""Postgres connection helper."""
import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection(database_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url or os.environ["DATABASE_URL"])


@contextmanager
def session(conn: psycopg.Connection | None = None):
    """Yield a connection, owning its lifecycle only when the caller didn't supply one.

    Centralizes the "did I open this, so am I the one who closes it" rule that
    used to be copy-pasted in every module that accepted an optional conn.
    """
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        yield conn
    finally:
        if owns_conn:
            conn.close()
