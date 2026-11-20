"""Durable, restart-safe records for final autopilot video assembly."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from creatorthon_store import _connect


def _ensure(db: Any) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS autopilot_finalization_jobs (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          concept_id TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'queued',
          stage TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '',
          result_json TEXT NOT NULL DEFAULT '{}',
          lease_until BIGINT NOT NULL DEFAULT 0,
          attempt BIGINT NOT NULL DEFAULT 0,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          UNIQUE(customer_id, concept_id)
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_autopilot_finalization_status "
        "ON autopilot_finalization_jobs(status, lease_until)"
    )


def _decode(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    for source, target in (("payload_json", "payload"), ("result_json", "result")):
        try:
            item[target] = json.loads(item.pop(source) or "{}")
        except (TypeError, ValueError):
            item[target] = {}
    return item


def get(root: Path, customer_id: str, concept_id: str) -> dict[str, Any] | None:
    with _connect(root) as db:
        _ensure(db)
        row = db.execute(
            "SELECT * FROM autopilot_finalization_jobs WHERE customer_id=? AND concept_id=?",
            (customer_id, concept_id),
        ).fetchone()
    return _decode(row)


def enqueue(root: Path, customer_id: str, concept_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    now, job_id = int(time.time()), uuid.uuid4().hex
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with _connect(root) as db:
        _ensure(db)
        db.execute(
            """INSERT INTO autopilot_finalization_jobs
            (id,customer_id,concept_id,payload_json,status,stage,created_at,updated_at)
            VALUES(?,?,?,?, 'queued','Final assembly queued',?,?)
            ON CONFLICT(customer_id,concept_id) DO UPDATE SET
              payload_json=excluded.payload_json,
              status=CASE WHEN autopilot_finalization_jobs.status='succeeded' THEN autopilot_finalization_jobs.status ELSE 'queued' END,
              stage=CASE WHEN autopilot_finalization_jobs.status='succeeded' THEN autopilot_finalization_jobs.stage ELSE 'Final assembly queued' END,
              error=CASE WHEN autopilot_finalization_jobs.status='succeeded' THEN autopilot_finalization_jobs.error ELSE '' END,
              lease_until=CASE WHEN autopilot_finalization_jobs.status='succeeded' THEN autopilot_finalization_jobs.lease_until ELSE 0 END,
              updated_at=excluded.updated_at""",
            (job_id, customer_id, concept_id, encoded, now, now),
        )
        row = db.execute(
            "SELECT * FROM autopilot_finalization_jobs WHERE customer_id=? AND concept_id=?",
            (customer_id, concept_id),
        ).fetchone()
    return _decode(row) or {}


def claim(root: Path, customer_id: str, concept_id: str, lease_seconds: int = 180) -> dict[str, Any] | None:
    now = int(time.time())
    with _connect(root) as db:
        _ensure(db)
        row = db.execute(
            """UPDATE autopilot_finalization_jobs
            SET status='processing',stage='Downloading completed scenes and assembling the final MP4…',
                error='',lease_until=?,attempt=attempt+1,updated_at=?
            WHERE customer_id=? AND concept_id=? AND status<>'succeeded'
              AND (status IN ('queued','failed') OR lease_until<=?)
            RETURNING *""",
            (now + lease_seconds, now, customer_id, concept_id, now),
        ).fetchone()
    return _decode(row)


def renew(root: Path, customer_id: str, concept_id: str, lease_seconds: int = 180) -> None:
    now = int(time.time())
    with _connect(root) as db:
        _ensure(db)
        db.execute(
            """UPDATE autopilot_finalization_jobs SET lease_until=?,updated_at=?
            WHERE customer_id=? AND concept_id=? AND status='processing'""",
            (now + lease_seconds, now, customer_id, concept_id),
        )


def finish(
    root: Path,
    customer_id: str,
    concept_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any] | None:
    now = int(time.time())
    status = "failed" if error else "succeeded"
    stage = "Final assembly failed" if error else "Final video ready"
    with _connect(root) as db:
        _ensure(db)
        row = db.execute(
            """UPDATE autopilot_finalization_jobs
            SET status=?,stage=?,error=?,result_json=?,lease_until=0,updated_at=?
            WHERE customer_id=? AND concept_id=? RETURNING *""",
            (
                status,
                stage,
                str(error or "")[:2000],
                json.dumps(result or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                now,
                customer_id,
                concept_id,
            ),
        ).fetchone()
    return _decode(row)


def retry(root: Path, customer_id: str, concept_id: str, error: str) -> dict[str, Any] | None:
    """Release a failed lease back to the durable queue without losing its payload."""
    now = int(time.time())
    with _connect(root) as db:
        _ensure(db)
        row = db.execute(
            """UPDATE autopilot_finalization_jobs
            SET status='queued',stage='Temporary assembly failure; retrying automatically…',
                error=?,lease_until=0,updated_at=?
            WHERE customer_id=? AND concept_id=? AND status='processing' RETURNING *""",
            (str(error or "")[:2000], now, customer_id, concept_id),
        ).fetchone()
    return _decode(row)

