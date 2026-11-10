"""Provider-neutral connection, monitoring, recommendation, and attribution services."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from autopilot_contracts import AttributionEventCreate, ProviderConnectionUpsert
from creatorthon_store import _connect


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _public_connection(row: Any) -> dict[str, Any]:
    item = dict(row)
    item.pop("secret_reference", None)
    item["capabilities"] = json.loads(item.pop("capabilities_json") or "[]")
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    return item


def save_connection(root: Path, customer_id: str, request: ProviderConnectionUpsert | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, ProviderConnectionUpsert) else ProviderConnectionUpsert.model_validate(request)
    if model.secret_reference and not model.secret_reference.startswith(("vault://", "kms://", "env://")):
        raise ValueError("Store only an encrypted secret reference, never a provider credential.")
    now = int(time.time())
    connection_id = uuid.uuid4().hex
    with _connect(root) as db:
        row = db.execute(
            """INSERT INTO autopilot_provider_connections
            (id,customer_id,provider,external_account_id,display_name,status,capabilities_json,secret_reference,metadata_json,connected_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(customer_id,provider,external_account_id) DO UPDATE SET
            display_name=excluded.display_name,status=excluded.status,capabilities_json=excluded.capabilities_json,
            secret_reference=CASE WHEN excluded.secret_reference='' THEN autopilot_provider_connections.secret_reference ELSE excluded.secret_reference END,
            metadata_json=excluded.metadata_json,connected_at=excluded.connected_at,updated_at=excluded.updated_at RETURNING *""",
            (connection_id, customer_id, model.provider, model.external_account_id, model.display_name, model.status,
             _json(model.capabilities), model.secret_reference, _json(model.metadata), now if model.status == "connected" else 0, now, now),
        ).fetchone()
    return _public_connection(row)


def list_connections(root: Path, customer_id: str) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM autopilot_provider_connections WHERE customer_id=? ORDER BY provider,created_at",
            (customer_id,),
        ).fetchall()
    return [_public_connection(row) for row in rows]


def due_publications(root: Path, now: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    moment = int(now if now is not None else time.time())
    with _connect(root) as db:
        rows = db.execute(
            """SELECT * FROM autopilot_publications
            WHERE status='published' AND next_metrics_at>0 AND next_metrics_at<=?
            ORDER BY next_metrics_at,id LIMIT ?""",
            (moment, max(1, min(500, int(limit)))),
        ).fetchall()
    return [dict(row) for row in rows]


def reconcile_publication(root: Path, customer_id: str, provider_post_id: str, result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status") or "processing").lower()
    normalized = {"published": "published", "failed": "failed", "cancelled": "cancelled"}.get(status, "processing")
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute(
            "SELECT * FROM autopilot_publications WHERE customer_id=? AND provider_post_id=?",
            (customer_id, provider_post_id),
        ).fetchone()
        if not row:
            raise ValueError("Publication result does not belong to this customer.")
        updated = db.execute(
            """UPDATE autopilot_publications SET status=?,native_post_id=?,native_url=?,result_json=?,
            published_at=CASE WHEN ?='published' AND published_at=0 THEN ? ELSE published_at END,
            next_metrics_at=CASE WHEN ?='published' AND next_metrics_at=0 THEN ? ELSE next_metrics_at END,
            updated_at=? WHERE id=? AND customer_id=? RETURNING *""",
            (normalized, str(result.get("native_post_id") or ""), str(result.get("native_url") or ""), _json(result),
             normalized, now, normalized, now + 10_800, now, dict(row)["id"], customer_id),
        ).fetchone()
    return dict(updated)


def create_recommendation(root: Path, customer_id: str, publication_id: str) -> dict[str, Any]:
    with _connect(root) as db:
        publication = db.execute(
            "SELECT * FROM autopilot_publications WHERE id=? AND customer_id=?",
            (publication_id, customer_id),
        ).fetchone()
        if not publication:
            raise ValueError("Publication was not found for this customer.")
        rows = db.execute(
            "SELECT metrics_json,deltas_json,captured_at FROM autopilot_metric_snapshots WHERE publication_id=? AND customer_id=? ORDER BY captured_at DESC LIMIT 2",
            (publication_id, customer_id),
        ).fetchall()
        if not rows:
            raise ValueError("At least one metrics snapshot is required.")
        latest = dict(rows[0])
        metrics, deltas = json.loads(latest["metrics_json"]), json.loads(latest["deltas_json"])
        views, engagements = float(metrics.get("views") or 0), sum(float(metrics.get(key) or 0) for key in ("likes", "comments", "shares"))
        rate = engagements / views if views else 0
        if rate >= .08:
            kind, message = "repeat_pattern", "Engagement is strong. Reuse the hook structure with a new evidence-backed topic; do not copy the wording."
        elif views and rate < .02:
            kind, message = "improve_hook", "Reach is present but engagement is weak. Test a clearer first-three-second promise before considering paid promotion."
        else:
            kind, message = "collect_more_data", "Performance evidence is still limited. Keep monitoring before changing the creative direction or recommending promotion."
        recommendation_id, now = uuid.uuid4().hex, int(time.time())
        result = db.execute(
            """INSERT INTO autopilot_recommendations
            (id,customer_id,publication_id,recommendation_type,recommendation,evidence_json,status,created_at)
            VALUES(?,?,?,?,?,?,'active',?) RETURNING *""",
            (recommendation_id, customer_id, publication_id, kind, message,
             _json({"metrics": metrics, "deltas": deltas, "engagement_rate": round(rate, 6), "paid_action": "recommendations_only"}), now),
        ).fetchone()
    return dict(result)


def save_attribution_event(root: Path, customer_id: str, request: AttributionEventCreate | dict[str, Any]) -> tuple[dict[str, Any], bool]:
    model = request if isinstance(request, AttributionEventCreate) else AttributionEventCreate.model_validate(request)
    now, event_id = int(time.time()), uuid.uuid4().hex
    with _connect(root) as db:
        if model.publication_id:
            publication = db.execute("SELECT id FROM autopilot_publications WHERE id=? AND customer_id=?", (model.publication_id, customer_id)).fetchone()
            if not publication:
                raise ValueError("Publication was not found for this customer.")
        row = db.execute(
            """INSERT INTO autopilot_attribution_events
            (id,customer_id,publication_id,provider,event_key,occurred_at,campaign_id,source,medium,content,sessions,conversions,revenue,currency,attribution_status,raw_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(customer_id,provider,event_key) DO NOTHING RETURNING *""",
            (event_id, customer_id, model.publication_id or None, model.provider, model.event_key,
             model.occurred_at or now, model.campaign_id, model.source, model.medium, model.content,
             str(model.sessions), str(model.conversions), str(model.revenue), model.currency.upper(),
             model.attribution_status, _json(model.raw), now),
        ).fetchone()
        if row:
            return dict(row), True
        existing = db.execute(
            "SELECT * FROM autopilot_attribution_events WHERE customer_id=? AND provider=? AND event_key=?",
            (customer_id, model.provider, model.event_key),
        ).fetchone()
    return dict(existing), False


def growth_dashboard(root: Path, customer_id: str) -> dict[str, Any]:
    with _connect(root) as db:
        publications = [dict(row) for row in db.execute("SELECT * FROM autopilot_publications WHERE customer_id=? ORDER BY created_at DESC LIMIT 50", (customer_id,)).fetchall()]
        recommendations = [dict(row) for row in db.execute("SELECT * FROM autopilot_recommendations WHERE customer_id=? ORDER BY created_at DESC LIMIT 50", (customer_id,)).fetchall()]
        metrics = [dict(row) for row in db.execute("SELECT * FROM autopilot_metric_snapshots WHERE customer_id=? ORDER BY captured_at DESC LIMIT 100", (customer_id,)).fetchall()]
        attribution = [dict(row) for row in db.execute("SELECT * FROM autopilot_attribution_events WHERE customer_id=? ORDER BY occurred_at DESC LIMIT 200", (customer_id,)).fetchall()]
    ga4 = {"sessions": 0.0, "conversions": 0.0, "reported_revenue": 0.0}
    shopify = {"orders": 0.0, "order_revenue": 0.0}
    unattributed_shopify = 0.0
    for event in attribution:
        if event["provider"] == "ga4":
            ga4["sessions"] += float(event["sessions"]); ga4["conversions"] += float(event["conversions"]); ga4["reported_revenue"] += float(event["revenue"])
        else:
            shopify["orders"] += float(event["conversions"]); shopify["order_revenue"] += float(event["revenue"])
            if event["attribution_status"] != "attributed": unattributed_shopify += float(event["revenue"])
    return {"connections": list_connections(root, customer_id), "publications": publications, "recommendations": recommendations, "metrics": metrics,
            "commerce": {"ga4": ga4, "shopify": shopify, "unattributed_shopify_revenue": unattributed_shopify,
                         "disclosure": "GA4 reported revenue and Shopify order revenue are shown separately and are never added together."}}


def update_recommendation(root: Path, customer_id: str, recommendation_id: str, status: str) -> dict[str, Any]:
    if status not in {"accepted", "dismissed"}:
        raise ValueError("Recommendation status must be accepted or dismissed.")
    with _connect(root) as db:
        row = db.execute(
            "UPDATE autopilot_recommendations SET status=? WHERE id=? AND customer_id=? RETURNING *",
            (status, recommendation_id, customer_id),
        ).fetchone()
    if not row:
        raise ValueError("Recommendation was not found for this customer.")
    return dict(row)
