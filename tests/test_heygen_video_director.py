import unittest

from heygen_video_director import build_heygen_plan, compile_heygen_request
from motion_director import build_motion_plan


CASES = [
    ({"topic": "Wonka chocolate tasting and reviews"}, 5),
    ({"topic": "Wonka chocolate tasting and reviews"}, 10),
    ({"topic": "Wonka chocolate tasting and reviews"}, 30),
    ({"topic": "WWE Raw professional wrestling analysis"}, 5),
    ({"topic": "WWE Raw professional wrestling analysis"}, 15),
    ({"topic": "WWE Raw professional wrestling analysis"}, 30),
    ({"topic": "Sony gaming industry update"}, 15),
    ({"topic": "Sony gaming industry update"}, 30),
    ({"topic": "Beauty product review"}, 15),
    ({"topic": "New car launch"}, 15),
    ({"topic": "Stock-market explanation"}, 30),
    ({"topic": "Travel destination guide"}, 30),
]


class HeyGenVideoDirectorTests(unittest.TestCase):
    def test_all_requested_scenarios_compile(self):
        for content, duration in CASES:
            with self.subTest(topic=content["topic"], duration=duration):
                plan = build_heygen_plan(content, duration)
                payload = compile_heygen_request(plan)
                self.assertEqual(plan["semantic_validation"]["status"], "PASS")
                self.assertAlmostEqual(sum(x["duration"] for x in plan["scenes"]), duration)
                self.assertEqual(payload["mode"], "generate")
                self.assertIn("prompt", payload)
                self.assertNotIn("visual_bible", payload)
                self.assertNotIn("semantic_score", payload)

    def test_prawn_seafood_does_not_inherit_chocolate_story(self):
        plan = build_heygen_plan({"topic": "prawn: Seafood Cooking Techniques"}, 5)
        self.assertEqual(plan["content_grounding"]["category"], "Food / Seafood")
        rendered = str(plan).lower()
        self.assertIn("prawn", rendered)
        self.assertIn("tongs", rendered)
        self.assertNotIn("chocolate", rendered)
        self.assertNotIn("confectionery", rendered)
    def test_wrestling_never_selects_other_sports(self):
        plan = build_heygen_plan({"topic": "Professional wrestling match analysis"}, 15)
        rendered = str(plan).lower()
        self.assertIn("wrestling ring", rendered)
        self.assertNotIn("soccer player", rendered)
        self.assertNotIn("basketball", rendered)

    def test_wonka_is_visual_first_and_not_talking_head_only(self):
        plan = build_heygen_plan({"topic": "Wonka chocolate tasting review"}, 10)
        self.assertEqual(plan["visual_mode"], "VISUAL_FIRST")
        self.assertIn("breaks it open", str(plan["scenes"]).lower())
        self.assertIn("not a talking head", plan["compiled_prompt"])
        self.assertEqual(len(plan["scenes"]), 4)
        self.assertEqual([scene["purpose"] for scene in plan["scenes"]], ["ESTABLISH", "FOCUS", "INTERACT_REVEAL", "PAYOFF"])
        self.assertIn("hand", plan["visual_story_arc"]["primary_interaction"])
        self.assertIn("hero", plan["ending_strategy"].lower())
        self.assertTrue(all(plan["semantic_validation"]["checks"].values()))

    def test_pixverse_and_heygen_have_provider_specific_plans(self):
        content = {"topic": "Sony gaming industry update", "category": "Gaming"}
        heygen = build_heygen_plan(content, 15)
        pixverse = build_motion_plan(content, 15, generation_type="text_to_video", quality_mode=True)
        self.assertIn("scenes", heygen)
        self.assertNotEqual(heygen["compiled_prompt"], pixverse.final_prompt)
        self.assertEqual(heygen["provider"], "heygen")


if __name__ == "__main__":
    unittest.main()