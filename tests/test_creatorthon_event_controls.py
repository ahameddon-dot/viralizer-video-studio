import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from creatorthon_store import (
    accept_event_generation,
    claim_event_seat,
    generation_entitlement,
    release_event_generation,
    reserve_event_generation,
)


class CreatorthonEventControlTests(unittest.TestCase):
    def test_only_configured_emails_have_unlimited_creatorthon_access(self):
        with patch.dict(os.environ, {"CREATORTHON_UNLIMITED_EMAILS": ""}, clear=False):
            self.assertTrue(app._unlimited_creatorthon_user({"email": " AHAMED.DON@GMAIL.COM "}))
            self.assertTrue(app._unlimited_creatorthon_user({"email": "yusufiid@gmail.com"}))
            self.assertFalse(app._unlimited_creatorthon_user({"email": "other@example.com"}))

    def test_environment_can_add_an_unlimited_email(self):
        with patch.dict(os.environ, {"CREATORTHON_UNLIMITED_EMAILS": "owner@example.com"}, clear=False):
            self.assertTrue(app._unlimited_creatorthon_user({"email": "OWNER@example.com"}))

    def test_event_capacity_is_shared_and_atomic_in_store(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"APP_DATA_DIR": directory, "CREATORTHON_EVENT_KEY": "test-event"},
            clear=False,
        ):
            root = Path(directory)
            claim_event_seat(root, "one", 2)
            claim_event_seat(root, "two", 2)
            claim_event_seat(root, "one", 2)
            with self.assertRaisesRegex(RuntimeError, "50-user"):
                claim_event_seat(root, "three", 2)

    def test_generation_is_released_before_acceptance_and_locked_after(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"APP_DATA_DIR": directory, "CREATORTHON_EVENT_KEY": "generation-test"},
            clear=False,
        ):
            root = Path(directory)
            self.assertTrue(reserve_event_generation(root, "user", "project-a", "pixverse")["allowed"])
            self.assertFalse(reserve_event_generation(root, "user", "project-b", "pixverse")["allowed"])
            release_event_generation(root, "user", "project-a")
            self.assertTrue(reserve_event_generation(root, "user", "project-b", "pixverse")["allowed"])
            accept_event_generation(root, "user", "project-b", "pixverse", "job-1")
            self.assertEqual(generation_entitlement(root, "user")["generation_status"], "accepted")
            self.assertFalse(reserve_event_generation(root, "user", "project-c", "pixverse")["allowed"])

    def test_non_english_topics_are_excluded(self):
        self.assertTrue(app._english_topic({"topic": "PlayStation 5 creator trends", "language": "en"}))
        self.assertFalse(app._english_topic({"topic": "விளையாட்டு செய்திகள்"}))
        self.assertFalse(app._english_topic({"topic": "English title", "language": "fr"}))

    def test_public_project_never_exposes_private_prompt(self):
        result = app._public_project({
            "id": "p1",
            "topic": {"topic": "PlayStation 5"},
            "prompt": {"text": "SECRET DETAILED PRODUCTION PROMPT", "concept": "Console reveal"},
        })
        self.assertEqual(result["prompt"]["text"], "Console reveal")
        self.assertNotIn("SECRET", str(result))

    def test_nested_report_values_are_accumulated_without_video_outline(self):
        report = {
            "topicAnalysis": [
                {"key": "marketMetrics", "data": {"Viral Topic Rank": "#17", "Total Audience": "44.0M", "Est. Remaining Views": "29.9M"}},
                {"key": "Audience Detected", "data": "A tech-savvy gamer aged 18-35."},
                {"key": "Creator Insight", "data": {"Themes": "Vloggers (68%), Games (56%)"}},
            ]
        }
        values = app._report_values(report)
        self.assertEqual(values["audience detected"], "A tech-savvy gamer aged 18-35.")
        self.assertEqual(values["viral topic rank"], "#17")
        self.assertIn("creator insight", values)

    def test_rich_report_sections_prefer_real_insights_over_placeholders(self):
        report = {
            "suggestedAudience": [
                {"sections": [{"text": "Audience Insight", "type": "BOLD"}]},
                {"sections": [{"text": "Audience insight is currently not available for this topic.", "type": "NORMAL"}]},
                {"sections": [{"text": "Creator Insight", "type": "BOLD"}]},
                {"sections": [{"text": "Creator insight is currently not available for this topic.", "type": "NORMAL"}]},
            ],
            "marketResearch": [
                {"sections": [{"text": "Audience Insight", "type": "BOLD"}]},
                {"sections": [{"text": "A fashion-forward person aged 18-35 who values sustainability.", "type": "NORMAL"}]},
                {"sections": [{"text": "Creator Insight", "type": "BOLD"}]},
                {"sections": [{"text": "Themes: Fashion (50%), News (50%)", "type": "NORMAL"}]},
                {"sections": [{"text": "Countries: United States (45%), Italy (9%)", "type": "NORMAL"}]},
            ],
        }
        self.assertEqual(
            app._report_insight(report, "Audience Insight"),
            "A fashion-forward person aged 18-35 who values sustainability.",
        )
        self.assertIn("Themes: Fashion", app._report_insight(report, "Creator Insight"))
        self.assertNotIn("not available", app._report_insight(report, "Creator Insight"))
        self.assertEqual(app._report_insight({"audienceInsight": "Direct insight"}, "Audience Insight"), "Direct insight")

    def test_report_hashtags_are_cleaned_for_display(self):
        report = {
            "topicAnalysis": [
                {"key": "hashtags", "data": ["#StellaMcCartney", "Sustainable fashion", "#Spring2027"]}
            ]
        }
        self.assertEqual(
            app._report_hashtags(report, {}),
            ["#StellaMcCartney", "#SustainableFashion", "#Spring2027"],
        )


if __name__ == "__main__":
    unittest.main()
