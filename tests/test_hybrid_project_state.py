import json
import os
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import generate_concepts, get_concept, rank_opportunities, save_brand_profile
from autopilot_lifecycle import approve_and_queue_publication, create_asset_version, start_content_workflow
from autopilot_publishing import FakePublishingAdapter, submit_publication
from creatorthon_store import _connect
from hybrid_project_state import RevisionConflictError, ensure_autopilot_project, get_project_context, list_project_events, revise_storyboard_scene


class HybridProjectStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()
        save_brand_profile(self.root, "customer-1", {"customer_type": "creator", "voice": ["clear"], "confirmed": True})
        opportunity = rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Luxury kitchen design", "viral_score": 91}]})[0]
        self.concept = generate_concepts(self.root, "customer-1", {"opportunity_id": opportunity["id"]})[0]

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_context_imports_existing_storyboard_once_and_is_customer_scoped(self):
        first = ensure_autopilot_project(self.root, "customer-1", self.concept["id"])
        second = ensure_autopilot_project(self.root, "customer-1", self.concept["id"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.concept["id"], first["concept_id"])
        self.assertEqual(1, first["revision"])
        self.assertEqual(3, len(first["active_storyboard"]["storyboard"]))
        with self.assertRaises(ValueError):
            get_project_context(self.root, "customer-2", first["id"])

    def test_ui_scene_revision_updates_shared_concept_and_emits_event(self):
        project = ensure_autopilot_project(self.root, "customer-1", self.concept["id"])
        result = revise_storyboard_scene(
            self.root, "customer-1", project["id"], 2, 1,
            {"keyframe_prompt": "A luxury black granite kitchen with warm architectural lighting"},
            "user_ui", "owner@example.com", "Changed scene three kitchen",
        )
        self.assertEqual(2, result["project"]["revision"])
        self.assertIn("black granite", result["project"]["active_storyboard"]["storyboard"][2]["keyframe_prompt"])
        concept = get_concept(self.root, "customer-1", self.concept["id"])
        self.assertIn("black granite", concept["content"]["storyboard"][2]["keyframe_prompt"])
        events = list_project_events(self.root, "customer-1", project["id"], after=1)
        self.assertEqual("storyboard.revision.created", events[0]["event_type"])
        self.assertEqual(2, events[0]["payload"]["revision"])

    def test_stale_revision_is_rejected_without_overwrite(self):
        project = ensure_autopilot_project(self.root, "customer-1", self.concept["id"])
        revise_storyboard_scene(self.root, "customer-1", project["id"], 0, 1, {"purpose": "new hook"}, "user_ui")
        with self.assertRaises(RevisionConflictError) as conflict:
            revise_storyboard_scene(self.root, "customer-1", project["id"], 1, 1, {"purpose": "stale write"}, "user_ui")
        self.assertEqual(2, conflict.exception.current)

    def test_storyboard_change_invalidates_unpublished_approval_and_queue(self):
        project = ensure_autopilot_project(self.root, "customer-1", self.concept["id"])
        run = start_content_workflow(self.root, "customer-1", self.concept["id"])
        asset = create_asset_version(self.root, "customer-1", {
            "workflow_run_id": run["id"], "concept_id": self.concept["id"], "media_url": "/video.mp4",
            "media_sha256": "f" * 64, "duration_seconds": 15, "aspect_ratio": "9:16",
        })
        approved = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": run["id"], "asset_version_id": asset["id"],
            "destination_id": "instagram-1", "caption": "Approved",
        })
        result = revise_storyboard_scene(self.root, "customer-1", project["id"], 0, 1, {"purpose": "revised hook"}, "user_ui")
        self.assertEqual(1, result["invalidated"]["publications"])
        self.assertEqual(1, result["invalidated"]["approvals"])
        with _connect(self.root) as db:
            publication = dict(db.execute("SELECT status FROM autopilot_publications WHERE id=?", (approved["publication"]["id"],)).fetchone())
            approval = dict(db.execute("SELECT status FROM autopilot_content_approvals WHERE id=?", (approved["approval"]["id"],)).fetchone())
        self.assertEqual("cancelled", publication["status"])
        self.assertEqual("revoked", approval["status"])

    def test_storyboard_change_preserves_already_published_history(self):
        project = ensure_autopilot_project(self.root, "customer-1", self.concept["id"])
        run = start_content_workflow(self.root, "customer-1", self.concept["id"])
        asset = create_asset_version(self.root, "customer-1", {
            "workflow_run_id": run["id"], "concept_id": self.concept["id"], "media_url": "/video.mp4",
            "media_sha256": "e" * 64, "duration_seconds": 15, "aspect_ratio": "9:16",
        })
        approved = approve_and_queue_publication(self.root, "customer-1", "owner", {
            "workflow_run_id": run["id"], "asset_version_id": asset["id"],
            "destination_id": "youtube-1", "caption": "Already published",
        })
        asyncio.run(submit_publication(self.root, "customer-1", approved["publication"]["id"], FakePublishingAdapter()))
        result = revise_storyboard_scene(self.root, "customer-1", project["id"], 0, 1, {"purpose": "next version"}, "user_ui")
        self.assertEqual(0, result["invalidated"]["publications"])
        self.assertEqual(0, result["invalidated"]["approvals"])
        with _connect(self.root) as db:
            publication = dict(db.execute("SELECT status FROM autopilot_publications WHERE id=?", (approved["publication"]["id"],)).fetchone())
            approval = dict(db.execute("SELECT status FROM autopilot_content_approvals WHERE id=?", (approved["approval"]["id"],)).fetchone())
        self.assertEqual("published", publication["status"])
        self.assertEqual("consumed", approval["status"])

    def test_scene_patch_rejects_unknown_fields(self):
        project = ensure_autopilot_project(self.root, "customer-1", self.concept["id"])
        with self.assertRaises(ValueError):
            revise_storyboard_scene(self.root, "customer-1", project["id"], 0, 1, {"customer_id": "customer-2"}, "user_ui")


class HybridRouteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app = (root / "app.py").read_text(encoding="utf-8")
        cls.ui = (root / "static" / "autopilot-product.js").read_text(encoding="utf-8")

    def test_hybrid_routes_and_stream_are_exposed(self):
        self.assertIn('/api/hybrid/projects/autopilot-concept/{concept_id}', self.app)
        self.assertIn('/storyboard/scenes/{scene_index}/revisions', self.app)
        self.assertIn('/events/stream', self.app)
        self.assertIn('text/event-stream', self.app)

    def test_existing_scene_generation_persists_manual_direction_first(self):
        self.assertIn('/api/hybrid/projects/autopilot-concept/', self.ui)
        self.assertIn('/storyboard/scenes/${body.scene_index}/revisions', self.ui)
        self.assertIn('expected_revision:project.revision', self.ui)


if __name__ == "__main__":
    unittest.main()
