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

    def test_chat_has_separate_route_and_mode_switching(self):
        self.assertIn('@app.get("/autopilot-chat")', self.app)
        self.assertIn('autopilot-chat.html', self.app)
        self.assertIn('/autopilot-review?mode=hybrid', self.chat_html)
        self.assertIn('/autopilot-review', self.chat_html)

    def test_chat_uses_real_persistence_and_policy_controlled_ai(self):
        self.assertIn("/api/conversations", self.chat_js)
        self.assertIn("/api/conversation-tools", self.chat_js)
        self.assertIn("Approval-safe AI workspace", self.chat_html)
        self.assertIn("Provider costs and publishing require approval", self.chat_html)
        self.assertIn("/respond", self.chat_js)
        self.assertNotIn("tool-executions/propose", self.chat_js)

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
