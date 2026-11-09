"""Durable storage primitives for Growth Autopilot workflows and approvals."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from autopilot_contracts import ApprovalCreate, ProviderCostCreate, PublicationPayload, WebhookReceipt, WorkflowRunCreate, WorkflowStepCreate
from creatorthon_store import _connect


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def publication_payload_hash(payload: PublicationPayload | dict[str, Any]) -> tuple[str, dict[str, Any]]:
    model = payload if isinstance(payload, PublicationPayload) else PublicationPayload.model_validate(payload)
    normalized = model.model_dump(mode="json")
    encoded = _json(normalized).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), normalized


def create_workflow_run(root: Path, request: WorkflowRunCreate | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, WorkflowRunCreate) else WorkflowRunCreate.model_validate(request)
    run_id, now = uuid.uuid4().hex, int(time.time())
    with _connect(root) as db:
        db.execute(
            "INSERT INTO autopilot_workflow_runs(id,customer_id,workflow_type,status,input_json,created_at,updated_at) VALUES(?,?,?,'queued',?,?,?)",
            (run_id, model.customer_id, model.workflow_type, _json(model.input), now, now),
        )
        row = db.execute("SELECT * FROM autopilot_workflow_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row)


def get_workflow_run(root: Path, customer_id: str, run_id: str) -> dict[str, Any] | None:
    """Return a customer-scoped run and its ordered steps for read-only status views."""
    with _connect(root) as db:
        run = db.execute(
            "SELECT * FROM autopilot_workflow_runs WHERE id=? AND customer_id=?",
            (run_id, customer_id),
        ).fetchone()
        if not run:
            return None
        steps = db.execute(
            "SELECT * FROM autopilot_workflow_steps WHERE run_id=? AND customer_id=? ORDER BY created_at,id",
            (run_id, customer_id),
        ).fetchall()
    return {"run": dict(run), "steps": [dict(step) for step in steps]}


def enqueue_workflow_step(root: Path, request: WorkflowStepCreate | dict[str, Any]) -> tuple[dict[str, Any], bool]:
    model = request if isinstance(request, WorkflowStepCreate) else WorkflowStepCreate.model_validate(request)
    step_id, now = uuid.uuid4().hex, int(time.time())
    with _connect(root) as db:
        run = db.execute(
            "SELECT id FROM autopilot_workflow_runs WHERE id=? AND customer_id=?",
            (model.run_id, model.customer_id),
        ).fetchone()
        if not run:
            raise ValueError("Workflow run does not belong to this customer.")
        inserted = db.execute(
            """INSERT INTO autopilot_workflow_steps
            (id,run_id,customer_id,agent_type,status,idempotency_key,input_json,max_attempts,next_attempt_at,created_at,updated_at)
            VALUES(?,?,?,?,'queued',?,?,?,?,?,?)
            ON CONFLICT(customer_id,idempotency_key) DO NOTHING RETURNING *""",
            (step_id, model.run_id, model.customer_id, model.agent_type, model.idempotency_key, _json(model.input), model.max_attempts, now, now, now),
        ).fetchone()
        if inserted:
            return dict(inserted), True
        existing = db.execute(
            "SELECT * FROM autopilot_workflow_steps WHERE customer_id=? AND idempotency_key=?",
            (model.customer_id, model.idempotency_key),
        ).fetchone()
    return dict(existing), False


def claim_due_steps(root: Path, worker_id: str, limit: int = 1, lease_seconds: int = 300) -> list[dict[str, Any]]:
    if not worker_id.strip():
        raise ValueError("worker_id is required")
    now, limit = int(time.time()), max(1, min(100, int(limit)))
    with _connect(root) as db:
        if getattr(db, "dialect", "sqlite") == "postgres":
            rows = db.execute(
                """WITH candidates AS (
                  SELECT id FROM autopilot_workflow_steps
                  WHERE status IN ('queued','retry_wait') AND next_attempt_at<=? AND lease_until<=?
                  ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT ?
                )
                UPDATE autopilot_workflow_steps AS steps
                SET status='running',worker_id=?,lease_until=?,attempt=attempt+1,updated_at=?
                FROM candidates WHERE steps.id=candidates.id RETURNING steps.*""",
                (now, now, limit, worker_id, now + lease_seconds, now),
            ).fetchall()
        else:
            rows = db.execute(
                """UPDATE autopilot_workflow_steps
                SET status='running',worker_id=?,lease_until=?,attempt=attempt+1,updated_at=?
                WHERE id IN (
                  SELECT id FROM autopilot_workflow_steps
                  WHERE status IN ('queued','retry_wait') AND next_attempt_at<=? AND lease_until<=?
                  ORDER BY created_at,id LIMIT ?
                ) RETURNING *""",
                (worker_id, now + lease_seconds, now, now, now, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def finish_workflow_step(root: Path, customer_id: str, step_id: str, *, output: dict[str, Any] | None = None, error: dict[str, Any] | None = None, retry_delay: int = 0) -> dict[str, Any]:
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute(
            "SELECT * FROM autopilot_workflow_steps WHERE id=? AND customer_id=?",
            (step_id, customer_id),
        ).fetchone()
        if not row:
            raise ValueError("Workflow step was not found for this customer.")
        item = dict(row)
        if error:
            status = "retry_wait" if int(item["attempt"]) < int(item["max_attempts"]) else "dead_letter"
            next_attempt = now + max(0, retry_delay) if status == "retry_wait" else 0
            db.execute(
                "UPDATE autopilot_workflow_steps SET status=?,error_json=?,next_attempt_at=?,lease_until=0,worker_id='',updated_at=? WHERE id=? AND customer_id=?",
                (status, _json(error), next_attempt, now, step_id, customer_id),
            )
        else:
            db.execute(
                "UPDATE autopilot_workflow_steps SET status='succeeded',output_json=?,error_json='{}',lease_until=0,worker_id='',updated_at=? WHERE id=? AND customer_id=?",
                (_json(output or {}), now, step_id, customer_id),
            )
        updated = db.execute("SELECT * FROM autopilot_workflow_steps WHERE id=?", (step_id,)).fetchone()
    return dict(updated)


def create_content_approval(root: Path, request: ApprovalCreate | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, ApprovalCreate) else ApprovalCreate.model_validate(request)
    approval_id, now = uuid.uuid4().hex, int(time.time())
    payload_hash, normalized = publication_payload_hash(model.publication)
    with _connect(root) as db:
        db.execute(
            """INSERT INTO autopilot_content_approvals
            (id,customer_id,asset_version_id,asset_sha256,destination_id,scheduled_at,payload_hash,payload_json,status,approved_by,approved_at)
            VALUES(?,?,?,?,?,?,?,?, 'approved',?,?)""",
            (approval_id, model.customer_id, normalized["asset_version_id"], normalized["asset_sha256"], normalized["destination_id"], normalized["scheduled_at"], payload_hash, _json(normalized), model.approved_by, now),
        )
        row = db.execute("SELECT * FROM autopilot_content_approvals WHERE id=?", (approval_id,)).fetchone()
    return dict(row)


def revoke_content_approval(root: Path, customer_id: str, approval_id: str) -> bool:
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute(
            "UPDATE autopilot_content_approvals SET status='revoked',revoked_at=? WHERE id=? AND customer_id=? AND status='approved' RETURNING id",
            (now, approval_id, customer_id),
        ).fetchone()
    return bool(row)


def authorize_publication_step(root: Path, customer_id: str, run_id: str, approval_id: str, payload: PublicationPayload | dict[str, Any]) -> tuple[dict[str, Any], bool]:
    payload_hash, normalized = publication_payload_hash(payload)
    now = int(time.time())
    idempotency_key = f"publish:{approval_id}:{payload_hash}"
    with _connect(root) as db:
        approval = db.execute(
            "SELECT * FROM autopilot_content_approvals WHERE id=? AND customer_id=?",
            (approval_id, customer_id),
        ).fetchone()
        if not approval:
            raise PermissionError("Approval was not found for this customer.")
        approved = dict(approval)
        if approved["payload_hash"] != payload_hash:
            raise PermissionError("Publication payload does not match an active approval.")
        if approved["status"] == "consumed":
            existing = db.execute(
                "SELECT * FROM autopilot_workflow_steps WHERE customer_id=? AND idempotency_key=?",
                (customer_id, idempotency_key),
            ).fetchone()
            if existing:
                return dict(existing), False
        if approved["status"] != "approved":
            raise PermissionError("Publication payload does not match an active approval.")
        run = db.execute("SELECT id FROM autopilot_workflow_runs WHERE id=? AND customer_id=?", (run_id, customer_id)).fetchone()
        if not run:
            raise ValueError("Workflow run does not belong to this customer.")
        step_id = uuid.uuid4().hex
        inserted = db.execute(
            """INSERT INTO autopilot_workflow_steps
            (id,run_id,customer_id,agent_type,status,idempotency_key,input_json,max_attempts,next_attempt_at,created_at,updated_at)
            VALUES(?,?,?,'publishing','queued',?,?,3,?,?,?)
            ON CONFLICT(customer_id,idempotency_key) DO NOTHING RETURNING *""",
            (step_id, run_id, customer_id, idempotency_key, _json({"approval_id": approval_id, "publication": normalized}), max(now, int(normalized.get("scheduled_at") or 0)), now, now),
        ).fetchone()
        db.execute(
            "UPDATE autopilot_content_approvals SET status='consumed',consumed_at=? WHERE id=? AND customer_id=? AND status='approved'",
            (now, approval_id, customer_id),
        )
        if inserted:
            return dict(inserted), True
        existing = db.execute(
            "SELECT * FROM autopilot_workflow_steps WHERE customer_id=? AND idempotency_key=?",
            (customer_id, idempotency_key),
        ).fetchone()
    return dict(existing), False


def ingest_webhook_event(root: Path, request: WebhookReceipt | dict[str, Any]) -> tuple[dict[str, Any], bool]:
    model = request if isinstance(request, WebhookReceipt) else WebhookReceipt.model_validate(request)
    payload_json = _json(model.payload)
    body_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    event_key = model.provider_event_id.strip() or f"body:{body_hash}"
    event_id, now = uuid.uuid4().hex, int(time.time())
    status = "received" if model.signature_valid else "rejected"
    with _connect(root) as db:
        inserted = db.execute(
            """INSERT INTO autopilot_webhook_events
            (id,provider,provider_event_key,body_sha256,signature_valid,status,payload_json,received_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(provider,provider_event_key) DO NOTHING RETURNING *""",
            (event_id, model.provider, event_key, body_hash, int(model.signature_valid), status, payload_json, now),
        ).fetchone()
        if inserted:
            return dict(inserted), True
        existing = db.execute(
            "SELECT * FROM autopilot_webhook_events WHERE provider=? AND provider_event_key=?",
            (model.provider, event_key),
        ).fetchone()
    return dict(existing), False


def record_provider_cost(root: Path, request: ProviderCostCreate | dict[str, Any]) -> tuple[dict[str, Any], bool]:
    model = request if isinstance(request, ProviderCostCreate) else ProviderCostCreate.model_validate(request)
    cost_id, now = uuid.uuid4().hex, int(time.time())
    with _connect(root) as db:
        inserted = db.execute(
            """INSERT INTO autopilot_provider_cost_events
            (id,customer_id,workflow_step_id,provider,operation,idempotency_key,quantity,estimated_cost,currency,metadata_json,occurred_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(customer_id,provider,idempotency_key) DO NOTHING RETURNING *""",
            (cost_id, model.customer_id, model.workflow_step_id or None, model.provider, model.operation, model.idempotency_key, model.quantity, model.estimated_cost, model.currency.upper(), _json(model.metadata), now),
        ).fetchone()
        if inserted:
            return dict(inserted), True
        existing = db.execute(
            "SELECT * FROM autopilot_provider_cost_events WHERE customer_id=? AND provider=? AND idempotency_key=?",
            (model.customer_id, model.provider, model.idempotency_key),
        ).fetchone()
    return dict(existing), False

