"""Approval-enforced publishing service with a provider-free test adapter."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol

from autopilot_contracts import PublicationPayload
from autopilot_providers import sanitize_publication_result
from autopilot_store import authorize_publication_step
from creatorthon_store import _connect


class PublishingAdapter(Protocol):
    async def publish(self, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...


class FakePublishingAdapter:
    """Local-only adapter used to prove workflow safety without provider calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def publish(self, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        call = {"publication": publication, "idempotency_key": idempotency_key}
        self.calls.append(call)
        return {
            "status": "published", "provider": "fake", "provider_post_id": idempotency_key,
            "data_source": "synthetic", "provider_mode": "fake", "is_simulated": True,
        }


def queue_approved_publication(root: Path, customer_id: str, run_id: str, approval_id: str, payload: PublicationPayload | dict[str, Any]) -> tuple[dict[str, Any], bool]:
    return authorize_publication_step(root, customer_id, run_id, approval_id, payload)


async def submit_publication(root: Path, customer_id: str, publication_id: str, adapter: PublishingAdapter) -> dict[str, Any]:
    """Submit one already-approved publication through an injected adapter."""
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute(
            "SELECT * FROM autopilot_publications WHERE id=? AND customer_id=?",
            (publication_id, customer_id),
        ).fetchone()
        if not row:
            raise ValueError("Publication was not found for this customer.")
        publication = dict(row)
        stored_result: dict[str, Any] = {}
        try:
            stored_result = json.loads(publication.get("result_json") or "{}")
        except (TypeError, ValueError):
            stored_result = {}
        contaminated_fake_result = (
            publication["status"] == "published"
            and publication.get("provider") == "post_for_me"
            and publication.get("destination_id") != "demo-social-account"
            and stored_result.get("provider") == "fake"
        )
        if contaminated_fake_result:
            publication["status"] = "failed"
            db.execute(
                "UPDATE autopilot_publications SET status='failed',published_at=0,next_metrics_at=0,error_json=?,updated_at=? WHERE id=? AND customer_id=?",
                (json.dumps({"message": "A simulated result was rejected for this real publication. Retry through Post for Me."}, separators=(",", ":")),
                 now, publication_id, customer_id),
            )
        elif publication["status"] in {"submitting", "processing", "published"}:
            return publication
        if publication["status"] not in {"queued", "scheduled", "failed"}:
            raise ValueError("Publication is not ready for submission.")
        if int(publication["scheduled_at"] or 0) > now:
            raise ValueError("Publication is scheduled for a future time.")
        approval = db.execute(
            "SELECT status FROM autopilot_content_approvals WHERE id=? AND customer_id=?",
            (publication["approval_id"], customer_id),
        ).fetchone()
        if not approval or dict(approval)["status"] != "consumed":
            raise PermissionError("Publication does not have a consumed exact-content approval.")
        if isinstance(adapter, FakePublishingAdapter) and publication.get("destination_id") != "demo-social-account":
            raise PermissionError("Simulated publishing is not allowed for a real social account.")
        asset = db.execute(
            "SELECT media_url,media_sha256 FROM autopilot_asset_versions WHERE id=? AND customer_id=? AND status='ready_review'",
            (publication["asset_version_id"], customer_id),
        ).fetchone()
        if not asset:
            raise PermissionError("Approved immutable asset is no longer available.")
        db.execute(
            "UPDATE autopilot_publications SET status='submitting',updated_at=? WHERE id=? AND customer_id=?",
            (now, publication_id, customer_id),
        )
    idempotency_key = f"publication:{publication_id}"
    try:
        provider_payload = json.loads(publication["payload_json"])
        provider_payload["media_url"] = dict(asset)["media_url"]
        result = sanitize_publication_result(await adapter.publish(provider_payload, idempotency_key))
        if not result.get("provider"):
            raise ValueError("Publishing provider returned no safe provider identifier.")
        if not result.get("status"):
            raise ValueError("Publishing provider returned no safe status.")
        if (result.get("status") == "published" and result.get("provider") != "fake"
                and not any(result.get(key) for key in ("provider_post_id", "native_post_id", "native_url"))):
            raise ValueError("Publishing provider returned no verifiable post identifier.")
    except Exception as exc:
        with _connect(root) as db:
            db.execute(
                "UPDATE autopilot_publications SET status='failed',error_json=?,updated_at=? WHERE id=? AND customer_id=?",
                (json.dumps({"message": str(exc)[:500]}, separators=(",", ":")), int(time.time()), publication_id, customer_id),
            )
        raise
    status = "published" if result.get("status") == "published" else "processing"
    completed_at = int(time.time())
    with _connect(root) as db:
        updated = db.execute(
            """UPDATE autopilot_publications SET status=?,provider_post_id=?,native_post_id=?,native_url=?,result_json=?,
            published_at=?,next_metrics_at=?,error_json='{}',updated_at=? WHERE id=? AND customer_id=? RETURNING *""",
            (status, str(result.get("provider_post_id") or ""), str(result.get("native_post_id") or ""),
             str(result.get("native_url") or ""), json.dumps(result, sort_keys=True, separators=(",", ":")),
             completed_at if status == "published" else 0, completed_at + 10_800 if status == "published" else 0,
             completed_at, publication_id, customer_id),
        ).fetchone()
    return dict(updated)

