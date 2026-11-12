import asyncio
import os
import tempfile
import time
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import generate_concepts, rank_opportunities, save_brand_profile
from autopilot_lifecycle import approve_and_queue_publication, create_asset_version, start_content_workflow
from autopilot_operations import list_action_required, list_notifications, retry_action, scheduler_tick, worker_tick
from autopilot_store import claim_due_steps
from creatorthon_store import _connect


class AutopilotOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()
        save_brand_profile(self.root, "customer-1", {"customer_type": "creator", "voice": ["clear"], "confirmed": True})
        opportunity = rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Creator growth", "viral_score": 90}]})[0]
        concept = generate_concepts(self.root, "customer-1", {"opportunity_id": opportunity["id"]})[0]
        self.run = start_content_workflow(self.root, "customer-1", concept["id"])
        self.asset = create_asset_version(self.root, "customer-1", {
            "workflow_run_id": self.run["id"], "concept_id": concept["id"], "media_url": "/video.mp4",
            "media_sha256": "c" * 64, "duration_seconds": 15, "aspect_ratio": "9:16",
        })

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def approve(self, scheduled_at=0):
        return approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": self.asset["id"],
            "destination_id": "youtube-1", "caption": "Approved", "scheduled_at": scheduled_at,
        })

    def test_future_publication_is_not_claimed_early(self):
        self.approve(int(time.time()) + 3600)
        self.assertEqual([], claim_due_steps(self.root, "worker", limit=10))

    def test_fake_worker_publishes_once_and_notifies_customer(self):
        approved = self.approve()
        result = asyncio.run(worker_tick(self.root, "worker", mode="fake"))
        replay = asyncio.run(worker_tick(self.root, "worker", mode="fake"))
        self.assertEqual(1, result["succeeded"])
        self.assertEqual(0, replay["claimed"])
        with _connect(self.root) as db:
            publication = db.execute("SELECT * FROM autopilot_publications WHERE id=?", (approved["publication"]["id"],)).fetchone()
        self.assertEqual("published", dict(publication)["status"])
        provenance = json.loads(dict(publication)["result_json"])
        self.assertTrue(provenance["is_simulated"])
        self.assertEqual("fake", provenance["provider_mode"])
        self.assertEqual(1, len(list_notifications(self.root, "customer-1")))
        self.assertEqual([], list_notifications(self.root, "customer-2"))

    def test_scheduler_enqueues_due_monitoring_and_worker_creates_insight(self):
        approved = self.approve()
        asyncio.run(worker_tick(self.root, "publisher", mode="fake"))
        with _connect(self.root) as db:
            db.execute("UPDATE autopilot_publications SET next_metrics_at=? WHERE id=?", (1, approved["publication"]["id"]))
        first = scheduler_tick(self.root, now=10800)
        duplicate = scheduler_tick(self.root, now=10800)
        monitored = asyncio.run(worker_tick(self.root, "monitor", mode="fake"))
        self.assertEqual(1, first["monitoring_enqueued"])
        self.assertEqual(0, duplicate["monitoring_enqueued"])
        self.assertEqual(1, monitored["succeeded"])
        with _connect(self.root) as db:
            snapshots = db.execute("SELECT COUNT(*) AS n FROM autopilot_metric_snapshots").fetchone()
            snapshot = db.execute("SELECT raw_json FROM autopilot_metric_snapshots LIMIT 1").fetchone()
            recommendations = db.execute("SELECT COUNT(*) AS n FROM autopilot_recommendations").fetchone()
        self.assertEqual(1, dict(snapshots)["n"])
        provenance = json.loads(dict(snapshot)["raw_json"])
        self.assertTrue(provenance["is_simulated"])
        self.assertEqual("synthetic", provenance["data_source"])
        self.assertEqual(1, dict(recommendations)["n"])

    def test_dead_letter_is_visible_and_admin_retry_resets_it(self):
        approved = self.approve()
        with _connect(self.root) as db:
            db.execute("UPDATE autopilot_workflow_steps SET status='dead_letter',attempt=3,error_json=? WHERE customer_id=?", ('{"message":"failed"}', "customer-1"))
        action = list_action_required(self.root)
        self.assertEqual(1, len(action["steps"]))
        self.assertTrue(retry_action(self.root, "step", action["steps"][0]["id"]))
        with _connect(self.root) as db:
            step = db.execute("SELECT status,attempt FROM autopilot_workflow_steps WHERE id=?", (action["steps"][0]["id"],)).fetchone()
        self.assertEqual("queued", dict(step)["status"])
        self.assertEqual(0, dict(step)["attempt"])


if __name__ == "__main__":
    unittest.main()
