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


if __name__ == "__main__":
    unittest.main()
