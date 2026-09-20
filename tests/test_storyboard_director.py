import unittest

from motion_director import build_motion_plan
from quality_pipeline import build_plan
from storyboard_director import build_reference_frame_plan, build_storyboard_package, validate_storyboard


class StoryboardDirectorTests(unittest.IsolatedAsyncioTestCase):
    def authority(self):
        story = {
            "core_message": "The Revenge Dress is receiving renewed attention as a cultural symbol of confidence before its auction.",
            "viewer_takeaway": "The garment's importance comes from its cultural meaning, not only its appearance.",
            "key_visual_facts": ["black strapless silk Revenge Dress", "displayed publicly before auction", "restrained visitors observe from a respectful distance", "symbol of confidence"],
            "factual_boundaries": ["Do not fabricate Princess Diana or historical events."],
            "unsupported_visuals": ["Princess Diana reenactment", "fabricated archival photographs"],
        }
        plan = {
            "core_visual_subject": "Princess Diana's black strapless Revenge Dress",
            "visual_message": "A private symbol of confidence becomes a publicly examined cultural artifact.",
            "selected_creative_concept": "Use a reflection-to-gallery reveal so the same dress shifts from intimate presence to public cultural attention.",
            "creative_concept_selection_reason": "The reflection creates truthful curiosity and connects identity, public attention, and auction display without reenactment.",
            "visual_hook": "The dress appears first as a fragmented reflection before the real garment resolves beside it.",
            "story_beats": [
                {"purpose": "HOOK", "visual": "A dark silk contour appears in a gallery reflection before the real dress resolves beside it."},
                {"purpose": "EVIDENCE", "visual": "The camera crosses the reflection edge to reveal the complete dress in its public display."},
                {"purpose": "HERO PAYOFF", "visual": "The same dress holds center frame while restrained visitors gather at a respectful distance."},
            ],
            "continuity_strategy": "Use the same dress, mannequin, reflection line, gallery, and lighting direction throughout.",
            "hero_payoff": "The same dress holds center frame as a publicly examined cultural artifact.",
            "visual_style": "factual museum-fashion editorial",
            "must_show": ["black strapless silk dress", "public gallery display"],
            "must_avoid": ["Princess Diana reenactment", "fabricated archival photographs"],
        }
        return story, plan

    def storyboard(self):
        story, plan = self.authority()
        shots = [
            {"shot_id":"S1","purpose":"HOOK","source_support":[story["key_visual_facts"][0]],"visual_subject":plan["core_visual_subject"],"visual_description":plan["story_beats"][0]["visual"],"action":"A reflection edge slides across frame and resolves into the stationary real dress.","environment":"public gallery display","composition":"reflection foreground, dress offset behind","camera":"slow lateral move across the reflection edge","lighting":"controlled gallery spotlight","foreground":"soft reflection edge","background":"restrained gallery depth","transition_in":"begin on the reflection","transition_out":"cross the reflection edge into the real display","continuity_requirements":[plan["continuity_strategy"]],"must_show":plan["must_show"],"must_avoid":plan["must_avoid"],"duration_seconds":4,"reference_frame_required":True},
            {"shot_id":"S2","purpose":"HERO PAYOFF","source_support":story["key_visual_facts"],"visual_subject":plan["core_visual_subject"],"visual_description":plan["story_beats"][2]["visual"],"action":"The camera settles as restrained visitors stop at a respectful distance around the display.","environment":"same public gallery display","composition":"dress central, visitors held in distant background","camera":"continue the lateral direction then settle","lighting":"same controlled gallery spotlight","foreground":"clear gallery floor","background":"restrained visitors without readable signage","transition_in":"continue across the same reflection boundary","transition_out":"settle on the approved hero composition","continuity_requirements":[plan["continuity_strategy"]],"must_show":plan["must_show"],"must_avoid":plan["must_avoid"],"duration_seconds":6,"reference_frame_required":True},
        ]
        return story, plan, {"storyboard":shots,"muted_test_v2":{"status":"PASS","inferred_story":"A culturally important dress is drawing renewed public attention.","core_message_alignment":"aligned","reason":"The dress moves from intimate reflection to public examination."},"generic_video_test_v2":{"status":"PASS","reusable_for_unrelated_stories":False,"reason":"The reflection-to-public-artifact transition depends on this dress's cultural story."}}

    def test_storyboard_structure_purpose_duration_and_v2_tests(self):
        story, plan, package = self.storyboard()
        result = validate_storyboard(story, plan, package, 10)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(all(result["checks"].values()))

    def test_unsupported_asset_is_rejected(self):
        story, plan, package = self.storyboard()
        package["storyboard"][0]["visual_description"] += " with fabricated archival photographs"
        self.assertFalse(validate_storyboard(story, plan, package, 10)["checks"]["unsupported_assets_rejected"])

    def test_reference_frame_plan_is_prompt_ready(self):
        _, plan, package = self.storyboard()
        reference = build_reference_frame_plan(package["storyboard"][0], plan)
        self.assertEqual(reference["subject"], plan["core_visual_subject"])
        self.assertIn("Reference start frame for S1", reference["prompt_ready_description"])
        self.assertIn("fabricated archival photographs", reference["must_not_generate"])

    def test_storyboard_to_motion_preserves_subject_and_action(self):
        story, visual, package = self.storyboard()
        shot = package["storyboard"][0]
        reference = build_reference_frame_plan(shot, visual)
        content = {"topic":"Diana Revenge Dress auction","category":"Fashion","story_understanding":story,"visual_story_plan":visual,"approved_storyboard_shot":shot,"reference_frame_plan":reference}
        motion = build_motion_plan(content, shot["duration_seconds"])
        self.assertEqual(motion.core_subject, visual["core_visual_subject"])
        self.assertEqual(motion.concrete_visual_action, shot["action"].rstrip("."))
        self.assertEqual(motion.semantic_validation["handoff"]["status"], "PASS")

    def test_quality_plan_uses_story_decided_shot_count(self):
        story, visual, package = self.storyboard()
        refs = [build_reference_frame_plan(shot, visual) for shot in package["storyboard"]]
        content = {"topic":"Diana Revenge Dress auction","category":"Fashion","story_understanding":story,"visual_story_plan":visual,"storyboard":package["storyboard"],"reference_frame_plans":refs}
        production = build_plan(content, 10)
        self.assertEqual(production["duration_strategy"]["source"], "storyboard_director")
        self.assertEqual([shot["duration"] for shot in production["shots"]], [4, 6])
        self.assertTrue(all(shot["motion_debug"]["semantic_validation"]["handoff"]["status"] == "PASS" for shot in production["shots"]))


if __name__ == "__main__":
    unittest.main()
