import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from conversation.onboarding import respond_onboarding


def assistant(stage, data=None):
    return {"role": "assistant", "content": {"onboarding_stage": stage, "onboarding_data": data or {}}}


class ConversationOnboardingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = []

    def append(self, root, customer_id, conversation_id, role, content):
        self.saved.append((role, content))
        return {"id": "m1", "role": role, "content": content}

    async def test_starts_with_role_and_only_relevant_buttons(self):
        with patch("conversation.onboarding.append_message", side_effect=self.append):
            result = await respond_onboarding(Path("."), "customer", "conversation", [], "Start onboarding")
        content = result["message"]["content"]
        self.assertEqual("role", content["onboarding_stage"])
        self.assertEqual(["Business owner", "Content creator", "Agency"], [x["label"] for x in content["suggestions"]])

    async def test_website_and_social_are_analyzed_together(self):
        data = {"role": "creator", "social_urls": ["https://youtube.com/@brand"]}
        analysis = {"draft": {"brand_name": "Brand", "category": "Technology", "confidence": "high"},
                    "sources": [{"status": "analyzed", "image_url": "https://example.com/logo.png"}]}
        with patch("conversation.onboarding.append_message", side_effect=self.append), \
             patch("conversation.onboarding.analyze_brand_sources", new=AsyncMock(return_value=analysis)):
            result = await respond_onboarding(Path("."), "customer", "conversation", [assistant("website_url", data)], "https://example.com")
        self.assertEqual("brand_review", result["message"]["content"]["onboarding_stage"])
        self.assertTrue(any(role == "tool" for role, _ in self.saved))
        self.assertEqual("Brand", result["message"]["content"]["onboarding_data"]["draft"]["brand_name"])

    async def test_confirmation_saves_logo_name_and_confirmed_profile(self):
        data = {"role": "creator", "website_url": "https://example.com", "social_urls": [],
                "draft": {"brand_name": "Example", "category": "Technology", "confidence": "medium"},
                "sources": [{"image_url": "https://example.com/logo.png", "status": "analyzed"}]}
        profile = {"id": "profile1", "version": 1, "status": "confirmed"}
        with patch("conversation.onboarding.append_message", side_effect=self.append), \
             patch("conversation.onboarding.save_brand_profile", return_value=profile) as save:
            result = await respond_onboarding(Path("."), "customer", "conversation", [assistant("brand_review", data)], "I confirm this Brand DNA")
        payload = save.call_args.args[2]
        self.assertTrue(payload["confirmed"])
        self.assertEqual("Example", payload["brand_name"])
        self.assertEqual("https://example.com/logo.png", payload["logo_url"])
        self.assertEqual("complete", result["message"]["content"]["onboarding_stage"])
        self.assertEqual("onboarding_complete", result["message"]["content"]["type"])

    async def test_skipping_sources_requires_explicit_warning_acceptance(self):
        with patch("conversation.onboarding.append_message", side_effect=self.append):
            first = await respond_onboarding(Path("."), "customer", "conversation", [assistant("source_choice", {"role": "business"})], "Skip analysis")
            second = await respond_onboarding(Path("."), "customer", "conversation", [first["message"]], "I understand. Continue without source analysis.")
        self.assertEqual("skip_warning", first["message"]["content"]["onboarding_stage"])
        self.assertEqual("manual_description", second["message"]["content"]["onboarding_stage"])
