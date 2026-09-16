import unittest

from motion_director import build_motion_plan


WONKA = {
    "topic": "Wonka chocolate tasting",
    "video_idea": "Introduction to Wonka Chocolate. Brief history and pop culture significance. "
    "Overview of the tasting event. Presentation of different varieties, tasting notes, flavor profiles, "
    "trivia, audience poll, comments and subscribe CTA.",
}

WWE = {
    "topic": "WWERaw: Wrestling match analysis",
    "video_idea": "Break down the latest wrestling match, key moments and storylines. "
    "1. Introduction to the Match 2. Overview of the Wrestlers Involved 3. Key Moments Breakdown.",
}


class PixVerseLanguageCompilerTests(unittest.TestCase):
    def test_internal_metadata_never_leaks(self):
        for content in (WONKA, WWE):
            prompt = build_motion_plan(content, 5, generation_type="text_to_video").final_prompt.lower()
            for forbidden in ("(primary", "(secondary", "(reactive", "(locked", "reacts_to", "attached_to", "inherits_motion", "/100 motion budget"):
                self.assertNotIn(forbidden, prompt)

    def test_wonka_uses_clean_grounded_constraints(self):
        plan = build_motion_plan(WONKA, 5, generation_type="text_to_video")
        self.assertEqual(plan.action_validation["status"], "PASS")
        self.assertIn("hand selects one chocolate piece, gently breaks it open, and reveals", plan.final_prompt.lower())
        self.assertNotIn("vehicle", plan.final_prompt.lower())
        self.assertNotIn("mechanism", plan.final_prompt.lower())
        self.assertNotIn("product designer", plan.final_prompt.lower())
        self.assertNotIn("introduction to the match", plan.final_prompt.lower())

    def test_wwe_resolves_abstract_analysis_to_observable_action(self):
        plan = build_motion_plan(WWE, 5, generation_type="text_to_video")
        self.assertEqual(plan.category, "Sports")
        self.assertEqual(plan.core_subject, "professional wrestling match")
        self.assertEqual(plan.action_validation["status"], "PASS")
        self.assertIn("secures the opponent, pivots with controlled balance", plan.final_prompt.lower())
        self.assertIn("inside the arena ring", plan.final_prompt.lower())
        self.assertNotIn("one clear human action", plan.final_prompt.lower())
        self.assertNotIn("key moments breakdown", plan.final_prompt.lower())
        self.assertNotIn("overview of the wrestlers", plan.final_prompt.lower())
        self.assertNotIn("product redesign", plan.final_prompt.lower())

    def test_image_prompts_are_natural_but_debug_stays_structured(self):
        plan = build_motion_plan(
            {"topic": "Vinyl music player interface", "video_idea": "seamless loop"},
            5,
            generation_type="image_to_video",
        )
        debug = plan.debug()
        self.assertIn("relationship_graph", debug)
        self.assertIn("motion_budget", debug)
        self.assertNotIn("relationship_graph", plan.final_prompt)
        self.assertNotIn("motion budget", plan.final_prompt.lower())
        self.assertIn("same angular speed", plan.final_prompt.lower())


    def test_final_prompt_polish_quality_checks_pass(self):
        for content in (WONKA, WWE):
            plan = build_motion_plan(content, 5, generation_type="text_to_video")
            report = plan.semantic_validation["final_prompt_polish"]
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(all(report["checks"].values()))
            self.assertNotIn("documentary shot centered on professional wrestling match", plan.final_prompt.lower())
            self.assertLessEqual(plan.final_prompt.lower().count("anatomy distortion"), 1)
            self.assertLessEqual(plan.final_prompt.lower().count("duplicated"), 1)
if __name__ == "__main__":
    unittest.main()
