"""Operational scheduler, worker dispatch, notifications, audit, and webhook processing."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any

from autopilot_growth import create_recommendation, due_publications, reconcile_publication
from autopilot_lifecycle import record_metric_snapshot
from autopilot_providers import PostForMeAdapter
from autopilot_publishing import FakePublishingAdapter, submit_publication
from autopilot_store import claim_due_steps, enqueue_workflow_step, finish_workflow_step
from creatorthon_store import _connect


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def notify(root: Path, customer_id: str, notification_type: str, title: str, message: str, *, entity_type: str = "", entity_id: str = "", action_url: str = "") -> dict[str, Any]:
    now, notification_id = int(time.time()), uuid.uuid4().hex
    with _connect(root) as db:
        row = db.execute(
            """INSERT INTO autopilot_notifications
            (id,customer_id,notification_type,title,message,action_url,entity_type,entity_id,created_at)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(customer_id,notification_type,entity_type,entity_id)
            DO UPDATE SET title=excluded.title,message=excluded.message,action_url=excluded.action_url,created_at=excluded.created_at RETURNING *""",
            (notification_id, customer_id, notification_type, title, message, action_url, entity_type, entity_id, now),
        ).fetchone()
    return dict(row)


def audit(root: Path, customer_id: str, event_type: str, entity_type: str, entity_id: str, detail: dict[str, Any] | None = None, actor_id: str = "", correlation_id: str = "") -> dict[str, Any]:
    event_id, now = uuid.uuid4().hex, int(time.time())
    with _connect(root) as db:
        row = db.execute(
            """INSERT INTO autopilot_audit_events
            (id,customer_id,actor_id,event_type,entity_type,entity_id,correlation_id,detail_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?) RETURNING *""",
            (event_id, customer_id, actor_id, event_type, entity_type, entity_id, correlation_id, _json(detail or {}), now),
        ).fetchone()
    return dict(row)


def list_notifications(root: Path, customer_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM autopilot_notifications WHERE customer_id=? AND dismissed_at=0 ORDER BY created_at DESC LIMIT ?",
            (customer_id, max(1, min(200, int(limit)))),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_notification(root: Path, customer_id: str, notification_id: str, dismiss: bool = False) -> bool:
    column, now = ("dismissed_at" if dismiss else "read_at"), int(time.time())
    with _connect(root) as db:
        row = db.execute(f"UPDATE autopilot_notifications SET {column}=? WHERE id=? AND customer_id=? RETURNING id", (now, notification_id, customer_id)).fetchone()
    return bool(row)


def scheduler_tick(root: Path, now: int | None = None) -> dict[str, int]:
    moment, enqueued = int(now if now is not None else time.time()), 0
    for publication in due_publications(root, moment):
        bucket = moment // 10_800
        _, created = enqueue_workflow_step(root, {
            "customer_id": publication["customer_id"], "run_id": publication["workflow_run_id"],
            "agent_type": "growth_monitoring", "idempotency_key": f"metrics:{publication['id']}:{bucket}",
            "input": {"publication_id": publication["id"], "due_at": publication["next_metrics_at"]}, "max_attempts": 5,
        })
        enqueued += int(created)
    return {"monitoring_enqueued": enqueued}


def process_webhook_inbox(root: Path, limit: int = 100) -> dict[str, int]:
    processed, failed = 0, 0
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM autopilot_webhook_events WHERE status='received' AND signature_valid=1 ORDER BY received_at,id LIMIT ?",
            (max(1, min(500, int(limit))),),
        ).fetchall()
    for row in rows:
        event = dict(row)
        try:
            payload = json.loads(event["payload_json"])
            if event["provider"] == "post_for_me":
                data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                provider_post_id = str(data.get("social_post_id") or data.get("post_id") or data.get("id") or "")
                if provider_post_id:
                    with _connect(root) as db:
                        publication = db.execute("SELECT customer_id FROM autopilot_publications WHERE provider_post_id=?", (provider_post_id,)).fetchone()
                    if publication:
                        reconcile_publication(root, dict(publication)["customer_id"], provider_post_id, data)
            with _connect(root) as db:
                db.execute("UPDATE autopilot_webhook_events SET status='processed',processed_at=? WHERE id=?", (int(time.time()), event["id"]))
            processed += 1
        except Exception as exc:
            with _connect(root) as db:
                db.execute("UPDATE autopilot_webhook_events SET status='failed',error_json=? WHERE id=?", (_json({"message": str(exc)[:500]}), event["id"]))
            failed += 1
    return {"processed": processed, "failed": failed}


async def execute_step(root: Path, step: dict[str, Any], mode: str = "disabled") -> dict[str, Any]:
    customer_id, agent_type = step["customer_id"], step["agent_type"]
    inputs = json.loads(step.get("input_json") or "{}")
    if agent_type == "trend_discovery":
        objective = " ".join(str(inputs.get("objective") or "").split())
        supplied = [" ".join(str(item).split()) for item in inputs.get("seed_topics", []) if str(item).strip()]
        titles = supplied or [objective, f"How {objective} changes customer decisions", f"Common mistakes with {objective}", f"A practical guide to {objective}", f"What leaders misunderstand about {objective}"]
        topics = [{"title": title, "category": "customer_signal", "discovery_heat": "WATCH", "recommended_format": "15-second vertical explainer", "source_type": "customer_supplied" if supplied else "local_hypothesis"} for title in titles[:10]]
        enqueue_workflow_step(root, {"customer_id": customer_id, "run_id": step["run_id"], "agent_type": "opportunity_ranking", "idempotency_key": f"{step['run_id']}:opportunity_ranking", "input": {**inputs, "topics": topics}})
        return {"topics": topics, "count": len(topics), "provenance": "customer_supplied" if supplied else "local_hypothesis", "external_calls": 0}
    if agent_type == "opportunity_ranking":
        from autopilot_intelligence import rank_opportunities
        from autopilot_orchestrator import wait_for_user
        opportunities = rank_opportunities(root, customer_id, {"topics": inputs.get("topics") or [], "limit": 5})
        wait_for_user(root, customer_id, step["run_id"], "opportunity_selection", {"opportunity_ids": [item["id"] for item in opportunities]})
        return {"opportunities": opportunities, "count": len(opportunities), "model": "autopilot-opportunity-v1"}
    if agent_type == "creative_direction":
        from autopilot_intelligence import generate_concepts
        from autopilot_orchestrator import wait_for_user
        concepts = generate_concepts(root, customer_id, {"opportunity_id": inputs["opportunity_id"], "platform": inputs.get("platform", "youtube_shorts"), "goal": inputs.get("goal", "")})
        wait_for_user(root, customer_id, step["run_id"], "concept_selection", {"concept_ids": [item["id"] for item in concepts]})
        return {"concepts": concepts, "count": len(concepts), "version": "autopilot-concept-v1"}
    if agent_type == "production_planning":
        from autopilot_orchestrator import wait_for_user
        plan = {"concept_id": inputs["concept_id"], "provider": "pixverse", "duration_seconds": 15, "aspect_ratio": "9:16", "provider_calls_enabled": False, "next_action": "Connect PixVerse or attach an approved local asset."}
        wait_for_user(root, customer_id, step["run_id"], "production_provider", plan)
        return plan
    if agent_type == "publishing":
        with _connect(root) as db:
            publication = db.execute("SELECT id FROM autopilot_publications WHERE approval_id=? AND customer_id=?", (inputs.get("approval_id"), customer_id)).fetchone()
        if not publication:
            raise ValueError("Queued publication record was not found.")
        if mode == "fake":
            adapter = FakePublishingAdapter()
        elif mode == "live" and os.getenv("AUTOPILOT_PROVIDER_CALLS_ENABLED", "").lower() in {"1", "true", "yes"}:
            adapter = PostForMeAdapter()
        else:
            raise RuntimeError("Provider execution is disabled.")
        result = await submit_publication(root, customer_id, dict(publication)["id"], adapter)
        persisted = json.loads(result.get("result_json") or "{}")
        simulated = bool(persisted.get("is_simulated"))
        label = "Simulated publication" if simulated else "Publication"
        notify(root, customer_id, "publication_status", f"{label} updated", f"{label} is {result['status']}.", entity_type="publication", entity_id=result["id"], action_url="/autopilot/growth")
        audit(root, customer_id, "publication.submitted", "publication", result["id"], {"status": result["status"], "provider": result["provider"], "is_simulated": simulated, "data_source": persisted.get("data_source", "unknown")}, correlation_id=step["id"])
        return {"publication_id": result["id"], "status": result["status"], "is_simulated": simulated, "data_source": persisted.get("data_source", "unknown")}
    if agent_type == "growth_monitoring":
        publication_id = str(inputs.get("publication_id") or "")
        if mode != "fake":
            raise RuntimeError("Metrics provider execution is disabled.")
        with _connect(root) as db:
            count = db.execute("SELECT COUNT(*) AS n FROM autopilot_metric_snapshots WHERE publication_id=?", (publication_id,)).fetchone()
        sequence = int(dict(count)["n"]) + 1
        snapshot = record_metric_snapshot(root, customer_id, {"publication_id": publication_id, "metrics": {"views": sequence * 100, "likes": sequence * 7, "comments": sequence * 2}, "unavailable": ["shares"], "raw": {"provider": "fake", "data_source": "synthetic", "provider_mode": "fake", "is_simulated": True, "label": "Simulated metrics — not social performance"}})
        recommendation = create_recommendation(root, customer_id, publication_id)
        notify(root, customer_id, "growth_update", "New growth insight", recommendation["recommendation"], entity_type="publication", entity_id=publication_id, action_url="/autopilot/growth")
        return {"snapshot_id": snapshot["id"], "recommendation_id": recommendation["id"]}
    raise ValueError(f"Unsupported workflow agent type: {agent_type}")


async def worker_tick(root: Path, worker_id: str, mode: str = "disabled", limit: int = 10, customer_id: str = "") -> dict[str, int]:
    claimed = claim_due_steps(root, worker_id, limit=limit, lease_seconds=300, customer_id=customer_id)
    succeeded, failed = 0, 0
    for step in claimed:
        try:
            output = await execute_step(root, step, mode)
            finish_workflow_step(root, step["customer_id"], step["id"], output=output)
            succeeded += 1
        except Exception as exc:
            finish_workflow_step(root, step["customer_id"], step["id"], error={"type": type(exc).__name__, "message": str(exc)[:500]}, retry_delay=min(3600, 30 * (2 ** max(0, int(step["attempt"]) - 1))))
            failed += 1
    return {"claimed": len(claimed), "succeeded": succeeded, "failed": failed}


def operations_status(root: Path) -> dict[str, Any]:
    with _connect(root) as db:
        step_counts = {str(dict(row)["status"]): int(dict(row)["n"]) for row in db.execute("SELECT status,COUNT(*) AS n FROM autopilot_workflow_steps GROUP BY status").fetchall()}
        webhook_counts = {str(dict(row)["status"]): int(dict(row)["n"]) for row in db.execute("SELECT status,COUNT(*) AS n FROM autopilot_webhook_events GROUP BY status").fetchall()}
        due = int(dict(db.execute("SELECT COUNT(*) AS n FROM autopilot_publications WHERE status='published' AND next_metrics_at>0 AND next_metrics_at<=?", (int(time.time()),)).fetchone())["n"])
    return {"workflow_steps": step_counts, "webhooks": webhook_counts, "metrics_due": due,
            "provider_mode": os.getenv("AUTOPILOT_PROVIDER_MODE", "disabled"), "worker_id": f"{socket.gethostname()}:{os.getpid()}"}


def list_action_required(root: Path, limit: int = 100) -> dict[str, list[dict[str, Any]]]:
    with _connect(root) as db:
        steps = db.execute(
            "SELECT * FROM autopilot_workflow_steps WHERE status IN ('failed','dead_letter') ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(500, int(limit))),),
        ).fetchall()
        webhooks = db.execute(
            "SELECT id,provider,provider_event_key,status,error_json,received_at,processed_at FROM autopilot_webhook_events WHERE status='failed' ORDER BY received_at DESC LIMIT ?",
            (max(1, min(500, int(limit))),),
        ).fetchall()
    return {"steps": [dict(row) for row in steps], "webhooks": [dict(row) for row in webhooks]}


def retry_action(root: Path, entity_type: str, entity_id: str) -> bool:
    now = int(time.time())
    with _connect(root) as db:
        if entity_type == "step":
            row = db.execute(
                """UPDATE autopilot_workflow_steps SET status='queued',attempt=0,next_attempt_at=?,lease_until=0,worker_id='',error_json='{}',updated_at=?
                WHERE id=? AND status IN ('failed','dead_letter') RETURNING id""",
                (now, now, entity_id),
            ).fetchone()
        elif entity_type == "webhook":
            row = db.execute(
                "UPDATE autopilot_webhook_events SET status='received',error_json='{}',processed_at=0 WHERE id=? AND status='failed' RETURNING id",
                (entity_id,),
            ).fetchone()
        else:
            raise ValueError("Retry entity type must be step or webhook.")
    return bool(row)


async def run_worker(root: Path) -> None:
    worker_id = f"autopilot:{socket.gethostname()}:{os.getpid()}"
    mode = os.getenv("AUTOPILOT_PROVIDER_MODE", "disabled").lower()
    interval = max(2, int(os.getenv("AUTOPILOT_WORKER_INTERVAL_SECONDS", "10")))
    while True:
        scheduler_tick(root)
        process_webhook_inbox(root)
        if mode in {"fake", "live"}:
            await worker_tick(root, worker_id, mode=mode)
        await asyncio.sleep(interval)
