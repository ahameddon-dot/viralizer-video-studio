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
        self.assertIn("Growth Autopilot", self.page)

    def test_presents_all_eight_agents(self):
        for agent in range(1, 9):
            self.assertIn(f"'A{agent}'", self.page)

    def test_is_clearly_a_safe_review_build(self):
        self.assertIn("Stakeholder review build", self.page)
        self.assertIn("Demo data", self.page)
        self.assertIn("API integrations off", self.page)
        self.assertIn("No automated spending", self.page)

    def test_exact_content_approval_is_explicit(self):
        self.assertIn('id="exactCheck"', self.page)
        self.assertIn("I approve this exact asset, caption, hashtags, destination, and schedule.", self.page)
        self.assertIn("This approval will be invalidated", self.page)

    def test_does_not_embed_the_legacy_or_v3_ui(self):
        self.assertNotIn("creatorthon-v3", self.page)
        self.assertNotIn("Turn hot topics into", self.page)


if __name__ == "__main__":
    unittest.main()
