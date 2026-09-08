"""Data quality checks, read directly from Postgres.

Freshness is measured relative to the last successful watermark advance, not
wall-clock time (ADR 0004) -- a standard "no data in N hours" check would
alarm on every gap between manual runs (ADR 0002), training us to ignore it.
"days_since_last_run" is tracked separately as a non-alerting metric so that
pattern stays visible without itself failing the freshness check.
"""
from datetime import datetime, timezone

from db import get_connection

DEFAULT_FRESHNESS_MAX_DAYS = 3


def _check_freshness(cur, now: datetime, max_days: float) -> dict:
    # MIN, not MAX: a recently-refreshed player must not mask a lagging one --
    # every tracked PUUID's watermark has to be within the freshness window.
    cur.execute("SELECT MIN(updated_at) FROM ingestion_watermark")
    (stalest_advance,) = cur.fetchone()
    if stalest_advance is None:
        return {"passed": False, "detail": "no successful ingestion watermark advance on record"}
    age_days = (now - stalest_advance).total_seconds() / 86400
    return {
        "passed": age_days <= max_days,
        "detail": f"stalest watermark advance {age_days:.2f} days ago (max {max_days})",
    }


def _days_since_last_run(cur, now: datetime) -> float | None:
    cur.execute("SELECT MAX(started_at) FROM pipeline_runs")
    (last_started,) = cur.fetchone()
    if last_started is None:
        return None
    return (now - last_started).total_seconds() / 86400


def _check_row_count_bounds(cur, min_participants: int = 1, max_participants: int = 10) -> dict:
    cur.execute(
        """
        SELECT match_id, COUNT(*) AS n
        FROM participants
        GROUP BY match_id
        HAVING COUNT(*) < %s OR COUNT(*) > %s
        """,
        (min_participants, max_participants),
    )
    offenders = cur.fetchall()
    return {
        "passed": len(offenders) == 0,
        "detail": f"{len(offenders)} match(es) with participant count outside [{min_participants}, {max_participants}]",
    }


def _check_null_rates(cur) -> dict:
    cur.execute("SELECT COUNT(*) FROM participants WHERE damage_dealt_to_champions IS NULL")
    (null_count,) = cur.fetchone()
    return {
        "passed": null_count == 0,
        "detail": f"{null_count} participant row(s) with null damage_dealt_to_champions",
    }


def _check_referential_integrity(cur) -> dict:
    cur.execute(
        """
        SELECT COUNT(*) FROM participants p
        WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.match_id = p.match_id)
        """
    )
    (orphaned_participants,) = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*) FROM ingestion_watermark w
        WHERE w.last_match_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.match_id = w.last_match_id)
        """
    )
    (dangling_watermarks,) = cur.fetchone()

    passed = orphaned_participants == 0 and dangling_watermarks == 0
    return {
        "passed": passed,
        "detail": (
            f"{orphaned_participants} orphaned participant row(s), "
            f"{dangling_watermarks} watermark(s) pointing at a missing match"
        ),
    }


def run_data_quality_checks(
    conn=None,
    now: datetime | None = None,
    freshness_max_days: float = DEFAULT_FRESHNESS_MAX_DAYS,
) -> dict:
    owns_conn = conn is None
    conn = conn or get_connection()
    now = now or datetime.now(timezone.utc)
    try:
        with conn.cursor() as cur:
            checks = {
                "freshness": _check_freshness(cur, now, freshness_max_days),
                "row_count_bounds": _check_row_count_bounds(cur),
                "null_rates": _check_null_rates(cur),
                "referential_integrity": _check_referential_integrity(cur),
            }
            metrics = {"days_since_last_run": _days_since_last_run(cur, now)}
        return {
            "checks": checks,
            "metrics": metrics,
            "all_passed": all(c["passed"] for c in checks.values()),
        }
    finally:
        if owns_conn:
            conn.close()
