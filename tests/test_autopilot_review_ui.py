import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutopilotReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "static" / "autopilot-review.html").read_text(encoding="utf-8")
        cls.product = (ROOT / "static" / "autopilot-product.js").read_text(encoding="utf-8")
        cls.chat_avatar = (ROOT / "static" / "autopilot-chat-avatar.js").read_text(encoding="utf-8")
        cls.chat_page = (ROOT / "static" / "autopilot-chat.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_has_a_dedicated_route_and_file(self):
        self.assertIn('@app.get("/autopilot-review")', self.app)
        self.assertIn('"autopilot-review.html"', self.app)

    def test_chat_storyboard_uses_private_avatar_and_hides_only_duplicate_actions(self):
        self.assertIn("Use your own photo or avatar", self.chat_avatar)
        self.assertIn("/api/autopilot/user-photos", self.chat_avatar)
        self.assertIn("body.user_photo_id=photoId", self.chat_avatar)
        self.assertIn("removeDuplicateActions", self.chat_avatar)
        self.assertIn("laterOutput", self.chat_avatar)
        self.assertIn("autopilot-chat-avatar.js", self.chat_page)
        self.assertIn("user_photo_id=payload.user_photo_id", self.app)

    def test_manual_direction_wrapper_has_its_own_scope_safe_mode_reader(self):
        self.assertIn("(()=>{const directionMode=()=>document.querySelector", self.product)
        self.assertIn("AI Growth Assistant", self.page)

    def test_exposes_a_simple_customer_experience_not_agent_internals(self):
        for label in ("Today", "Content", "Results", "Brand", "Connections"):
            self.assertIn(label, self.page)
        for agent in ("Trend Scout", "Opportunity Analyst", "Creative Director", "Video Producer"):
            self.assertIn(agent, self.page)
        self.assertIn("Create this video", self.page)
        self.assertIn("See 2 other ideas", self.page)
        self.assertNotIn("Workflow runs", self.page)
        self.assertNotIn("Run queued work", self.page)

    def test_first_time_onboarding_builds_the_personalization_profile(self):
        for copy in ("Step 1 of 3", "Individual business", "Creator", "Teach the AI about your brand", "Your AI team is ready to learn", "Find my topics"):
            self.assertIn(copy, self.page)
        self.assertIn("/api/autopilot/brand-profile", self.page)
        self.assertIn("Never publish without exact-content approval.", self.page)

    def test_is_clearly_a_safe_review_build(self):
        self.assertIn("PixVerse is not called", self.page)
        self.assertIn("Exact-content approval is always required before publishing.", self.page)
        self.assertIn("I approve this exact content", self.page)
        self.assertIn("SIMULATED DATA — NOT SOCIAL PERFORMANCE", self.page)
        self.assertIn("It will not contact a social network", self.page)
        self.assertIn("Demo values are excluded from real performance claims", self.product)

    def test_flywheel_uses_existing_topic_and_autopilot_endpoints(self):
        self.assertIn("/api/autopilot/topics/refresh", self.page)
        self.assertIn("/api/autopilot/concepts/generate", self.page)
        self.assertIn("/api/autopilot/workflows/start/", self.page)
        self.assertIn("/api/autopilot/publications/approve", self.page)
        self.assertIn("/api/autopilot/demo/publications/", self.page)
        self.assertIn("/api/autopilot/growth-dashboard", self.page)
        self.assertIn("autopilot-product.js", self.page)

    def test_demo_preserves_confirmed_profile_and_personalizes_fallback(self):
        self.assertIn("profile = get_brand_profile(ROOT, customer_id)", self.app)
        self.assertIn("AI-powered kitchen tools", self.app)
        self.assertIn("Food + Tech", self.app)

    def test_does_not_embed_the_legacy_or_v3_ui(self):
        self.assertNotIn("creatorthon-v3", self.page)
        self.assertNotIn("Turn hot topics into", self.page)

    def test_boss_demo_assembles_real_pixverse_video_before_approval(self):
        self.assertIn("Create final 15-second video", self.product)
        self.assertIn("/finalize", self.product)
        self.assertIn("REAL PIXVERSE VIDEO", self.product)
        self.assertIn("I approve this exact content", self.product)
        self.assertIn("/api/autopilot/publications/approve", self.product)
        self.assertIn("/submit", self.product)
        self.assertNotIn("/api/autopilot/demo/publications/", self.product)

    def test_finalizer_requires_all_variable_length_pixverse_scenes(self):
        self.assertIn('@app.post("/api/autopilot/concepts/{concept_id}/finalize")', self.app)
        self.assertIn("must contain between 1 and 12 five-second scenes", self.app)
        self.assertIn("for scene_index in range(len(storyboard))", self.app)
        self.assertIn("was edited after its image was made", self.app)
        self.assertIn("is not a completed PixVerse clip", self.app)
        self.assertIn('"provider": "pixverse", "scene_job_ids": job_ids', self.app)
        self.assertIn('f"/api/finished-video/{filename}"', self.app)
        self.assertIn('methods=["GET", "HEAD"]', self.app)
        finished_route = self.app.split('@app.api_route("/api/finished-video/{filename}"', 1)[1][:500]
        self.assertIn('(?:hybrid|autopilot)', finished_route)
        self.assertIn('autopilot_recovery', self.app)
        self.assertIn("async def _ensure_autopilot_finished_video", self.app)
        self.assertIn("for scene_index in range(len(storyboard))", self.app)
        self.assertIn("1 <= len(storyboard) <= 12", self.app)
        self.assertIn("Waiting for Instagram or YouTube to confirm", self.product)

    def test_chat_final_video_includes_speech_branding_and_tracking(self):
        chat = (ROOT / "static" / "autopilot-chat.js").read_text(encoding="utf-8")
        self.assertIn('overlay_text="#Viralizer.ai"', self.app)
        self.assertIn('narration, "coral"', self.app)
        self.assertIn('hashtags=["#Viralizer.ai"]', self.app)
        self.assertIn("Do you want me to track this post?", chat)
        self.assertIn("[3,6,12,24]", chat)
        self.assertIn("/track", chat)

    def test_missing_animation_job_is_reported_as_recoverable(self):
        status_route = self.app.split(
            '@app.get("/api/autopilot/concepts/{concept_id}/animations/{scene_index}/status")', 1
        )[1][:1800]
        self.assertIn('"status": "not_started"', status_route)
        self.assertIn('"recoverable": True', status_route)
        self.assertNotIn('raise HTTPException(404, "PixVerse animation job was not found.")', status_route)

    def test_verified_relay_can_stream_only_the_customers_autopilot_video(self):
        self.assertIn('request.url.path.startswith("/api/finished-video/viralizer-autopilot-")', self.app)
        finished_route = self.app.split('@app.api_route("/api/finished-video/{filename}"', 1)[1][:1800]
        self.assertIn('_provider_relay_request_is_authorized(request)', finished_route)
        self.assertIn('WHERE customer_id=? AND media_url LIKE ?', finished_route)
        self.assertIn('raise HTTPException(404, "Finished video not found.")', finished_route)

    def test_demo_completion_is_forbidden_for_real_social_destinations(self):
        self.assertIn('publication.get("destination_id") != "demo-social-account"', self.app)
        self.assertIn("Demo completion cannot modify a real social publication.", self.app)

    def test_direct_post_for_me_path_uploads_local_video_first(self):
        self.assertIn("LocalMediaPostForMeAdapter(ROOT)", self.app)
        self.assertIn("path = await _ensure_autopilot_finished_video(match.group(1))", self.app)


if __name__ == "__main__":
    unittest.main()
