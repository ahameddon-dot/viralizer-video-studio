import unittest
from unittest.mock import AsyncMock, patch

import app


class ArticleIntelligenceSafeFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_enriched_content_when_pipeline_succeeds(self):
        enriched = {"topic": "Fashion launch", "article_intelligence": {"version": 3}}
        with patch.object(app, "prepare_article_intelligence", new=AsyncMock(return_value=enriched)):
            result = await app.prepare_article_intelligence_safely(
                {"topic": "Fashion launch"}, 10, "9:16"
            )
        self.assertEqual(result, enriched)

    async def test_preserves_discovery_metadata_when_pipeline_raises(self):
        content = {"topic": "Fashion launch", "summary": "A new collection launched."}
        with patch.object(
            app,
            "prepare_article_intelligence",
            new=AsyncMock(side_effect=RuntimeError("publisher edge case")),
        ):
            result = await app.prepare_article_intelligence_safely(content, 10, "9:16")
        self.assertEqual(result["topic"], content["topic"])
        intelligence = result["article_intelligence"]
        self.assertEqual(intelligence["extraction_state"], "failed")
        self.assertEqual(intelligence["analysis_model"], "safe-discovery-metadata-fallback")
        self.assertFalse(intelligence["approved_for_media_generation"])
        self.assertIn("RuntimeError", intelligence["fallback_reason"])

    async def test_video_prompt_returns_editable_prompt_when_compiler_raises(self):
        request = app.GenerateRequest(
            content={
                "topic": "Myntra Launches Italian Fashion Brand Sisley in India",
                "summary": "The retailer introduced the Italian fashion label in India.",
            },
            duration=10,
            aspect_ratio="9:16",
            target_platform="Instagram",
        )
        with (
            patch.object(
                app,
                "prepare_article_intelligence_safely",
                new=AsyncMock(return_value=dict(request.content)),
            ),
            patch.object(app, "build_video_prompt", side_effect=RuntimeError("compiler edge case")),
        ):
            result = await app.video_prompt(request)
        self.assertTrue(result["prompt_fallback"])
        self.assertIn("Myntra", result["prompt"])
        self.assertIn("10-second vertical 9:16", result["prompt"])
        self.assertEqual(
            result["article_intelligence"]["analysis_model"],
            "safe-prompt-response-fallback",
        )


if __name__ == "__main__":
    unittest.main()
