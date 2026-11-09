import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_store import (
    authorize_publication_step,
    claim_due_steps,
    create_content_approval,
    create_workflow_run,
    enqueue_workflow_step,
    finish_workflow_step,
    get_workflow_run,
    ingest_webhook_event,
    record_provider_cost,
)


ASSET_SHA = "a" * 64


class AutopilotFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()
        self.run = create_workflow_run(self.root, {"customer_id": "customer-1", "workflow_type": "growth_autopilot"})
        self.payload = {
            "asset_version_id": "asset-v1",
            "asset_sha256": ASSET_SHA,
            "caption": "Approved caption",
            "title": "Approved title",
            "hashtags": ["viralizer"],
            "destination_id": "youtube-account-1",
            "scheduled_at": 0,
        }

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_migrations_create_foundation_and_step_idempotency(self):
        step, created = enqueue_workflow_step(self.root, {
            "customer_id": "customer-1", "run_id": self.run["id"], "agent_type": "brand_intelligence",
            "idempotency_key": "brand:1", "input": {"url": "https://example.com"},
        })
        self.assertTrue(created)
        duplicate, created = enqueue_workflow_step(self.root, {
            "customer_id": "customer-1", "run_id": self.run["id"], "agent_type": "brand_intelligence",
            "idempotency_key": "brand:1", "input": {"url": "https://changed.example"},
        })
        self.assertFalse(created)
        self.assertEqual(step["id"], duplicate["id"])

    def test_active_lease_prevents_second_worker_claim(self):
        enqueue_workflow_step(self.root, {
            "customer_id": "customer-1", "run_id": self.run["id"], "agent_type": "trend_discovery",
            "idempotency_key": "discover:1",
        })
        first = claim_due_steps(self.root, "worker-1")
        second = claim_due_steps(self.root, "worker-2")
        self.assertEqual(1, len(first))
        self.assertEqual([], second)
        self.assertEqual("worker-1", first[0]["worker_id"])

    def test_status_read_is_customer_scoped(self):
        enqueue_workflow_step(self.root, {
            "customer_id": "customer-1", "run_id": self.run["id"], "agent_type": "brand_intelligence",
            "idempotency_key": "status:1",
        })
        status = get_workflow_run(self.root, "customer-1", self.run["id"])
        self.assertEqual(self.run["id"], status["run"]["id"])
        self.assertEqual("brand_intelligence", status["steps"][0]["agent_type"])
        self.assertIsNone(get_workflow_run(self.root, "customer-2", self.run["id"]))

    def test_failure_retries_then_dead_letters(self):
        step, _ = enqueue_workflow_step(self.root, {
            "customer_id": "customer-1", "run_id": self.run["id"], "agent_type": "production",
            "idempotency_key": "production:1", "max_attempts": 2,
        })
        claimed = claim_due_steps(self.root, "worker-1")[0]
        retried = finish_workflow_step(self.root, "customer-1", claimed["id"], error={"code": "timeout"})
        self.assertEqual("retry_wait", retried["status"])
        claimed = claim_due_steps(self.root, "worker-2")[0]
        dead = finish_workflow_step(self.root, "customer-1", claimed["id"], error={"code": "timeout"})
        self.assertEqual("dead_letter", dead["status"])

    def test_exact_payload_approval_and_publish_idempotency(self):
        approval = create_content_approval(self.root, {
            "customer_id": "customer-1", "approved_by": "user-1", "publication": self.payload,
        })
        step, created = authorize_publication_step(self.root, "customer-1", self.run["id"], approval["id"], self.payload)
        self.assertTrue(created)
        duplicate, created = authorize_publication_step(self.root, "customer-1", self.run["id"], approval["id"], self.payload)
        self.assertFalse(created)
        self.assertEqual(step["id"], duplicate["id"])

    def test_any_payload_change_blocks_publication(self):
        approval = create_content_approval(self.root, {
            "customer_id": "customer-1", "approved_by": "user-1", "publication": self.payload,
        })
        changed = {**self.payload, "caption": "Changed after approval"}
        with self.assertRaises(PermissionError):
            authorize_publication_step(self.root, "customer-1", self.run["id"], approval["id"], changed)

    def test_approval_is_customer_scoped(self):
        approval = create_content_approval(self.root, {
            "customer_id": "customer-1", "approved_by": "user-1", "publication": self.payload,
        })
        with self.assertRaises(PermissionError):
            authorize_publication_step(self.root, "customer-2", self.run["id"], approval["id"], self.payload)

    def test_webhooks_are_deduplicated_and_invalid_signatures_are_rejected(self):
        event, created = ingest_webhook_event(self.root, {
            "provider": "post_for_me", "provider_event_id": "evt-1", "signature_valid": True,
            "payload": {"type": "social.post.updated"},
        })
        self.assertTrue(created)
        duplicate, created = ingest_webhook_event(self.root, {
            "provider": "post_for_me", "provider_event_id": "evt-1", "signature_valid": True,
            "payload": {"type": "different"},
        })
        self.assertFalse(created)
        self.assertEqual(event["id"], duplicate["id"])
        rejected, _ = ingest_webhook_event(self.root, {
            "provider": "post_for_me", "provider_event_id": "evt-2", "signature_valid": False,
            "payload": {"type": "social.post.updated"},
        })
        self.assertEqual("rejected", rejected["status"])

    def test_cost_events_are_idempotent(self):
        request = {
            "customer_id": "customer-1", "provider": "pixverse", "operation": "video_generation",
            "idempotency_key": "generation:1", "estimated_cost": "0.25",
        }
        first, created = record_provider_cost(self.root, request)
        self.assertTrue(created)
        duplicate, created = record_provider_cost(self.root, request)
        self.assertFalse(created)
        self.assertEqual(first["id"], duplicate["id"])


if __name__ == "__main__":
    unittest.main()

