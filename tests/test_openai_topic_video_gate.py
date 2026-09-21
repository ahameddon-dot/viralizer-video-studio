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

    async def test_strict_preparation_rebuilds_rejected_storyboard(self):
        rejected = {
            "article_intelligence": {
                "version": 4,
                "duration": 10,
                "aspect_ratio": "9:16",
                "analysis_model": "gpt-4.1-mini",
                "validation": {"status": "PASS"},
                "approved_for_media_generation": False,
            }
        }
        rebuilt = {
            **rejected,
            "article_intelligence": {
                **rejected["article_intelligence"],
                "approved_for_media_generation": True,
            },
        }
        with patch.object(article_intelligence, "resolve_and_extract_article", new=AsyncMock(return_value={})), patch.object(
            article_intelligence, "build_story_package", new=AsyncMock(return_value={
                "story_understanding": {"factual_boundaries": [], "unsupported_visuals": []},
                "visualizability_analysis": {},
                "visual_story_plan": {},
                "validation": {"status": "PASS"},
                "model": "gpt-4.1-mini",
                "attempts": 1,
            })), patch.object(
            article_intelligence, "build_storyboard_package", new=AsyncMock(return_value={
                "storyboard": [], "reference_frame_plans": [], "visual_qc_specs": [],
                "muted_test_v2": {}, "generic_video_test_v2": {},
                "effective_visual_story_plan": {}, "validation": {"status": "PASS"},
                "creative_story_qc": {"final_story_pass": "PASS"},
                "story_type_qc": {"status": "PASS"},
                "approved_for_media_generation": True,
            })), patch.object(article_intelligence, "apply_achievement_representation", return_value={}), patch.object(
                article_intelligence, "build_source_evidence_locks", return_value=[]
            ), patch.object(article_intelligence, "collect_source_visual_evidence", return_value=[]):
            result = await article_intelligence.prepare_article_intelligence(rejected, 10, "9:16", require_openai=True)
        self.assertTrue(result["article_intelligence"]["approved_for_media_generation"])

    def test_standard_pixverse_fallback_is_explicit_and_v3_scoped(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        app_source = (root / "app.py").read_text(encoding="utf-8")
        v3_source = (root / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("allow_standard_fallback: bool = False", app_source)
        self.assertIn("not request.allow_standard_fallback", app_source)
        self.assertIn("effective_quality_mode and not", app_source)
        self.assertIn("allow_standard_fallback:true", v3_source)

    def test_standard_pixverse_fallback_is_available_in_confirmed_creatorthon_flows(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        v1_source = (root / "static" / "creatorthon.html").read_text(encoding="utf-8")
        v3_source = (root / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("quality_mode:false,allow_standard_fallback:true", v1_source)
        self.assertIn("quality_mode:false,allow_standard_fallback:true", v3_source)

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
