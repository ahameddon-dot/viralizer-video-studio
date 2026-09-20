import unittest
from unittest.mock import AsyncMock, patch

from article_intelligence import (
    build_story_package,
    extract_article_html,
    prepare_article_intelligence,
    resolve_and_extract_article,
    validate_story_package,
)
from motion_director import build_motion_plan
from quality_pipeline import build_plan


def article_html(paragraphs=12):
    prose = " ".join(["Diana wore a recycled silk gown at the London fashion exhibition while designers explained the material process."] * paragraphs)
    return f'''<html><head><link rel="canonical" href="https://publisher.example/diana-fashion">
    <script type="application/ld+json">{{"@type":"NewsArticle","headline":"Diana exhibition reframes sustainable fashion","author":{{"name":"A Reporter"}},"datePublished":"2026-09-20","publisher":{{"name":"Example News"}},"articleBody":"{prose}"}}</script></head><body><article><p>{prose}</p></article></body></html>'''


class ArticleExtractionTests(unittest.IsolatedAsyncioTestCase):
    def test_complete_and_partial_extraction_states(self):
        complete = extract_article_html("https://news.google.com/item", "https://publisher.example/story", article_html(24), {})
        partial = extract_article_html("https://publisher.example/short", "https://publisher.example/short", article_html(8), {})
        self.assertEqual(complete["extraction_state"], "complete")
        self.assertEqual(partial["extraction_state"], "partial")
        self.assertEqual(complete["author"], "A Reporter")
        self.assertEqual(complete["canonical_url"], "https://publisher.example/diana-fashion")

    async def test_google_discovery_url_resolves_to_publisher(self):
        async def fetcher(url):
            self.assertIn("news.google.com", url)
            return "https://publisher.example/diana-fashion", article_html(24), 200
        result = await resolve_and_extract_article({"topic":"Diana fashion story","source_urls":["https://news.google.com/rss/articles/test"]}, fetcher)
        self.assertEqual(result["canonical_url"], "https://publisher.example/diana-fashion")
        self.assertEqual(result["extraction_state"], "complete")

    async def test_blocked_publisher_uses_explicit_fallback(self):
        async def fetcher(url):
            return "https://publisher.example/paywall", "<html>Subscribe to continue reading</html>", 403
        result = await resolve_and_extract_article({"topic":"Blocked story","summary":"Verified discovery snippet","source_urls":["https://publisher.example/paywall"]}, fetcher)
        self.assertEqual(result["extraction_state"], "blocked")
        self.assertEqual(result["standfirst"], "Verified discovery snippet")
        self.assertEqual(result["article_body"], "")


class StoryDirectorTests(unittest.IsolatedAsyncioTestCase):
    def valid_package(self):
        return {
            "story_understanding": {
                "what_happened":"A recycled silk gown opened a fashion exhibition.",
                "main_subjects":["Diana", "recycled silk gown"],
                "important_context":"The exhibition explains material reuse.",
                "new_development":"The gown is presented as the opening exhibit.",
                "core_message":"Diana's gown makes recycled silk the tangible focus of the exhibition.",
                "viewer_takeaway":"Material reuse is being shown through one concrete garment.",
                "key_visual_facts":["Diana wears a recycled silk gown", "Designers show the fabric process"],
                "factual_boundaries":["Do not invent a runway show."],
                "unsupported_visuals":["runway crowd", "award ceremony"],
            },
            "visual_story_plan": {
                "core_visual_subject":"the recycled silk gown",
                "visual_message":"A single recycled-silk garment makes sustainable fashion tangible.",
                "selected_creative_concept":"Use a source-supported fabric comparison to transform one gown from beautiful object into visible evidence of material reuse.",
                "creative_concept_selection_reason":"The fabric comparison is specific, factual, visually legible, and continuous.",
                "visual_hook":"Diana enters the exhibition wearing the recycled silk gown.",
                "story_beats":[
                    {"beat":1,"purpose":"hook","visual":"Diana enters the exhibition wearing the recycled silk gown."},
                    {"beat":2,"purpose":"development","visual":"A designer lifts a fabric sample beside the gown to reveal its recycled weave."},
                    {"beat":3,"purpose":"payoff","visual":"Diana turns toward the finished exhibit while the gown settles naturally."},
                ],
                "continuity_strategy":"Keep Diana, the gown, and exhibition lighting continuous.",
                "hero_payoff":"Diana turns toward the finished exhibit while the gown settles naturally.",
                "visual_style":"factual fashion editorial",
                "must_show":["recycled silk gown", "exhibition"],
                "must_avoid":["runway crowd", "award ceremony"],
                "muted_test_explanation":"The garment, fabric comparison, and exhibit communicate reuse without narration.",
            },
            "model":"test-model",
        }

    def test_structured_story_and_visual_plan_pass(self):
        package = self.valid_package()
        result = validate_story_package(package["story_understanding"], package["visual_story_plan"], 10)
        self.assertEqual(result["status"], "PASS")

    def test_muted_and_generic_failures_are_rejected(self):
        package = self.valid_package()
        package["visual_story_plan"].update(visual_hook="", hero_payoff="", story_beats=[{"beat":1,"purpose":"hook","visual":"Use dynamic visuals and engaging scene."}])
        result = validate_story_package(package["story_understanding"], package["visual_story_plan"], 10)
        self.assertFalse(result["checks"]["muted_test_pass"])
        self.assertFalse(result["checks"]["generic_video_pass"])

    def test_unsupplied_archival_assets_are_rejected(self):
        package = self.valid_package()
        package["visual_story_plan"]["story_beats"][1]["visual"] = "Show a vintage invitation with handwriting beside an archival photo frame."
        result = validate_story_package(package["story_understanding"], package["visual_story_plan"], 10)
        self.assertFalse(result["checks"]["generated_visuals_safe"])
        self.assertEqual(result["status"], "FAIL")

    async def test_failed_first_plan_regenerates_once(self):
        bad = self.valid_package(); bad["visual_story_plan"]["visual_hook"] = ""; bad["visual_story_plan"]["hero_payoff"] = ""
        good = self.valid_package()
        with patch("article_intelligence._ask_story_model", new=AsyncMock(side_effect=[bad, good])) as mocked:
            result = await build_story_package({"headline":"Diana fashion story","standfirst":"A recycled silk gown opens an exhibition."}, 10)
        self.assertEqual(mocked.await_count, 2)
        self.assertEqual(result["validation"]["status"], "PASS")

    async def test_prepare_adds_factual_boundaries_without_network_or_llm(self):
        source = {"topic":"Diana fashion story","summary":"Diana wears a recycled silk gown at an exhibition."}
        with patch("article_intelligence._ask_story_model", new=AsyncMock(side_effect=RuntimeError("offline test"))):
            enriched = await prepare_article_intelligence(source, 5)
        self.assertIn("story_understanding", enriched)
        self.assertIn("visual_story_plan", enriched)
        self.assertTrue(enriched["factual_boundaries"])
        self.assertEqual(enriched["extraction_state"], "snippet_only")

    def test_motion_director_receives_current_story_beat(self):
        package = self.valid_package()
        content = {"topic":"Diana fashion story","category":"Fashion", **package, "current_story_beat":package["visual_story_plan"]["story_beats"][1]["visual"]}
        plan = build_motion_plan(content, 5)
        self.assertIn("designer lifts a fabric sample", plan.final_prompt.lower())
        self.assertEqual(plan.current_story_beat, content["current_story_beat"].rstrip("."))
        self.assertIn("runway crowd", plan.must_avoid)
        self.assertEqual(plan.core_subject, "the recycled silk gown")
        self.assertEqual(plan.semantic_validation["handoff"]["status"], "PASS")

    def test_diana_revenge_dress_remains_authoritative_visual_subject(self):
        package = {
            "story_understanding": {
                "what_happened":"Princess Diana's black strapless silk Revenge Dress is being exhibited before a Sotheby's auction.",
                "main_subjects":["Princess Diana", "Revenge Dress"],
                "important_context":"The dress became a symbol of confidence and resilience.",
                "new_development":"The dress is expected to sell for up to $300,000.",
                "core_message":"The Revenge Dress is both a significant fashion object and a symbol of personal strength and communication through fashion.",
                "viewer_takeaway":"The garment carries cultural meaning beyond fashion.",
                "key_visual_facts":["black strapless silk dress", "public gallery display"],
                "factual_boundaries":["Do not fabricate Princess Diana or Prince Charles reenactments."],
                "unsupported_visuals":["fabricated archival photographs", "invented historical reenactments"],
            },
            "visual_story_plan": {
                "core_visual_subject":"Princess Diana's black strapless Revenge Dress",
                "visual_message":"Present the Revenge Dress as a symbol of confidence and resilience ahead of its exhibition and auction.",
                "selected_creative_concept":"Reveal the dress as a cultural artifact moving from intimate material detail to public display and auction attention.",
                "creative_concept_selection_reason":"The gallery reveal connects the sourced object's detail to its renewed cultural attention without reenactment.",
                "visual_hook":"An elegant reveal of the black strapless silk dress on a mannequin.",
                "story_beats":[
                    {"beat":1,"purpose":"hook","visual":"Close, controlled views reveal the dress's black silk fabric and strapless silhouette."},
                    {"beat":2,"purpose":"development","visual":"A slow widening view reveals the dress displayed in the gallery before the auction."},
                    {"beat":3,"purpose":"payoff","visual":"The dress remains central in a clean, stable gallery hero composition."},
                ],
                "continuity_strategy":"Keep the same dress, mannequin, gallery, and lighting across all beats.",
                "hero_payoff":"The dress remains central in a clean, stable gallery hero composition.",
                "visual_style":"factual premium fashion editorial",
                "must_show":["black strapless silk dress", "gallery display"],
                "must_avoid":["fabricated archival photographs", "historical reenactments"],
                "muted_test_explanation":"The dress reveal, detail, and gallery payoff communicate its importance without narration.",
            },
        }
        for beat in package["visual_story_plan"]["story_beats"]:
            content = {"topic":"Princess Diana Revenge Dress auction", "category":"Fashion", **package, "current_story_beat":beat["visual"]}
            plan = build_motion_plan(content, 5)
            self.assertEqual(plan.core_subject, "Princess Diana's black strapless Revenge Dress")
            self.assertNotEqual(plan.core_subject, "Princess Diana")
            self.assertEqual(plan.selected_visual_concept, beat["visual"].rstrip(" ."))
            self.assertEqual(plan.semantic_validation["handoff"]["status"], "PASS")
            self.assertEqual(plan.semantic_validation["final_prompt_polish"]["status"], "PASS")
            self.assertEqual(plan.semantic_validation["status"], "PASS")
            self.assertNotIn("directly showing Princess Diana", plan.final_prompt)
            self.assertNotIn("archival photograph", plan.final_prompt.lower().split("do not introduce:", 1)[0])
            self.assertNotIn("vehicle", plan.final_prompt.lower())

    def test_authoritative_fashion_beat_cannot_become_automotive_from_red_carpet(self):
        package = self.valid_package()
        package["visual_story_plan"]["story_beats"][0]["visual"] = "Reveal the recycled silk gown beside a muted red carpet corner in the exhibition."
        content = {"topic":"Diana fashion story", "category":"Fashion", **package, "current_story_beat":package["visual_story_plan"]["story_beats"][0]["visual"]}
        plan = build_motion_plan(content, 5)
        self.assertNotEqual(plan.scene_type, "AUTOMOTIVE")
        self.assertNotIn("vehicle speed", plan.final_prompt.lower())
        self.assertNotIn("wheel", plan.final_prompt.lower())

    def test_quality_mode_retains_plan_and_adapts_duration(self):
        package = self.valid_package()
        content = {"topic":"Diana fashion story","category":"Fashion", **package}
        ten = build_plan(content, 10)
        five = build_plan(content, 5)
        self.assertEqual(sum(shot["duration"] for shot in ten["shots"]), 10)
        self.assertEqual(sum(shot["duration"] for shot in five["shots"]), 5)
        self.assertNotEqual(len(ten["shots"]), len(five["shots"]))
        self.assertTrue(all(shot["motion_debug"]["visual_story_plan"] for shot in ten["shots"]))
        self.assertTrue(all(shot["motion_debug"]["factual_boundaries"] for shot in ten["shots"]))


if __name__ == "__main__":
    unittest.main()
