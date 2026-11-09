import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutopilotUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")

    def test_customer_flow_exposes_three_autopilot_stages(self):
        self.assertIn('id="autopilotBrand"', self.page)
        self.assertIn('id="autopilotOpportunities"', self.page)
        self.assertIn('id="autopilotConcepts"', self.page)
        self.assertIn("Turn your brand into ranked content opportunities", self.page)
        self.assertIn("Five opportunities", self.page)
        self.assertIn("Three distinct concepts are saved before production", self.page)

    def test_brand_confirmation_is_mandatory_in_browser_contract(self):
        self.assertIn('id="autopilotBrandConfirmed"', self.page)
        self.assertIn("Confirm the exact brand profile before opportunity ranking.", self.page)
        self.assertIn("confirmed:$('#autopilotBrandConfirmed').checked", self.page)

    def test_ui_calls_only_local_autopilot_endpoints(self):
        self.assertIn("api('/api/autopilot/brand-profile'", self.page)
        self.assertIn("api('/api/autopilot/opportunities?limit=5'", self.page)
        self.assertIn("api('/api/autopilot/opportunities/rank'", self.page)
        self.assertIn("api('/api/autopilot/concepts/generate'", self.page)
        self.assertNotIn("api('https://", self.page)

    def test_selected_concept_enters_existing_review_first_flow(self):
        self.assertIn("async function useAutopilotConcept(conceptId)", self.page)
        self.assertIn("/api/autopilot/workflows/start/", self.page)
        self.assertIn("autopilot_concept_id:concept.id", self.page)
        self.assertIn("selectTopic(selected)", self.page)
        self.assertIn("Use this exact concept", self.page)

    def test_completed_autopilot_video_requires_exact_approval(self):
        self.assertIn("function approveAutopilotCompletedVideo()", self.page)
        self.assertIn("/api/autopilot/assets/from-project", self.page)
        self.assertIn("/api/autopilot/publications/approve", self.page)
        self.assertIn("I approve this exact asset, caption, hashtags, destination, and immediate schedule.", self.page)
        self.assertIn("Approve exact content & queue", self.page)

    def test_growth_dashboard_separates_measurement_sources(self):
        self.assertIn('id="autopilotGrowth"', self.page)
        self.assertIn("/api/autopilot/growth-dashboard", self.page)
        self.assertIn("GA4", self.page)
        self.assertIn("Shopify", self.page)
        self.assertIn("Paid promotion is advisory only", self.page)

    def test_notifications_and_recommendation_feedback_are_customer_actions(self):
        self.assertIn('id="autopilotNotifications"', self.page)
        self.assertIn("/api/autopilot/notifications", self.page)
        self.assertIn("data-recommendation-action", self.page)
        self.assertIn("Accept recommendation", self.page)
        self.assertIn("Dismiss", self.page)


if __name__ == "__main__":
    unittest.main()
