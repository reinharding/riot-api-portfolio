"""Postgres connection helper."""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection(database_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url or os.environ["DATABASE_URL"])
