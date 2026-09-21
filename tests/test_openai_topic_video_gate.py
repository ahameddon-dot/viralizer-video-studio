import unittest
from unittest.mock import AsyncMock, patch

import article_intelligence


class OpenAITopicVideoGateTests(unittest.IsolatedAsyncioTestCase):
    def test_accepts_validated_openai_analysis(self):
        self.assertTrue(article_intelligence.openai_story_analysis_complete({
            "article_intelligence": {
                "analysis_model": "gpt-4.1-mini",
                "validation": {"status": "PASS"},
            }
        }))

    def test_rejects_fallback_analysis(self):
        self.assertFalse(article_intelligence.openai_story_analysis_complete({
            "model": "deterministic-evidence-fallback",
            "validation": {"status": "PASS"},
        }))

    async def test_strict_story_package_never_uses_fallback(self):
        article = {
            "title": "Strict OpenAI analysis test topic",
            "description": "A unique test story for the mandatory analysis gate.",
            "canonical_url": "https://example.test/strict-openai-analysis",
            "article_body": "A complete test article body describing a specific event and its outcome.",
        }
        with patch.object(
            article_intelligence,
            "_ask_story_model",
            new=AsyncMock(side_effect=RuntimeError("OpenAI unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "OpenAI unavailable"):
                await article_intelligence.build_story_package(
                    article,
                    10,
                    require_openai=True,
                )


if __name__ == "__main__":
    unittest.main()
