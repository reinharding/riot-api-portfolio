import pytest

import pipeline


def _run_row(db_conn, run_id):
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT trigger_type, status, started_at, ended_at FROM pipeline_runs WHERE run_id = %s",
            (run_id,),
        )
        return cur.fetchone()


@pytest.mark.parametrize("trigger_type", ["manual", "scheduled"])
def test_run_pipeline_logs_row_with_trigger_type(db_conn, monkeypatch, trigger_type):
    monkeypatch.setattr(pipeline, "run_ingestion", lambda puuid, conn=None: {"status": "noop"})

    result = pipeline.run_pipeline(trigger_type, puuids=["puuid-1"], conn=db_conn)

    trigger, status, started_at, ended_at = _run_row(db_conn, result["run_id"])
    assert trigger == trigger_type
    assert status == "success"
    assert started_at is not None
    assert ended_at is not None


def test_run_pipeline_records_failed_status_when_ingestion_raises(db_conn, monkeypatch):
    def boom(puuid, conn=None):
        raise RuntimeError("riot api down")

    monkeypatch.setattr(pipeline, "run_ingestion", boom)

    with pytest.raises(RuntimeError):
        pipeline.run_pipeline("manual", puuids=["puuid-1"], conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute("SELECT status, error_message FROM pipeline_runs ORDER BY run_id DESC LIMIT 1")
        status, error_message = cur.fetchone()
    assert status == "failed"
    assert error_message == "riot api down"
