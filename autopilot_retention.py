"""Customer export and retention controls for Autopilot-owned records."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from creatorthon_store import _connect


CUSTOMER_TABLES = (
    "autopilot_notifications", "autopilot_audit_events", "autopilot_recommendations",
    "autopilot_metric_snapshots", "autopilot_attribution_events", "autopilot_publications",
    "autopilot_asset_versions", "autopilot_creative_concepts", "autopilot_opportunities",
    "autopilot_brand_profiles", "autopilot_provider_cost_events", "autopilot_content_approvals",
    "autopilot_workflow_steps", "autopilot_workflow_runs", "autopilot_provider_connections",
)


def _safe_rows(rows: list[Any]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row)
        item.pop("secret_reference", None)
        result.append(item)
    return result


def export_customer_data(root: Path, customer_id: str) -> dict[str, Any]:
    if not customer_id:
        raise ValueError("customer_id is required")
    export: dict[str, Any] = {"schema_version": 1, "customer_id": customer_id, "exported_at": int(time.time()), "tables": {}}
    with _connect(root) as db:
        for table in CUSTOMER_TABLES:
            rows = db.execute(f"SELECT * FROM {table} WHERE customer_id=?", (customer_id,)).fetchall()
            export["tables"][table] = _safe_rows(rows)
    return export


def deletion_preview(root: Path, customer_id: str) -> dict[str, int]:
    with _connect(root) as db:
        return {table: int(dict(db.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE customer_id=?", (customer_id,)).fetchone())["n"]) for table in CUSTOMER_TABLES}


def delete_customer_data(root: Path, customer_id: str, confirmation: str) -> dict[str, int]:
    expected = f"DELETE {customer_id}"
    if not customer_id or confirmation != expected:
        raise PermissionError(f"Exact confirmation is required: {expected}")
    counts = deletion_preview(root, customer_id)
    with _connect(root) as db:
        for table in CUSTOMER_TABLES:
            db.execute(f"DELETE FROM {table} WHERE customer_id=?", (customer_id,))
    return counts


def retention_preview(root: Path, now: int | None = None, webhook_days: int = 30, audit_days: int = 365) -> dict[str, int]:
    moment = int(now if now is not None else time.time())
    with _connect(root) as db:
        webhook_count = dict(db.execute("SELECT COUNT(*) AS n FROM autopilot_webhook_events WHERE received_at<? AND status IN ('processed','rejected')", (moment - webhook_days * 86400,)).fetchone())["n"]
        audit_count = dict(db.execute("SELECT COUNT(*) AS n FROM autopilot_audit_events WHERE created_at<?", (moment - audit_days * 86400,)).fetchone())["n"]
    return {"webhook_events": int(webhook_count), "audit_events": int(audit_count)}


def apply_retention(root: Path, confirmation: str, now: int | None = None, webhook_days: int = 30, audit_days: int = 365) -> dict[str, int]:
    if confirmation != "APPLY RETENTION":
        raise PermissionError("Exact APPLY RETENTION confirmation is required.")
    moment = int(now if now is not None else time.time())
    counts = retention_preview(root, moment, webhook_days, audit_days)
    with _connect(root) as db:
        db.execute("DELETE FROM autopilot_webhook_events WHERE received_at<? AND status IN ('processed','rejected')", (moment - webhook_days * 86400,))
        db.execute("DELETE FROM autopilot_audit_events WHERE created_at<?", (moment - audit_days * 86400,))
    return counts
