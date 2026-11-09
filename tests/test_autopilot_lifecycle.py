import os
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import generate_concepts, rank_opportunities, save_brand_profile
from autopilot_lifecycle import (
    approve_and_queue_publication,
    create_asset_version,
    list_asset_versions,
    list_publications,
    record_metric_snapshot,
    start_content_workflow,
)
from autopilot_publishing import FakePublishingAdapter, submit_publication
from creatorthon_store import _connect


class AutopilotLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()
        save_brand_profile(self.root, "customer-1", {
            "customer_type": "creator", "voice": ["clear"], "audiences": ["creators"],
            "goals": ["grow reach"], "confirmed": True,
        })
        opportunity = rank_opportunities(self.root, "customer-1", {
            "topics": [{"topic": "Creator video workflows", "category": "Technology", "viral_score": 88}], "limit": 5,
        })[0]
        self.concept = generate_concepts(self.root, "customer-1", {"opportunity_id": opportunity["id"]})[0]
        self.run = start_content_workflow(self.root, "customer-1", self.concept["id"])

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def asset(self):
        return create_asset_version(self.root, "customer-1", {
            "workflow_run_id": self.run["id"], "concept_id": self.concept["id"],
            "media_url": "/api/media/final.mp4", "media_sha256": "a" * 64,
            "duration_seconds": 15, "aspect_ratio": "9:16", "caption": "Exact caption",
            "title": "Exact title", "hashtags": ["#viralizer"],
        })

    def test_asset_is_immutable_version_and_customer_scoped(self):
        first = self.asset()
        second = self.asset()
        self.assertEqual(1, first["version"])
        self.assertEqual(2, second["version"])
        self.assertEqual("superseded", list_asset_versions(self.root, "customer-1")[-1]["status"])
        self.assertEqual([], list_asset_versions(self.root, "customer-2"))

    def test_required_qc_blocks_invalid_asset(self):
        with self.assertRaises(ValueError):
            create_asset_version(self.root, "customer-1", {
                "workflow_run_id": self.run["id"], "concept_id": self.concept["id"],
                "media_url": "/bad.mp4", "media_sha256": "b" * 64,
                "duration_seconds": 30, "aspect_ratio": "16:9",
            })

    def test_exact_approval_creates_one_provider_neutral_publication(self):
        asset = self.asset()
        result = approve_and_queue_publication(self.root, "customer-1", "owner@example.com", {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "youtube-account-1", "caption": "Exact caption",
            "title": "Exact title", "hashtags": ["#viralizer"], "scheduled_at": 0,
        })
        self.assertEqual("approved", result["approval"]["status"])
        self.assertEqual("post_for_me", result["publication"]["provider"])
        self.assertEqual("publishing", result["workflow_step"]["agent_type"])
        self.assertEqual(1, len(list_publications(self.root, "customer-1")))
        self.assertEqual([], list_publications(self.root, "customer-2"))

    def test_metrics_store_deltas_and_schedule_three_hours(self):
        asset = self.asset()
        result = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "youtube-1", "caption": "Caption",
        })
        publication_id = result["publication"]["id"]
        with _connect(self.root) as db:
            db.execute("UPDATE autopilot_publications SET status='published' WHERE id=?", (publication_id,))
        first = record_metric_snapshot(self.root, "customer-1", {
            "publication_id": publication_id, "captured_at": 1000,
            "metrics": {"views": 100, "likes": 10}, "unavailable": ["shares"],
        })
        second = record_metric_snapshot(self.root, "customer-1", {
            "publication_id": publication_id, "captured_at": 2000,
            "metrics": {"views": 160, "likes": 14}, "unavailable": ["shares"],
        })
        self.assertIn('"views":60', second["deltas_json"])
        self.assertIn("shares", first["unavailable_json"])
        publication = list_publications(self.root, "customer-1")[0]
        self.assertEqual(12800, publication["next_metrics_at"])

    def test_fake_provider_submits_approved_publication_once(self):
        asset = self.asset()
        approved = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "youtube-1", "caption": "Caption",
        })
        adapter = FakePublishingAdapter()
        published = asyncio.run(submit_publication(
            self.root, "customer-1", approved["publication"]["id"], adapter,
        ))
        replay = asyncio.run(submit_publication(
            self.root, "customer-1", approved["publication"]["id"], adapter,
        ))
        self.assertEqual("published", published["status"])
        self.assertEqual(published["id"], replay["id"])
        self.assertEqual(1, len(adapter.calls))
        self.assertGreater(published["next_metrics_at"], published["published_at"])


if __name__ == "__main__":
    unittest.main()
