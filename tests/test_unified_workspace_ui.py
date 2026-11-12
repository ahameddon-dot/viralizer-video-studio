import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UnifiedWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.page = (ROOT / "static" / "autopilot-workspace.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "static" / "autopilot-workspace-live.js").read_text(encoding="utf-8")

    def test_separate_workspace_route_preserves_existing_product(self):
        self.assertIn('@app.get("/autopilot-workspace")', self.app)
        self.assertIn('"autopilot-workspace.html"', self.app)
        self.assertIn("LIVE UNIFIED WORKSPACE", self.page)
        self.assertIn("provider costs and publishing require approval", self.page)

    def test_single_journey_replaces_customer_facing_modes(self):
        for step in ("Choose topic", "Create", "Produce", "Approve", "Learn"):
            self.assertIn(step, self.page)
        self.assertNotIn("Chat Mode", self.page)
        self.assertNotIn("Hybrid Mode", self.page)
        self.assertNotIn("UI Mode", self.page)

    def test_contextual_assistant_covers_each_stage(self):
        for context in ("Topic advisor", "Creative editor", "Production helper", "Approval guide", "Growth analyst"):
            self.assertIn(context, self.script)
        self.assertIn("Ask Viralizer", self.page)
        self.assertIn("Tool actions are audited", self.page)
        self.assertIn("/api/conversations/", self.script)

    def test_real_workflow_is_approval_and_provenance_protected(self):
        self.assertIn("I approve this exact content", self.page)
        self.assertIn("/api/autopilot/publications/approve", self.script)
        self.assertIn("/submit", self.script)
        self.assertIn("SIMULATED DATA — NOT SOCIAL PERFORMANCE", self.script)
        self.assertIn("/api/autopilot/concepts/", self.script)
        self.assertNotIn("demo/publications", self.script)

    def test_confirmed_profile_survives_reload(self):
        self.assertIn("state.profile?.status === 'confirmed'", self.script)
        self.assertIn("state.profile?.confirmed_at", self.script)

    def test_concept_generation_uses_supported_platform(self):
        self.assertIn("platform: 'instagram'", self.script)
        self.assertNotIn("platform: 'instagram_reels'", self.script)

    def test_keyframes_require_visible_review_before_animation(self):
        self.assertIn('id="productionKeyframes"', self.page)
        self.assertIn('id="approveKeyframes"', self.page)
        self.assertLess(self.page.index('id="keyframeReview"'), self.page.index('id="screen-produce"'))
        self.assertIn("Generate three keyframe images", self.page)
        self.assertIn("renderProductionKeyframes", self.script)
        self.assertIn("if (!state.keyframesApproved)", self.script)
        self.assertIn("data-regenerate-keyframe", self.script)

    def test_keyframe_generation_has_a_visible_wait_state(self):
        self.assertIn('id="imageGenerationStatus"', self.page)
        self.assertIn('id="imageElapsed"', self.page)
        self.assertIn("Estimated total time", self.page)
        self.assertIn("startImageTimer", self.script)
        self.assertIn("Typical time per image", self.script)
        self.assertIn("Your three images are already ready below.", self.script)

    def test_user_photo_can_drive_private_identity_generation(self):
        self.assertIn('id="userPhotoInput"', self.page)
        self.assertIn('id="useUserPhoto"', self.page)
        self.assertIn("permission to use this photo", self.page)
        self.assertIn("/api/autopilot/user-photos", self.script)
        self.assertIn("user_photo_id", self.script)
        self.assertIn("USER PHOTO IDENTITY LOCK", self.app)

    def test_video_production_has_elapsed_time_and_scene_status(self):
        self.assertIn('id="productionElapsed"', self.page)
        self.assertIn('id="productionSceneStrip"', self.page)
        self.assertIn("ESTIMATED TOTAL", self.page)
        self.assertIn("startProductionTimer", self.script)
        self.assertIn("stopProductionTimer", self.script)


if __name__ == "__main__":
    unittest.main()
