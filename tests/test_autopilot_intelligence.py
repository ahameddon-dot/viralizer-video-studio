import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import (
    archive_other_opportunities,
    generate_concepts,
    get_brand_profile,
    list_concepts,
    list_opportunities,
    get_concept,
    record_keyframe,
    rank_opportunities,
    save_brand_profile,
)


class AutopilotIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def brand(self, customer="customer-1", confirmed=True):
        return save_brand_profile(self.root, customer, {
            "customer_type": "business",
            "website_url": "https://example.com",
            "social_urls": ["https://youtube.com/@example"],
            "voice": ["clear", "practical"],
            "positioning": "Analytics software for independent ecommerce businesses",
            "audiences": ["ecommerce founders"],
            "goals": ["website visits"],
            "products_services": ["commerce analytics"],
            "visual_style": ["clean dashboards"],
            "constraints": ["do not invent revenue claims"],
            "confirmed": confirmed,
        })

    def test_brand_profile_tracks_provenance_and_is_customer_scoped(self):
        profile = self.brand()
        self.assertEqual("confirmed", profile["status"])
        provenances = {item["provenance"] for item in profile["evidence"]}
        self.assertIn("observed", provenances)
        self.assertIn("customer_confirmed", provenances)
        self.assertIsNone(get_brand_profile(self.root, "customer-2"))

    def test_brand_corrections_create_a_new_version(self):
        first = self.brand()
        corrected = self.brand()
        self.assertEqual(1, first["version"])
        self.assertEqual(2, corrected["version"])
        self.assertNotEqual(first["id"], corrected["id"])

    def test_draft_brand_cannot_rank_opportunities(self):
        self.brand(confirmed=False)
        with self.assertRaises(ValueError):
            rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Commerce trend"}]})

    def test_ranking_persists_five_and_preserves_missing_viralizer_signal(self):
        self.brand()
        topics = [
            {"topic": "Ecommerce analytics changes", "category": "Business", "viral_score": 92, "discovery_heat": "EXPLODING", "video_idea": "Explain the change"},
            {"topic": "Creator economy update", "category": "Creators", "viral_rank": 20, "discovery_heat": "VERY HOT"},
            {"topic": "Retail dashboard design", "category": "Technology", "discovery_heat": "HOT", "role_match_index": 180},
            {"topic": "Online store conversion research", "category": "Business", "viral_score": 75, "discovery_heat": "HOT"},
            {"topic": "Small business website traffic", "category": "Business", "viral_rank": 40, "discovery_heat": "WATCH"},
            {"topic": "Unrelated sports result", "category": "Sports", "viral_score": 20, "discovery_heat": "WATCH"},
        ]
        ranked = rank_opportunities(self.root, "customer-1", {"topics": topics, "limit": 5})
        self.assertEqual(4, len(ranked))
        self.assertEqual("Ecommerce analytics changes", ranked[0]["title"])
        missing = next(item for item in ranked if item["title"] == "Retail dashboard design")
        self.assertEqual(0, missing["components"]["viralizer"])
        self.assertFalse(missing["components"]["viral_data_available"])
        self.assertIn("business_impact", missing["components"])
        self.assertIn("was not estimated", missing["rationale"])
        self.assertEqual(4, len(list_opportunities(self.root, "customer-1")))

    def test_unrelated_high_velocity_topics_are_not_recommended(self):
        save_brand_profile(self.root, "dog-channel", {
            "customer_type": "creator", "social_urls": ["https://youtube.com/@dog"],
            "positioning": "Rottweiler training, puppy care and canine adventures",
            "audiences": ["dog owners and pet lovers"], "products_services": ["dog training content"],
            "keywords": ["rottweiler", "dogs", "puppies"], "confirmed": True,
        })
        ranked = rank_opportunities(self.root, "dog-channel", {"topics": [
            {"topic": "Claude Code API billing changes", "viral_score": 99, "role_match_index": 200},
            {"topic": "Rottweiler puppy obedience mistakes", "viral_score": 70},
        ]})
        self.assertEqual(["Rottweiler puppy obedience mistakes"], [item["title"] for item in ranked])

    def test_generic_content_words_do_not_make_irrelevant_topics_brand_relevant(self):
        save_brand_profile(self.root, "dog-channel", {
            "customer_type": "creator", "positioning": "Rottweiler videos for pet lovers",
            "audiences": ["dog owners"], "products_services": ["puppy content"],
            "keywords": ["rottweiler", "puppy", "shorts", "creators"], "confirmed": True,
        })
        ranked = rank_opportunities(self.root, "dog-channel", {"topics": [
            {"topic": "Free Spins Bonuses Compared for Beginners", "summary": "Latest creator content guide", "viral_score": 99},
            {"topic": "Rottweiler puppy socialization checklist", "viral_score": 70},
            {"topic": "Rottweiler puppy socialization checklist", "viral_score": 70},
        ]})
        self.assertEqual(["Rottweiler puppy socialization checklist"], [item["title"] for item in ranked])

    def test_empty_refresh_archives_stale_recommendations(self):
        self.brand()
        rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Ecommerce analytics update"}]})
        archive_other_opportunities(self.root, "customer-1", [])
        self.assertEqual([], list_opportunities(self.root, "customer-1"))

    def test_rank_over_one_hundred_is_available_even_when_normalized_signal_is_zero(self):
        self.brand()
        item = rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Commerce analytics", "viral_rank": 137}]})[0]
        self.assertEqual(0, item["components"]["viralizer"])
        self.assertEqual(137, item["components"]["viral_rank"])
        self.assertTrue(item["components"]["viral_data_available"])
        self.assertIn("rank #137", item["rationale"])

    def test_ranking_is_idempotent_for_same_topic_and_model(self):
        self.brand()
        request = {"topics": [{"topic": "Ecommerce analytics changes", "viral_score": 90}]}
        first = rank_opportunities(self.root, "customer-1", request)[0]
        second = rank_opportunities(self.root, "customer-1", request)[0]
        self.assertEqual(first["id"], second["id"])

    def test_new_refresh_can_supersede_stale_recommendations(self):
        self.brand()
        old = rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Old ecommerce analytics topic"}]})[0]
        new = rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "New ecommerce analytics topic"}]})[0]
        archive_other_opportunities(self.root, "customer-1", [new["id"]])
        visible = list_opportunities(self.root, "customer-1")
        self.assertEqual([new["id"]], [item["id"] for item in visible])
        self.assertNotEqual(old["id"], new["id"])

    def test_creative_director_generates_exactly_three_distinct_15_second_concepts(self):
        self.brand()
        opportunity = rank_opportunities(self.root, "customer-1", {
            "topics": [{"topic": "Ecommerce analytics changes", "viral_score": 90, "discovery_heat": "EXPLODING"}]
        })[0]
        concepts = generate_concepts(self.root, "customer-1", {
            "opportunity_id": opportunity["id"], "platform": "youtube_shorts", "goal": "Visit the website",
        })
        self.assertEqual(3, len(concepts))
        self.assertEqual(3, len({item["name"] for item in concepts}))
        self.assertTrue(all(item["content"]["duration_seconds"] == 15 for item in concepts))
        self.assertTrue(all(item["content"]["production_mode"] == "image_to_video" for item in concepts))
        self.assertTrue(all(all(scene.get("keyframe_prompt") and scene.get("motion_prompt") for scene in item["content"]["storyboard"]) for item in concepts))
        self.assertTrue(all(item["content"]["cta"] == "Visit the website" for item in concepts))
        self.assertEqual(3, len(list_concepts(self.root, "customer-1", opportunity["id"])))
        keyframe = record_keyframe(self.root, "customer-1", concepts[0]["id"], 0, {"filename": "scene.png", "image_url": "/keyframe", "provider": "openai_image"})
        self.assertEqual(1, keyframe["version"])
        stored = get_concept(self.root, "customer-1", concepts[0]["id"])
        self.assertEqual("scene.png", stored["content"]["keyframes"]["0"][0]["filename"])

    def test_opportunities_and_concepts_cannot_cross_customer_boundary(self):
        self.brand("customer-1")
        self.brand("customer-2")
        opportunity = rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Private ecommerce analytics topic"}]})[0]
        with self.assertRaises(ValueError):
            generate_concepts(self.root, "customer-2", {"opportunity_id": opportunity["id"]})
        self.assertEqual([], list_concepts(self.root, "customer-2", opportunity["id"]))


if __name__ == "__main__":
    unittest.main()

