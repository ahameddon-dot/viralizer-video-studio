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

    def test_is_an_agent_control_center_not_a_marketing_dashboard(self):
        self.assertIn("Agent Control Center", self.page)
        self.assertIn("Workflow runs", self.page)
        self.assertIn("Run queued work", self.page)
        self.assertNotIn("Revenue influenced", self.page)

    def test_is_clearly_a_safe_review_build(self):
        self.assertIn("SAFE / PROVIDER-FREE", self.page)
        self.assertIn("Provider calls disabled", self.page)
        self.assertIn("external_calls", (ROOT / "autopilot_operations.py").read_text(encoding="utf-8"))

    def test_human_decision_gates_are_connected_to_real_endpoints(self):
        self.assertIn("Human decision required", self.page)
        self.assertIn("/api/autopilot/control/runs/${state.selected}/select/${type}", self.page)
        self.assertIn("/api/autopilot/control/tick", self.page)

    def test_does_not_embed_the_legacy_or_v3_ui(self):
        self.assertNotIn("creatorthon-v3", self.page)
        self.assertNotIn("Turn hot topics into", self.page)


if __name__ == "__main__":
    unittest.main()
