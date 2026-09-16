import unittest

from motion_director import build_motion_plan


WONKA_OUTLINE = """Introduction to Wonka Chocolate. Brief history of Wonka and its pop culture significance.
Overview of the tasting event. Presentation of different Wonka chocolate varieties. Tasting notes and
flavor profiles for each chocolate. Fun facts and trivia. Poll: Which Wonka chocolate is your favorite?
Share tasting experiences in the comments. Recap the tasting and subscribe for more sweet content."""


class ContentGroundingRegressionTests(unittest.TestCase):
    def plan(self, topic, details="", generation_type="text_to_video"):
        return build_motion_plan(
            {"topic": topic, "video_idea": details},
            5,
            generation_type=generation_type,
            quality_mode=True,
        )

    def assert_semantic_pass(self, plan):
        self.assertEqual(plan.semantic_validation["status"], "PASS")
        self.assertEqual(plan.semantic_validation["concept"]["status"], "PASS")
        self.assertEqual(plan.semantic_validation["final"]["status"], "PASS")

    def test_wonka_chocolate_is_grounded_in_food(self):
        plan = self.plan("Wonka chocolate tasting", WONKA_OUTLINE)
        self.assertEqual(plan.category, "Food / Confectionery")
        self.assertEqual(plan.core_subject, "chocolate tasting and review")
        self.assertIn("premium food commercial", plan.final_prompt)
        self.assertIn("gently breaks", plan.final_prompt)
        self.assertNotIn("product designer", plan.final_prompt.lower())
        self.assertNotIn("prototype", plan.final_prompt.lower())
        self.assertNotIn("technology studio", plan.final_prompt.lower())
        self.assert_semantic_pass(plan)

    def test_prawn_seafood_never_uses_chocolate_template(self):
        plan = self.plan("prawn: Seafood Cooking Techniques", "Demonstrate a premium prawn cooking technique with tongs, pan heat and herb butter")
        self.assertEqual(plan.category, "Food / Seafood")
        self.assertIn("prawn", plan.final_prompt.lower())
        self.assertIn("tongs", plan.final_prompt.lower())
        self.assertIn("herb butter", plan.final_prompt.lower())
        for forbidden in ("chocolate", "confectionery", "candy", "filling", "tasting surface"):
            self.assertNotIn(forbidden, plan.final_prompt.lower())
        self.assert_semantic_pass(plan)
    def test_sony_gaming_update(self):
        plan = self.plan("Sony gaming industry update", "PlayStation players and a new game experience")
        self.assertEqual(plan.category, "Gaming")
        self.assertEqual(plan.scene_type, "GAMING")
        self.assertIn("gaming", plan.final_prompt.lower())
        self.assert_semantic_pass(plan)

    def test_ai_company_investment(self):
        plan = self.plan("AI company investment update", "A software company raises investment for its artificial intelligence platform")
        self.assertEqual(plan.category, "Technology / Business")
        self.assertEqual(plan.scene_type, "TECH")
        self.assertIn("technology", plan.final_prompt.lower())
        self.assert_semantic_pass(plan)

    def test_perfume_review(self):
        plan = self.plan("Luxury perfume review", "Review the fragrance bottle, materials and scent experience")
        self.assertEqual(plan.category, "Beauty / Product")
        self.assertEqual(plan.scene_type, "BEAUTY")
        self.assertIn("beauty", plan.final_prompt.lower())
        self.assert_semantic_pass(plan)

    def test_car_launch(self):
        plan = self.plan("New electric car launch", "Reveal the vehicle driving on a coastal road")
        self.assertEqual(plan.category, "Automotive")
        self.assertEqual(plan.scene_type, "AUTOMOTIVE")
        self.assertIn("vehicle", plan.final_prompt.lower())
        self.assert_semantic_pass(plan)

    def test_stock_market_update(self):
        plan = self.plan("Stock market update", "Investors react to trading and earnings movement")
        self.assertEqual(plan.category, "Finance / Business")
        self.assertEqual(plan.scene_type, "FINANCE")
        self.assertIn("financial", plan.final_prompt.lower())
        self.assert_semantic_pass(plan)

    def test_vinyl_reference_preservation(self):
        plan = self.plan("Vinyl record music player interface", "Create a seamless loop", "image_to_video")
        self.assertEqual(plan.scene_type, "UI_ANIMATION")
        self.assertIn("same angular speed", plan.final_prompt)
        self.assertIn("camera completely locked", plan.final_prompt)
        self.assert_semantic_pass(plan)

    def test_moba_reference_preservation(self):
        plan = self.plan("MOBA hero character selection screen", "Living splash-art idle animation", "image_to_video")
        self.assertEqual(plan.scene_type, "GAMING")
        self.assertEqual(plan.preservation_map["identity"], "STRICT")
        self.assertIn("pixel-stable", plan.final_prompt)
        self.assert_semantic_pass(plan)

    def test_fresh_context_prevents_category_contamination(self):
        sequence = [
            self.plan("Sony AI technology platform", "software and chip development"),
            self.plan("Wonka chocolate tasting", WONKA_OUTLINE),
            self.plan("Luxury perfume review", "fragrance bottle and scent experience"),
            self.plan("Stock market update", "investors and trading movement"),
        ]
        self.assertEqual([plan.category for plan in sequence], [
            "Technology / Business", "Food / Confectionery", "Beauty / Product", "Finance / Business"
        ])
        self.assertNotIn("technology", sequence[1].final_prompt.lower())
        self.assertNotIn("chocolate", sequence[2].final_prompt.lower())
        self.assertNotIn("perfume", sequence[3].final_prompt.lower())


if __name__ == "__main__":
    unittest.main()
