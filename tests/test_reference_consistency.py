import unittest

from motion_director import (
    build_motion_plan,
    build_shot_specification,
    compile_reference_image_prompt,
    validate_shot_consistency,
)
from quality_pipeline import build_plan


class ReferenceConsistencyTests(unittest.TestCase):
    def wrestling_plan(self):
        return build_motion_plan(
            {
                "topic": "WWERaw: Wrestling match analysis",
                "video_idea": "Break down the latest wrestling match, key moments and storylines.",
            },
            5,
            generation_type="image_to_video",
        )

    def test_wrestling_reference_uses_shared_shot_specification(self):
        plan = self.wrestling_plan()
        spec = build_shot_specification(plan)
        reference = compile_reference_image_prompt(spec)
        self.assertIn("two athletic professional wrestlers", reference.lower())
        self.assertIn("inside a clearly defined wrestling ring", reference.lower())
        self.assertIn("beginning of a grapple", reference.lower())
        self.assertIn("ring ropes", reference.lower())
        self.assertNotIn("focused football player", reference.lower())
        self.assertNotIn("regulation football", reference.lower())
        result = validate_shot_consistency(spec, reference, plan.final_prompt)
        self.assertEqual(result["status"], "PASS")

    def test_conflicting_positive_reference_is_blocked(self):
        plan = self.wrestling_plan()
        spec = build_shot_specification(plan)
        bad_reference = "A soccer player carries a soccer ball through a football tunnel toward a football pitch."
        result = validate_shot_consistency(spec, bad_reference, plan.final_prompt)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("soccer player", result["conflicting_objects"])

    def test_quality_pipeline_no_longer_builds_football_reference_for_wrestling(self):
        shot = build_plan(
            {"topic": "WWERaw: Wrestling match analysis", "video_idea": "Latest wrestling match and key moments"},
            5,
        )["shots"][0]
        self.assertEqual(shot["preflight_consistency"]["status"], "PASS")
        self.assertEqual(shot["shot_specification"]["core_subject"], "professional wrestling match")
        self.assertNotIn("football player", shot["reference_prompt"].lower())



    def test_wrestling_routes_through_validated_reference(self):
        from generation_router import choose_generation_route
        route = choose_generation_route(
            {"topic": "WWE Raw", "category": "Sports", "video_idea": "professional wrestling takedown"},
            reference_available=True,
            production_style="premium",
        )
        self.assertEqual(route.mode, "image_to_video")
if __name__ == "__main__":
    unittest.main()
