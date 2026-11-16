import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChatHybridUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.chat_html = (ROOT / "static" / "autopilot-chat.html").read_text(encoding="utf-8")
        cls.chat_js = (ROOT / "static" / "autopilot-chat.js").read_text(encoding="utf-8")
        cls.review = (ROOT / "static" / "autopilot-review.html").read_text(encoding="utf-8")
        cls.hybrid = (ROOT / "static" / "autopilot-hybrid.js").read_text(encoding="utf-8")

    def test_chat_has_separate_route_and_does_not_redirect_into_visual_mode(self):
        self.assertIn('@app.get("/autopilot-chat")', self.app)
        self.assertIn('autopilot-chat.html', self.app)
        self.assertIn('Chat Mode', self.chat_html)
        self.assertNotIn('Open visual workspace', self.chat_html)
        self.assertNotIn('Open canvas', self.chat_js)
        self.assertNotIn('/autopilot-workspace?view=', self.chat_js)

    def test_exact_publication_review_and_submit_remain_inside_chat(self):
        self.assertIn('EXACT POST APPROVAL · CHAT MODE', self.chat_js)
        self.assertIn('/api/autopilot/publications/approve', self.chat_js)
        self.assertIn('/submit', self.chat_js)
        self.assertIn('data-exact-approval', self.chat_js)
        self.assertIn('publication-card', (ROOT / "static" / "autopilot-chat.css").read_text(encoding="utf-8"))

    def test_latest_chat_stays_visible_after_media_layout_changes(self):
        self.assertIn('function keepLatestVisible(force=false)', self.chat_js)
        self.assertIn("media.addEventListener(event,()=>scrollToLatest(false)", self.chat_js)
        self.assertIn("messages.addEventListener('scroll'", self.chat_js)
        self.assertNotIn('messages.scrollTop=messages.scrollHeight', self.chat_js)

    def test_chat_uses_real_persistence_and_policy_controlled_ai(self):
        self.assertIn("/api/conversations", self.chat_js)
        self.assertIn("/api/conversation-tools", self.chat_js)
        self.assertIn("Approval-safe AI workspace", self.chat_html)
        self.assertIn("Provider costs and publishing require approval", self.chat_html)
        self.assertIn("/respond", self.chat_js)
        self.assertNotIn("tool-executions/propose", self.chat_js)

    def test_video_countdown_is_added_after_conversation_refresh(self):
        refresh = self.chat_js.index("await openConversation(currentId);if(tool==='all_animations'")
        countdown = self.chat_js.index("countdown=startCountdown('video',ids.length)")
        polling = self.chat_js.index("await waitForAnimations(conceptId,ids.length,countdown)")
        self.assertLess(refresh, countdown)
        self.assertLess(countdown, polling)
        self.assertIn("VIDEO GENERATION'} · ESTIMATED TIME LEFT", self.chat_js)
        self.assertIn("Your job is still running safely", self.chat_js)

    def test_pixverse_complete_status_renders_video_and_advances(self):
        self.assertIn("value==='completed'||value==='complete'", self.chat_js)
        self.assertIn("if(done){complete.add(scene)", self.chat_js)
        self.assertIn("All scene animations are ready. Assembling the final video", self.chat_js)

    def test_saved_animation_can_resume_after_refresh_without_new_generation(self):
        self.assertIn("function resumableProduction(rows)", self.chat_js)
        self.assertIn('data-resume-production', self.chat_js)
        self.assertIn('Resume the status check without creating or charging for another video.', self.chat_js)
        self.assertIn('await waitForAnimations(conceptId,count,countdown)', self.chat_js)

    def test_chat_has_its_own_account_and_logout_controls(self):
        self.assertIn('/api/autopilot/brand-profile', self.chat_js)
        self.assertIn('id="accountName"', self.chat_html)
        self.assertIn('href="/logout?next=/login"', self.chat_html)
        self.assertIn('id="chatLogout"', self.chat_html)

    def test_hybrid_is_loaded_without_replacing_existing_ui(self):
        self.assertIn('/static/autopilot-product.js?v=15', self.review)
        self.assertIn('/static/autopilot-hybrid.js?v=1', self.review)
        self.assertIn('/static/autopilot-hybrid.css?v=1', self.review)
        self.assertIn("document.body.appendChild(panel)", self.hybrid)

    def test_hybrid_links_project_scene_conversation_and_events(self):
        self.assertIn('/api/hybrid/projects/autopilot-concept/', self.hybrid)
        self.assertIn('/events/stream?after=0', self.hybrid)
        self.assertIn("active_scene:activeScene", self.hybrid)
        self.assertIn("active_project_context_id:project?.id", self.hybrid)
        self.assertIn("viralizer.activeProject", self.hybrid)
        self.assertNotIn("tool-executions/propose", self.hybrid)


if __name__ == "__main__":
    unittest.main()
