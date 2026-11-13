"""Local lifecycle services for production review, exact approval, and growth monitoring.

Provider submission is intentionally absent. These functions make the product state durable
before PixVerse, Post for Me, GA4, or Shopify credentials are connected.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from autopilot_contracts import AssetVersionCreate, MetricSnapshotCreate, PublicationApprovalRequest
from autopilot_publishing import queue_approved_publication
from autopilot_store import create_content_approval, create_workflow_run, publication_payload_hash
from creatorthon_store import _connect


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def start_content_workflow(root: Path, customer_id: str, concept_id: str) -> dict[str, Any]:
    if not concept_id.strip():
        raise ValueError("concept_id is required")
    with _connect(root) as db:
        concept = db.execute(
            "SELECT id,opportunity_id FROM autopilot_creative_concepts WHERE id=? AND customer_id=?",
            (concept_id, customer_id),
        ).fetchone()
    if not concept:
        raise ValueError("Concept was not found for this customer.")
    return create_workflow_run(root, {
        "customer_id": customer_id,
        "workflow_type": "content_growth",
        "input": {"concept_id": concept_id, "opportunity_id": dict(concept)["opportunity_id"]},
    })


def create_asset_version(root: Path, customer_id: str, request: AssetVersionCreate | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, AssetVersionCreate) else AssetVersionCreate.model_validate(request)
    now = int(time.time())
    if not model.media_url.startswith(("https://", "/")):
        raise ValueError("Media URL must be HTTPS or an application-relative path.")
    qc = dict(model.qc)
    qc.setdefault("duration_valid", 14 <= model.duration_seconds <= 16)
    qc.setdefault("aspect_ratio_valid", model.aspect_ratio == "9:16")
    qc.setdefault("media_available", True)
    if not all(qc.get(key) is True for key in ("duration_valid", "aspect_ratio_valid", "media_available")):
        raise ValueError("Asset failed required duration, aspect-ratio, or availability checks.")
    with _connect(root) as db:
        run = db.execute(
            "SELECT id FROM autopilot_workflow_runs WHERE id=? AND customer_id=?",
            (model.workflow_run_id, customer_id),
        ).fetchone()
        concept = db.execute(
            "SELECT id FROM autopilot_creative_concepts WHERE id=? AND customer_id=?",
            (model.concept_id, customer_id),
        ).fetchone()
        if not run or not concept:
            raise ValueError("Workflow or concept was not found for this customer.")
        current = db.execute(
            "SELECT COALESCE(MAX(version),0) AS version FROM autopilot_asset_versions WHERE customer_id=? AND concept_id=?",
            (customer_id, model.concept_id),
        ).fetchone()
        version = int(dict(current)["version"]) + 1
        db.execute(
            "UPDATE autopilot_asset_versions SET status='superseded' WHERE customer_id=? AND concept_id=? AND status='ready_review'",
            (customer_id, model.concept_id),
        )
        asset_id = uuid.uuid4().hex
        row = db.execute(
            """INSERT INTO autopilot_asset_versions
            (id,customer_id,workflow_run_id,concept_id,version,media_url,media_sha256,duration_seconds,aspect_ratio,caption,title,hashtags_json,qc_json,status,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'ready_review',?) RETURNING *""",
            (asset_id, customer_id, model.workflow_run_id, model.concept_id, version, model.media_url,
             model.media_sha256, str(model.duration_seconds), model.aspect_ratio, model.caption, model.title,
             _json(model.hashtags), _json(qc), now),
        ).fetchone()
        db.execute(
            "UPDATE autopilot_workflow_runs SET status='waiting_user',output_json=?,updated_at=? WHERE id=? AND customer_id=?",
            (_json({"asset_version_id": asset_id, "stage": "publication_approval"}), now, model.workflow_run_id, customer_id),
        )
    return dict(row)


def list_asset_versions(root: Path, customer_id: str, workflow_run_id: str = "") -> list[dict[str, Any]]:
    query = "SELECT * FROM autopilot_asset_versions WHERE customer_id=?"
    params: list[Any] = [customer_id]
    if workflow_run_id:
        query += " AND workflow_run_id=?"
        params.append(workflow_run_id)
    query += " ORDER BY created_at DESC,version DESC"
    with _connect(root) as db:
        rows = db.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def get_active_project(root: Path, customer_id: str) -> dict[str, Any] | None:
    """Restore the latest customer-owned creative state after refresh or login."""
    with _connect(root) as db:
        opportunity = db.execute(
            """SELECT o.* FROM autopilot_opportunities o
            WHERE o.customer_id=? AND EXISTS (
              SELECT 1 FROM autopilot_creative_concepts c
              WHERE c.opportunity_id=o.id AND c.customer_id=o.customer_id
            ) ORDER BY o.updated_at DESC LIMIT 1""",
            (customer_id,),
        ).fetchone()
        if not opportunity:
            return None
        opportunity_item = dict(opportunity)
        concept_rows = db.execute(
            "SELECT * FROM autopilot_creative_concepts WHERE customer_id=? AND opportunity_id=? ORDER BY variant_number",
            (customer_id, opportunity_item["id"]),
        ).fetchall()
        concepts = [dict(row) for row in concept_rows]
        concept_ids = {item["id"] for item in concepts}
        asset = db.execute(
            """SELECT a.* FROM autopilot_asset_versions a
            JOIN autopilot_creative_concepts c ON c.id=a.concept_id AND c.customer_id=a.customer_id
            WHERE a.customer_id=? AND c.opportunity_id=? AND a.status='ready_review'
            ORDER BY a.created_at DESC,a.version DESC LIMIT 1""",
            (customer_id, opportunity_item["id"]),
        ).fetchone()
        workflow = None
        selected_concept_id = str(dict(asset).get("concept_id") or "") if asset else ""
        if asset:
            workflow_row = db.execute(
                "SELECT * FROM autopilot_workflow_runs WHERE id=? AND customer_id=?",
                (dict(asset)["workflow_run_id"], customer_id),
            ).fetchone()
            workflow = dict(workflow_row) if workflow_row else None
        if not workflow:
            for row in db.execute(
                "SELECT * FROM autopilot_workflow_runs WHERE customer_id=? AND workflow_type='content_growth' ORDER BY updated_at DESC,id DESC",
                (customer_id,),
            ).fetchall():
                candidate = dict(row)
                try:
                    input_data = json.loads(candidate.get("input_json") or "{}")
                except (TypeError, ValueError):
                    input_data = {}
                if input_data.get("concept_id") in concept_ids:
                    workflow = candidate
                    selected_concept_id = str(input_data.get("concept_id") or "")
                    break
        selected_concept = next((item for item in concepts if item["id"] == selected_concept_id), concepts[0])
    for item in concepts:
        try:
            item["content"] = json.loads(item.pop("content_json") or "{}")
        except (TypeError, ValueError):
            item["content"] = {}
    for key, default in (("components_json", {}), ("source_json", {})):
        try:
            opportunity_item[key.removesuffix("_json")] = json.loads(opportunity_item.pop(key) or "{}")
        except (TypeError, ValueError):
            opportunity_item[key.removesuffix("_json")] = default
    asset_item = dict(asset) if asset else None
    if asset_item:
        for key, default in (("hashtags_json", []), ("qc_json", {})):
            try:
                asset_item[key.removesuffix("_json")] = json.loads(asset_item.get(key) or json.dumps(default))
            except (TypeError, ValueError):
                asset_item[key.removesuffix("_json")] = default
    return {
        "opportunity": opportunity_item,
        "concepts": concepts,
        "concept": next(item for item in concepts if item["id"] == selected_concept["id"]),
        "workflow": workflow,
        "asset": asset_item,
    }


def list_autopilot_projects(root: Path, customer_id: str) -> list[dict[str, Any]]:
    """Return distinct customer-owned video projects, including published history.

    Asset retries can create more than one database row for the same final media.  The
    Projects screen should show the video once while retaining all of its publication
    destinations and statuses.
    """
    with _connect(root) as db:
        rows = db.execute(
            """SELECT a.*,c.opportunity_id,o.title AS opportunity_title,
                      o.category AS opportunity_category
               FROM autopilot_asset_versions a
               JOIN autopilot_creative_concepts c
                 ON c.id=a.concept_id AND c.customer_id=a.customer_id
               JOIN autopilot_opportunities o
                 ON o.id=c.opportunity_id AND o.customer_id=a.customer_id
              WHERE a.customer_id=?
              ORDER BY a.created_at DESC,a.version DESC""",
            (customer_id,),
        ).fetchall()
        publications = db.execute(
            """SELECT * FROM autopilot_publications
               WHERE customer_id=? ORDER BY created_at DESC""",
            (customer_id,),
        ).fetchall()

    publications_by_asset: dict[str, list[dict[str, Any]]] = {}
    for row in publications:
        item = dict(row)
        # Provider payloads are already sanitized before persistence. Keep the project
        # inventory deliberately small and never expose raw provider response JSON.
        publications_by_asset.setdefault(str(item.get("asset_version_id") or ""), []).append({
            "id": item.get("id"),
            "destination_id": item.get("destination_id"),
            "provider": item.get("provider"),
            "status": item.get("status"),
            "provider_post_id": item.get("provider_post_id"),
            "published_at": item.get("published_at"),
            "created_at": item.get("created_at"),
        })

    projects: list[dict[str, Any]] = []
    projects_by_media: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        media_key = str(item.get("media_sha256") or item.get("media_url") or item.get("id"))
        asset_publications = publications_by_asset.get(str(item["id"]), [])
        if media_key in projects_by_media:
            project = projects_by_media[media_key]
            project["publications"].extend(asset_publications)
            project["published_count"] = sum(
                1 for publication in project["publications"] if publication.get("status") == "published"
            )
            continue
        project = {
            "id": item["id"],
            "asset_id": item["id"],
            "concept_id": item["concept_id"],
            "opportunity_id": item["opportunity_id"],
            "workflow_run_id": item["workflow_run_id"],
            "title": item.get("title") or item.get("opportunity_title") or "Untitled video",
            "opportunity_title": item.get("opportunity_title"),
            "category": item.get("opportunity_category"),
            "media_url": item.get("media_url"),
            "status": item.get("status"),
            "version": item.get("version"),
            "created_at": item.get("created_at"),
            "publications": asset_publications,
            "published_count": sum(1 for publication in asset_publications if publication.get("status") == "published"),
        }
        projects_by_media[media_key] = project
        projects.append(project)
    for project in projects:
        published = [item for item in project["publications"] if item.get("status") == "published"]
        project["is_published"] = bool(published)
        project["published_destinations"] = sorted({
            str(item.get("destination_id") or "") for item in published if item.get("destination_id")
        })
        # Kept for API compatibility. This is a unique destination count, not a count
        # of provider retries or historical publication rows.
        project["published_count"] = len(project["published_destinations"])
    return projects


def approve_and_queue_publication(root: Path, customer_id: str, approved_by: str, request: PublicationApprovalRequest | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, PublicationApprovalRequest) else PublicationApprovalRequest.model_validate(request)
    with _connect(root) as db:
        asset = db.execute(
            "SELECT * FROM autopilot_asset_versions WHERE id=? AND customer_id=? AND workflow_run_id=? AND status='ready_review'",
            (model.asset_version_id, customer_id, model.workflow_run_id),
        ).fetchone()
    if not asset:
        raise ValueError("Approval-ready asset was not found for this customer and workflow.")
    asset_item = dict(asset)
    payload = {
        "asset_version_id": model.asset_version_id,
        "asset_sha256": asset_item["media_sha256"],
        "caption": model.caption,
        "title": model.title,
        "hashtags": model.hashtags,
        "destination_id": model.destination_id,
        "scheduled_at": model.scheduled_at,
    }
    payload_hash, _ = publication_payload_hash(payload)
    with _connect(root) as db:
        existing = db.execute(
            """SELECT p.*,a.id AS existing_approval_id,a.status AS approval_status
            FROM autopilot_publications p
            JOIN autopilot_content_approvals a ON a.id=p.approval_id
            WHERE p.customer_id=? AND p.workflow_run_id=? AND a.payload_hash=?
            ORDER BY p.created_at DESC LIMIT 1""",
            (customer_id, model.workflow_run_id, payload_hash),
        ).fetchone()
        if existing:
            publication = dict(existing)
            approval = db.execute(
                "SELECT * FROM autopilot_content_approvals WHERE id=? AND customer_id=?",
                (publication["approval_id"], customer_id),
            ).fetchone()
            step = db.execute(
                "SELECT * FROM autopilot_workflow_steps WHERE customer_id=? AND idempotency_key LIKE ? ORDER BY created_at DESC LIMIT 1",
                (customer_id, f"publish:{publication['approval_id']}:%"),
            ).fetchone()
            return {"approval": dict(approval), "publication": publication,
                    "workflow_step": dict(step) if step else {}, "created": False}
    approval = create_content_approval(root, {
        "customer_id": customer_id, "approved_by": approved_by, "publication": payload,
    })
    step, created = queue_approved_publication(root, customer_id, model.workflow_run_id, approval["id"], payload)
    now = int(time.time())
    publication_id = uuid.uuid4().hex
    with _connect(root) as db:
        inserted = db.execute(
            """INSERT INTO autopilot_publications
            (id,customer_id,workflow_run_id,approval_id,asset_version_id,destination_id,provider,status,scheduled_at,payload_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,'post_for_me',?,?,?,?,?)
            ON CONFLICT(customer_id,approval_id,destination_id) DO NOTHING RETURNING *""",
            (publication_id, customer_id, model.workflow_run_id, approval["id"], model.asset_version_id,
             model.destination_id, "scheduled" if model.scheduled_at > now else "queued", model.scheduled_at,
             _json(payload), now, now),
        ).fetchone()
        if not inserted:
            inserted = db.execute(
                "SELECT * FROM autopilot_publications WHERE customer_id=? AND approval_id=? AND destination_id=?",
                (customer_id, approval["id"], model.destination_id),
            ).fetchone()
        db.execute(
            "UPDATE autopilot_workflow_runs SET status='running',output_json=?,updated_at=? WHERE id=? AND customer_id=?",
            (_json({"publication_id": dict(inserted)["id"], "stage": "publication_queued"}), now, model.workflow_run_id, customer_id),
        )
    return {"approval": approval, "publication": dict(inserted), "workflow_step": step, "created": created}


def list_publications(root: Path, customer_id: str) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM autopilot_publications WHERE customer_id=? ORDER BY created_at DESC",
            (customer_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def record_metric_snapshot(root: Path, customer_id: str, request: MetricSnapshotCreate | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, MetricSnapshotCreate) else MetricSnapshotCreate.model_validate(request)
    captured_at = model.captured_at or int(time.time())
    normalized = {key: value for key, value in model.metrics.items() if value is not None}
    with _connect(root) as db:
        publication = db.execute(
            "SELECT id FROM autopilot_publications WHERE id=? AND customer_id=? AND status='published'",
            (model.publication_id, customer_id),
        ).fetchone()
        if not publication:
            raise ValueError("Published item was not found for this customer.")
        prior = db.execute(
            "SELECT metrics_json FROM autopilot_metric_snapshots WHERE publication_id=? ORDER BY captured_at DESC LIMIT 1",
            (model.publication_id,),
        ).fetchone()
        previous = json.loads(dict(prior)["metrics_json"]) if prior else {}
        deltas = {key: value - previous[key] for key, value in normalized.items() if isinstance(value, (int, float)) and isinstance(previous.get(key), (int, float))}
        snapshot_id = uuid.uuid4().hex
        row = db.execute(
            """INSERT INTO autopilot_metric_snapshots
            (id,customer_id,publication_id,captured_at,metrics_json,deltas_json,unavailable_json,raw_json)
            VALUES(?,?,?,?,?,?,?,?) RETURNING *""",
            (snapshot_id, customer_id, model.publication_id, captured_at, _json(normalized), _json(deltas),
             _json(model.unavailable), _json(model.raw)),
        ).fetchone()
        db.execute(
            "UPDATE autopilot_publications SET next_metrics_at=?,updated_at=? WHERE id=? AND customer_id=?",
            (captured_at + 10_800, int(time.time()), model.publication_id, customer_id),
        )
    return dict(row)
