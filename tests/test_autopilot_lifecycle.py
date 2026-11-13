import os
import tempfile
import unittest
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import generate_concepts, rank_opportunities, save_brand_profile
from autopilot_lifecycle import (
    approve_and_queue_publication,
    create_asset_version,
    get_active_project,
    list_asset_versions,
    list_autopilot_projects,
    list_publications,
    record_metric_snapshot,
    start_content_workflow,
)
from autopilot_publishing import FakePublishingAdapter, LocalMediaPostForMeAdapter, submit_publication
from autopilot_growth import reconcile_publication
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
            "topics": [{"topic": "Creators video workflows", "category": "Technology", "viral_score": 88}], "limit": 5,
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

    def test_active_project_restores_customer_owned_images_workflow_and_asset(self):
        workflow = start_content_workflow(self.root, "customer-1", self.concept["id"])
        asset = create_asset_version(self.root, "customer-1", {
            "workflow_run_id": workflow["id"], "concept_id": self.concept["id"],
            "media_url": "/api/media/restored.mp4", "media_sha256": "c" * 64,
            "duration_seconds": 15, "aspect_ratio": "9:16", "caption": "Saved caption",
            "title": "Saved title", "hashtags": ["#saved"],
        })
        restored = get_active_project(self.root, "customer-1")
        self.assertEqual(self.concept["id"], restored["concept"]["id"])
        self.assertEqual(workflow["id"], restored["workflow"]["id"])
        self.assertEqual(asset["id"], restored["asset"]["id"])
        self.assertEqual(["#saved"], restored["asset"]["hashtags"])
        self.assertIsNone(get_active_project(self.root, "customer-2"))

    def test_projects_inventory_keeps_published_history_and_deduplicates_media(self):
        first = self.asset()
        duplicate = self.asset()
        projects = list_autopilot_projects(self.root, "customer-1")
        self.assertEqual(1, len(projects))
        self.assertEqual(duplicate["id"], projects[0]["asset_id"])
        self.assertEqual("Exact title", projects[0]["title"])
        self.assertEqual([], list_autopilot_projects(self.root, "customer-2"))

        result = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": duplicate["id"],
            "destination_id": "instagram-1", "caption": "Exact caption",
        })
        with _connect(self.root) as db:
            db.execute("UPDATE autopilot_publications SET status='published' WHERE id=?", (result["publication"]["id"],))
        projects = list_autopilot_projects(self.root, "customer-1")
        self.assertEqual(1, projects[0]["published_count"])

        # A publication attached to an older retry version still belongs to the one
        # visible video card because both assets contain identical final media.
        with _connect(self.root) as db:
            db.execute("UPDATE autopilot_publications SET asset_version_id=? WHERE id=?", (first["id"], result["publication"]["id"]))
        projects = list_autopilot_projects(self.root, "customer-1")
        self.assertEqual(1, len(projects))
        self.assertEqual(1, projects[0]["published_count"])

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

    def test_repeated_exact_approval_reuses_publication(self):
        asset = self.asset()
        request = {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "instagram-1", "caption": "Exact caption",
            "title": "Exact title", "hashtags": ["#viralizer"], "scheduled_at": 0,
        }
        first = approve_and_queue_publication(self.root, "customer-1", "owner", request)
        second = approve_and_queue_publication(self.root, "customer-1", "owner", request)
        self.assertEqual(first["publication"]["id"], second["publication"]["id"])
        self.assertFalse(second["created"])
        self.assertEqual(1, len(list_publications(self.root, "customer-1")))

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
            "destination_id": "demo-social-account", "caption": "Caption",
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
        provenance = json.loads(published["result_json"])
        self.assertTrue(provenance["is_simulated"])
        self.assertEqual("synthetic", provenance["data_source"])

    def test_fake_provider_cannot_complete_real_social_publication(self):
        asset = self.asset()
        approved = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "instagram-1", "caption": "Caption",
        })
        with self.assertRaises(PermissionError):
            asyncio.run(submit_publication(
                self.root, "customer-1", approved["publication"]["id"], FakePublishingAdapter(),
            ))
        publication = list_publications(self.root, "customer-1")[0]
        self.assertNotEqual("published", publication["status"])
        self.assertNotIn('"provider":"fake"', publication["result_json"])

    def test_contaminated_fake_success_is_retried_through_real_provider(self):
        class RealAdapter:
            async def publish(self, publication, idempotency_key):
                return {"provider": "post_for_me", "status": "published", "provider_post_id": "post-real-1"}

        asset = self.asset()
        approved = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "instagram-1", "caption": "Caption",
        })
        publication_id = approved["publication"]["id"]
        with _connect(self.root) as db:
            db.execute(
                "UPDATE autopilot_publications SET status='published',result_json=?,published_at=1 WHERE id=?",
                ('{"provider":"fake","status":"published"}', publication_id),
            )
        repaired = asyncio.run(submit_publication(self.root, "customer-1", publication_id, RealAdapter()))
        self.assertEqual("published", repaired["status"])
        self.assertEqual("post-real-1", repaired["provider_post_id"])
        self.assertEqual("post_for_me", json.loads(repaired["result_json"])["provider"])

    def test_real_provider_cannot_claim_published_without_evidence(self):
        class EvidenceFreeAdapter:
            async def publish(self, publication, idempotency_key):
                return {"provider": "post_for_me", "status": "published"}

        asset = self.asset()
        approved = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "youtube-1", "caption": "Caption",
        })
        with self.assertRaisesRegex(ValueError, "verifiable post identifier"):
            asyncio.run(submit_publication(self.root, "customer-1", approved["publication"]["id"], EvidenceFreeAdapter()))
        self.assertEqual("failed", list_publications(self.root, "customer-1")[0]["status"])

    def test_local_video_is_uploaded_before_post_for_me_publish(self):
        class RecordingProvider:
            def __init__(self):
                self.uploaded = None
                self.published = None

            async def upload_media(self, path, content_type):
                self.uploaded = (path, content_type)
                return "https://media.postforme.test/approved.mp4"

            async def publish(self, publication, idempotency_key):
                self.published = (publication, idempotency_key)
                return {"provider": "post_for_me", "status": "published", "provider_post_id": "post-1"}

        video = b"immutable-approved-video"
        filename = "viralizer-autopilot-" + "d" * 32 + ".mp4"
        directory = self.root / "data" / "finished_videos"
        directory.mkdir(parents=True)
        (directory / filename).write_bytes(video)
        provider = RecordingProvider()
        result = asyncio.run(LocalMediaPostForMeAdapter(self.root, provider).publish({
            "media_url": f"/api/finished-video/{filename}",
            "asset_sha256": __import__("hashlib").sha256(video).hexdigest(),
            "destination_id": "instagram-1", "caption": "Caption",
        }, "publication:" + "e" * 32))
        self.assertEqual("video/mp4", provider.uploaded[1])
        self.assertEqual("https://media.postforme.test/approved.mp4", provider.published[0]["media_url"])
        self.assertEqual("post-1", result["provider_post_id"])

    def test_provider_result_secrets_are_not_persisted(self):
        class UnsafeAdapter:
            async def publish(self, publication, idempotency_key):
                return {
                    "provider": "post_for_me", "status": "published", "provider_post_id": "post-1",
                    "native_url": "https://social.test/post/1", "access_token": "secret",
                    "refresh_token": "secret", "social_accounts": [{"access_token": "nested-secret"}],
                }

        asset = self.asset()
        approved = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "instagram-1", "caption": "Caption",
        })
        published = asyncio.run(submit_publication(self.root, "customer-1", approved["publication"]["id"], UnsafeAdapter()))
        stored = json.loads(published["result_json"])
        self.assertEqual("post-1", stored["provider_post_id"])
        self.assertEqual("https://social.test/post/1", stored["native_url"])
        self.assertNotIn("access_token", stored)
        self.assertNotIn("refresh_token", stored)
        self.assertNotIn("social_accounts", stored)

    def test_provider_account_failure_is_not_reported_as_published(self):
        asset = self.asset()
        approved = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": self.run["id"], "asset_version_id": asset["id"],
            "destination_id": "instagram-1", "caption": "Caption",
        })
        publication_id = approved["publication"]["id"]
        with _connect(self.root) as db:
            db.execute(
                "UPDATE autopilot_publications SET status='processing',provider_post_id='post-1' WHERE id=?",
                (publication_id,),
            )
        failed = reconcile_publication(self.root, "customer-1", "post-1", {
            "success": False, "error": "All media failed to process",
            "platform_data": {"id": None, "url": None},
        })
        self.assertEqual("failed", failed["status"])
        self.assertIn("All media failed", failed["error_json"])


if __name__ == "__main__":
    unittest.main()
