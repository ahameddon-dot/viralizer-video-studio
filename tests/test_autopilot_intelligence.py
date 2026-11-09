import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import (
    generate_concepts,
    get_brand_profile,
    list_concepts,
    list_opportunities,
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
        self.assertEqual(5, len(ranked))
        self.assertEqual("Ecommerce analytics changes", ranked[0]["title"])
        missing = next(item for item in ranked if item["title"] == "Retail dashboard design")
        self.assertEqual(0, missing["components"]["viralizer"])
        self.assertIn("was not estimated", missing["rationale"])
        self.assertEqual(5, len(list_opportunities(self.root, "customer-1")))

    def test_ranking_is_idempotent_for_same_topic_and_model(self):
        self.brand()
        request = {"topics": [{"topic": "Ecommerce analytics changes", "viral_score": 90}]}
        first = rank_opportunities(self.root, "customer-1", request)[0]
        second = rank_opportunities(self.root, "customer-1", request)[0]
        self.assertEqual(first["id"], second["id"])

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
        self.assertTrue(all(item["content"]["cta"] == "Visit the website" for item in concepts))
        self.assertEqual(3, len(list_concepts(self.root, "customer-1", opportunity["id"])))

    def test_opportunities_and_concepts_cannot_cross_customer_boundary(self):
        self.brand("customer-1")
        self.brand("customer-2")
        opportunity = rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Private topic"}]})[0]
        with self.assertRaises(ValueError):
            generate_concepts(self.root, "customer-2", {"opportunity_id": opportunity["id"]})
        self.assertEqual([], list_concepts(self.root, "customer-2", opportunity["id"]))


if __name__ == "__main__":
    unittest.main()

