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

    def test_saved_project_images_and_publish_retry_survive_reload(self):
        self.assertIn('/api/autopilot/projects/current', self.script)
        self.assertIn('Your saved project has been restored.', self.script)
        self.assertIn('renderProductionKeyframes()', self.script)
        self.assertIn('assetMatchesPost(asset, post)', self.script)
        self.assertIn('@app.get("/api/autopilot/projects/current")', self.app)
        self.assertIn('renderRestoredProduction()', self.script)
        self.assertIn('Saved final video restored', self.script)

    def test_projects_screen_lists_saved_customer_videos(self):
        self.assertIn('@app.get("/api/autopilot/projects")', self.app)
        self.assertIn("loadProjects()", self.script)
        self.assertIn("/api/autopilot/projects", self.script)
        self.assertIn("project-video", self.script)
        self.assertIn("prepare-publication", self.script)
        self.assertIn("Publish this video", self.script)
        self.assertIn("Every saved video and its real publishing status", self.page)

    def test_keyframes_and_identity_photos_use_durable_storage(self):
        self.assertIn('autopilot_keyframes/{customer_id}/{concept_id}/{filename}', self.app)
        self.assertIn('autopilot_user_photos/{customer_id}/{photo_id}.png', self.app)
        self.assertIn('await restore_object_file(reference_path', self.app)
        self.assertIn('await restore_object_file(user_photo_path', self.app)

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
        self.assertIn("Regenerate all three with my photo", self.script)
        self.assertIn("startImageTimer(); updateImageTimer(scene)", self.script)

    def test_video_production_has_elapsed_time_and_scene_status(self):
        self.assertIn('id="productionElapsed"', self.page)
        self.assertIn('id="productionSceneStrip"', self.page)
        self.assertIn("ESTIMATED TOTAL", self.page)
        self.assertIn("startProductionTimer", self.script)
        self.assertIn("stopProductionTimer", self.script)

    def test_topic_cards_use_one_real_image_surface(self):
        self.assertIn("topicFallbackImage", self.script)
        self.assertIn("/static/category-images/", self.script)
        self.assertNotIn('<div class="topic-top">', self.script)

    def test_login_leads_into_autopilot_onboarding(self):
        self.assertIn("Create content people stop for.", self.app)
        self.assertIn("Continue with Google", self.app)
        self.assertIn("Continue with Apple", self.app)
        self.assertIn("Continue with email", self.app)
        self.assertIn("Create account", self.app)
        self.assertIn('action="/auth/email"', self.app)
        self.assertIn('"/auth/email", "/about"', self.app)
        self.assertIn("Passwords are salted and hashed", self.app)
        self.assertIn("Sign-in could not continue.", self.app)
        self.assertIn("Email authentication rejected: reason=%s", self.app)
        self.assertIn('"/autopilot-workspace?view=today" if profile_confirmed', self.app)
        self.assertIn('"/autopilot-workspace?onboarding=1"', self.app)
        self.assertIn("forceOnboarding", self.script)

    def test_workspace_profile_menu_has_logout(self):
        self.assertIn('id="userMenuToggle"', self.page)
        self.assertIn('href="/logout?next=/login"', self.page)
        self.assertIn("aria-expanded", self.script)
        self.assertIn('LOGOUT_COOKIE = "viralizer_logged_out"', self.app)
        self.assertIn('EMAIL_AUTH_COOKIE = "viralizer_email_session"', self.app)
        self.assertIn('response.set_cookie(EMAIL_AUTH_COOKIE, token', self.app)
        self.assertIn('response.delete_cookie(EMAIL_AUTH_COOKIE', self.app)
        self.assertIn('response.delete_cookie(LOGOUT_COOKIE', self.app)
        self.assertNotIn('request.cookies.get(LOGOUT_COOKIE) == "1"', self.app)
        self.assertIn('response.set_cookie(AUTH_COOKIE, "logged-out"', self.app)

    def test_workspace_uses_consistent_svg_navigation_icons(self):
        self.assertGreaterEqual(self.page.count('<svg viewBox="0 0 24 24"'), 12)
        for legacy_icon in ("<i>⌂</i>", "<i>▣</i>", "<i>⚙</i>", ">♢</button>"):
            self.assertNotIn(legacy_icon, self.page)

    def test_topic_loading_has_large_progress_animation_and_verified_rank_fast_path(self):
        self.assertIn("topic-discovery-loader", self.script)
        self.assertIn("topicLoadingTime", self.script)
        self.assertIn("Verifying Viral Rank evidence", self.script)
        self.assertIn('source["viral_rank_source"] = "mcp_hot_topics"', self.app)


if __name__ == "__main__":
    unittest.main()
