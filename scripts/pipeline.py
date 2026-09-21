"""Run-history wrapper around ingestion: logs a pipeline_runs row per ADR 0002."""
import os
from datetime import datetime, timezone

from db import session
from ingestion import run_ingestion

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


def load_tracked_puuids() -> list[str]:
    raw = os.environ.get("TRACKED_PUUIDS", "")
    return [p for p in (puuid.strip() for puuid in raw.split(",")) if p]


def run_pipeline(trigger_type: str, puuids: list[str] | None = None, conn=None) -> dict:
    puuids = puuids if puuids is not None else load_tracked_puuids()

    with session(conn) as conn:
        started_at = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (trigger_type, started_at, status) VALUES (%s, %s, %s) RETURNING run_id",
                (trigger_type, started_at, STATUS_RUNNING),
            )
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            for puuid in puuids:
                run_ingestion(puuid, conn=conn)
            status = STATUS_SUCCESS
            error_message = None
        except Exception as exc:
            status = STATUS_FAILED
            error_message = str(exc)
            raise
        finally:
            ended_at = datetime.now(timezone.utc)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_runs SET ended_at = %s, status = %s, error_message = %s WHERE run_id = %s",
                    (ended_at, status, error_message, run_id),
                )
            conn.commit()

    return {"run_id": run_id, "status": status}


if __name__ == "__main__":
    run_pipeline("manual")
