import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutopilotReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "static" / "autopilot-review.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_has_a_dedicated_route_and_file(self):
        self.assertIn('@app.get("/autopilot-review")', self.app)
        self.assertIn('"autopilot-review.html"', self.app)
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

    def test_is_clearly_a_safe_review_build(self):
        self.assertIn("PixVerse is not called", self.page)
        self.assertIn("Exact-content approval is always required before publishing.", self.page)
        self.assertIn("I approve this exact content", self.page)
        self.assertIn("Simulated 3-hour report", self.page)
        self.assertIn("It will not contact a social network", self.page)

    def test_flywheel_uses_existing_topic_and_autopilot_endpoints(self):
        self.assertIn("/api/autopilot/topics/refresh", self.page)
        self.assertIn("/api/autopilot/concepts/generate", self.page)
        self.assertIn("/api/autopilot/workflows/start/", self.page)
        self.assertIn("/api/autopilot/publications/approve", self.page)
        self.assertIn("/api/autopilot/demo/publications/", self.page)
        self.assertIn("/api/autopilot/growth-dashboard", self.page)

    def test_does_not_embed_the_legacy_or_v3_ui(self):
        self.assertNotIn("creatorthon-v3", self.page)
        self.assertNotIn("Turn hot topics into", self.page)


if __name__ == "__main__":
    unittest.main()
