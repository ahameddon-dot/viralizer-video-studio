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
    event_admin_state,
    grant_event_admission,
    grant_extra_generation,
    remove_event_user,
    get_workflow_state,
    release_event_generation,
    reserve_event_generation,
    save_workflow_state,
)


class CreatorthonEventControlTests(unittest.TestCase):
    def test_only_configured_emails_have_unlimited_creatorthon_access(self):
        with patch.dict(os.environ, {"CREATORTHON_UNLIMITED_EMAILS": ""}, clear=False):
            self.assertTrue(app._unlimited_creatorthon_user({"email": " AHAMED.DON@GMAIL.COM "}))
            self.assertTrue(app._unlimited_creatorthon_user({"email": "yusufiid@gmail.com"}))
            self.assertTrue(app._unlimited_creatorthon_user({"email": "ansariarif1@gmail.com"}))
            self.assertFalse(app._unlimited_creatorthon_user({"email": "other@example.com"}))

    def test_environment_can_add_an_unlimited_email(self):
        with patch.dict(os.environ, {"CREATORTHON_UNLIMITED_EMAILS": "owner@example.com"}, clear=False):
            self.assertTrue(app._unlimited_creatorthon_user({"email": "OWNER@example.com"}))
            self.assertFalse(app._creatorthon_admin_user({"email": "OWNER@example.com"}))

    def test_only_the_three_organizer_emails_have_admin_access(self):
        self.assertTrue(app._creatorthon_admin_user({"email": "ahamed.don@gmail.com"}))
        self.assertTrue(app._creatorthon_admin_user({"email": "yusufiid@gmail.com"}))
        self.assertTrue(app._creatorthon_admin_user({"email": "ansariarif1@gmail.com"}))
        self.assertFalse(app._creatorthon_admin_user({"email": "other@example.com"}))

    def test_event_capacity_is_shared_and_atomic_in_store(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"APP_DATA_DIR": directory, "CREATORTHON_EVENT_KEY": "test-event"},
            clear=False,
        ):
            root = Path(directory)
            first = claim_event_seat(root, "one", 2)
            second = claim_event_seat(root, "two", 2)
            returning = claim_event_seat(root, "one", 2)
            self.assertEqual(first["seat_number"], 1)
            self.assertEqual(second["seat_number"], 2)
            self.assertEqual(returning["seat_number"], 1)
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

    def test_admin_can_grant_exactly_one_more_video(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"APP_DATA_DIR": directory, "DATABASE_URL": "", "CREATORTHON_EVENT_KEY": "credit-test"}, clear=False
        ):
            root = Path(directory)
            claim_event_seat(root, "user", 50, "person@example.com")
            self.assertTrue(reserve_event_generation(root, "user", "one", "pixverse")["allowed"])
            accept_event_generation(root, "user", "one", "pixverse", "job-1")
            self.assertFalse(reserve_event_generation(root, "user", "two", "pixverse")["allowed"])
            grant_extra_generation(root, "person@example.com", "ahamed.don@gmail.com")
            self.assertTrue(reserve_event_generation(root, "user", "two", "pixverse")["allowed"])
            accept_event_generation(root, "user", "two", "pixverse", "job-2")
            self.assertFalse(reserve_event_generation(root, "user", "three", "pixverse")["allowed"])
            account = event_admin_state(root)["users"][0]
            self.assertEqual(account["videos_used"], 2)
            self.assertEqual(account["total_allowance"], 2)
            self.assertEqual(account["credits_remaining"], 0)

    def test_admin_can_admit_named_email_after_capacity(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"APP_DATA_DIR": directory, "DATABASE_URL": "", "CREATORTHON_EVENT_KEY": "admit-test"}, clear=False
        ):
            root = Path(directory)
            claim_event_seat(root, "first", 1, "first@example.com")
            with self.assertRaisesRegex(RuntimeError, "50-user"):
                claim_event_seat(root, "second", 1, "second@example.com")
            grant_event_admission(root, "second@example.com", "ahamed.don@gmail.com")
            admitted = claim_event_seat(root, "second", 1, "second@example.com")
            self.assertEqual(admitted["seat_number"], 2)
            self.assertEqual(admitted["admission_override"], 1)
            state = event_admin_state(root, 1)
            self.assertEqual(state["admitted_count"], 2)
            self.assertEqual(state["audit"][0]["action"], "admit_user")

    def test_admin_can_remove_user_free_seat_and_readmit_later(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"APP_DATA_DIR": directory, "DATABASE_URL": "", "CREATORTHON_EVENT_KEY": "remove-test"}, clear=False
        ):
            root = Path(directory)
            claim_event_seat(root, "first", 1, "first@example.com")
            result = remove_event_user(root, "first@example.com", "ahamed.don@gmail.com")
            self.assertTrue(result["removed"])
            replacement = claim_event_seat(root, "second", 1, "second@example.com")
            self.assertEqual(replacement["seat_number"], 1)
            with self.assertRaisesRegex(RuntimeError, "removed by an organizer"):
                claim_event_seat(root, "first", 1, "first@example.com")
            grant_event_admission(root, "first@example.com", "ahamed.don@gmail.com")
            restored = claim_event_seat(root, "first", 1, "first@example.com")
            self.assertTrue(restored["admission_override"])
            self.assertEqual(event_admin_state(root, 1)["admitted_count"], 2)

    def test_workflow_step_and_selected_topic_survive_reload(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"APP_DATA_DIR": directory, "DATABASE_URL": ""}, clear=False
        ):
            root = Path(directory)
            saved = save_workflow_state(root, "user", {
                "step": "create",
                "topics": [{"topic": "First"}, {"topic": "Chosen"}],
                "selected_topic": {"topic": "Chosen"},
            })
            restored = get_workflow_state(root, "user")
            self.assertEqual(saved["step"], "create")
            self.assertEqual(restored["topics"][1]["topic"], "Chosen")
            self.assertEqual(restored["selected_topic"]["topic"], "Chosen")

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

    def test_explicit_user_prompt_replaces_secured_prompt_for_generation(self):
        project = {"prompt": {"text": "PRIVATE VIRALIZER PROMPT"}}
        prompt, custom = app._creatorthon_generation_prompt(project, "  My exact video prompt  ")
        self.assertEqual(prompt, "My exact video prompt")
        self.assertTrue(custom)
        prompt, custom = app._creatorthon_generation_prompt(project, "")
        self.assertEqual(prompt, "PRIVATE VIRALIZER PROMPT")
        self.assertFalse(custom)

    def test_custom_prompt_topic_alignment_detects_match_and_mismatch(self):
        topic = {"topic": "PlayStation 5 gaming console update"}
        self.assertTrue(app._creatorthon_prompt_matches_topic(topic, "Show a gamer unboxing a PlayStation 5 console."))
        self.assertFalse(app._creatorthon_prompt_matches_topic(topic, "Show a chef decorating a chocolate wedding cake."))
        self.assertFalse(app._creatorthon_prompt_matches_topic(
            {"topic": "Macy's Unveils Its 2026 Fall Fashion Campaign Featuring a Celebration of American Fashion"},
            "Create a premium commercial featuring a sleek Audi performance sedan.",
        ))

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
                {"sections": [{"text": "By analyzing the top creators, the representative distributions are:", "type": "NORMAL"}]},
                {"sections": [{"text": "Themes:", "type": "BOLD"}, {"text": "Fashion (50%), News (50%)", "type": "NORMAL"}]},
                {"sections": [{"text": "Countries:", "type": "BOLD"}, {"text": "United States (45%), Italy (9%)", "type": "NORMAL"}]},
                {"sections": [{"text": "Languages:", "type": "BOLD"}, {"text": "en (57%), en-US (28%), ko (7%)", "type": "NORMAL"}]},
                {"sections": [{"text": "Related Content Ideas", "type": "BOLD"}]},
                {"sections": [{"text": "This must not be part of Creator Insight.", "type": "NORMAL"}]},
            ],
        }
        self.assertEqual(
            app._report_insight(report, "Audience Insight"),
            "A fashion-forward person aged 18-35 who values sustainability.",
        )
        creator = app._report_insight(report, "Creator Insight")
        self.assertIn("Themes: Fashion", creator)
        self.assertIn("Countries: United States", creator)
        self.assertIn("Languages: en", creator)
        self.assertNotIn("not available", creator)
        self.assertNotIn("must not be part", creator)
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

    def test_review_hashtag_cache_is_scoped_to_the_selected_topic(self):
        page = (Path(app.__file__).parent / "static" / "creatorthon.html").read_text(encoding="utf-8")
        self.assertIn("creatorthonHashtagTopicKey===topicKey", page)
        self.assertIn("insightTopicKey(selected)!==topicKey", page)
        self.assertIn("body:JSON.stringify({topic:topicSnapshot})", page)

    def test_custom_prompt_editor_is_visible_and_sent_to_secured_generation(self):
        page = (Path(app.__file__).parent / "static" / "creatorthon.html").read_text(encoding="utf-8")
        self.assertIn("custom-prompt-field", page)
        self.assertIn("Describe your video", page)
        self.assertIn("prompt:custom?customText:''", page)
        self.assertIn("Create a ${duration}-second short video", page)
        self.assertIn("I reviewed and updated the speech script", page)
        self.assertIn("Use this prompt despite the topic mismatch", page)
        self.assertIn("speech_script_reviewed", page)
        self.assertIn("custom-prompt-field>label:before", page)
        self.assertIn(".production-field:not(.narration)>label:before", page)
        self.assertNotIn(".production-field:not(.narration) label:before", page)

    def test_insight_queue_preserves_scroll_position_when_rerendered(self):
        page = (Path(app.__file__).parent / "static" / "creatorthon.html").read_text(encoding="utf-8")
        self.assertIn("panelTop=current?.scrollTop", page)
        self.assertIn("replacement.scrollTop=Math.min(panelTop", page)
        self.assertIn("window.scrollTo({top:pageTop", page)


if __name__ == "__main__":
    unittest.main()
