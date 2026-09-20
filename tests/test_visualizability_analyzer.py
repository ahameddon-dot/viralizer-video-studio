import unittest

from creative_story_qc import creative_qc_authority, normalize_creative_qc
from storyboard_director import validate_storyboard
from visualizability_analyzer import analyze_visualizability, classify_story_type, symbolism_is_supported


class VisualizabilityAnalyzerTests(unittest.TestCase):
    def story(self, **updates):
        value = {
            "what_happened": "A historically important black dress returns to public exhibition before auction.",
            "new_development": "The dress is returning to public view.",
            "core_message": "The dress is an enduring symbol of empowerment and resilience.",
            "viewer_takeaway": "Its cultural meaning exceeds fashion.",
            "key_visual_facts": ["black strapless dress", "mannequin exhibition display", "public exhibition before auction"],
            "factual_boundaries": ["Do not recreate historical people."],
            "unsupported_visuals": ["Princess Diana recreation", "fake archival photograph"],
        }
        value.update(updates)
        return value

    def test_object_significance_story(self):
        result = analyze_visualizability(self.story())
        self.assertEqual(result["story_type"], "OBJECT_SIGNIFICANCE")
        self.assertIn("black strapless dress", result["visualizable_facts"])

    def test_person_action_story(self):
        story = self.story(what_happened="A chef lifts the finished dish and places it on the counter.", new_development="The chef opens the oven and serves the dish.", core_message="A chef completes the recipe.", viewer_takeaway="The dish is ready.", key_visual_facts=["chef opens oven", "chef places dish on counter"])
        self.assertEqual(classify_story_type(story), "PERSON_ACTION")

    def test_person_action_outranks_location_words(self):
        story = self.story(
            what_happened="Fatima Naseem completes ten world records in Pakistan.",
            new_development="The athlete completes the tenth record.",
            core_message="The athlete achieves a record milestone.",
            viewer_takeaway="Her physical achievement is the story.",
        )
        self.assertEqual(classify_story_type(story), "PERSON_ACTION")

    def test_person_action_outranks_becomes_transformation_word(self):
        story = self.story(
            what_happened="Fatima completes ten records and becomes the first athlete to do so.",
            new_development="She completes the final punching challenge.",
            core_message="A person achieves a physical record.",
            viewer_takeaway="The completed action is the achievement.",
        )
        self.assertEqual(classify_story_type(story), "PERSON_ACTION")

    def test_interface_development_routes_as_product(self):
        story = self.story(
            what_happened="GM unveils a new vehicle interface and infotainment technology.",
            new_development="The interface launches in a new vehicle.",
            core_message="The product integrates two systems.",
            viewer_takeaway="The device interface changes.",
        )
        self.assertEqual(classify_story_type(story), "PRODUCT")

    def test_space_mission_routes_as_event(self):
        story = self.story(
            what_happened="A university launches a new space mission with a nanosatellite.",
            new_development="The mission progresses from a first cube satellite to a new collaboration.",
            core_message="The space mission enters a new phase.",
            viewer_takeaway="A scientific mission is changing over time.",
        )
        self.assertEqual(classify_story_type(story), "EVENT")

    def test_llm_place_label_yields_to_clear_mission_event(self):
        story = self.story(
            what_happened="A university launches a new space mission.",
            new_development="The scientific mission enters a new phase.",
            core_message="The mission progresses.",
            viewer_takeaway="The process changes over time.",
        )
        result = analyze_visualizability(story)
        from visualizability_analyzer import normalize_visualizability
        normalized = normalize_visualizability({"story_type": "PLACE"}, story)
        self.assertEqual(result["story_type"], "EVENT")
        self.assertEqual(normalized["story_type"], "EVENT")

    def test_criticism_and_decision_move_out_of_visual_facts(self):
        story = self.story(
            key_visual_facts=[
                "a split-screen vehicle interface",
                "the company listened to criticism and reversed its decision",
            ]
        )
        result = analyze_visualizability(story)
        self.assertIn("a split-screen vehicle interface", result["visualizable_facts"])
        self.assertNotIn("the company listened to criticism and reversed its decision", result["visualizable_facts"])

    def test_process_story(self):
        story = self.story(what_happened="The factory shows how recycled fibre moves through the manufacturing process.", core_message="The process converts waste into fabric.")
        self.assertEqual(classify_story_type(story), "PROCESS")

    def test_abstract_meaning_moves_to_narration_gap(self):
        result = analyze_visualizability(self.story())
        self.assertTrue(result["narration_dependent_meanings"])
        self.assertTrue(result["narration_gap"]["narration_gap_acceptable"])
        self.assertIn("public exhibition", result["visualizable_facts"])
        self.assertNotIn("before auction", " ".join(result["visualizable_facts"]).lower())
        self.assertIn("auction", " ".join(result["narration_dependent_meanings"]).lower())

    def test_unsupported_metaphor_rejected(self):
        result = analyze_visualizability(self.story())
        self.assertFalse(symbolism_is_supported("A crown-shaped shadow appears behind the dress.", result))

    def test_object_story_accepts_context_reveal_without_person_action(self):
        story = self.story(); analysis = analyze_visualizability(story); story["visualizability_analysis"] = analysis
        plan = {"core_visual_subject":"the black strapless dress", "visualizability_analysis":analysis, "story_type":"OBJECT_SIGNIFICANCE", "must_avoid":story["unsupported_visuals"]}
        shot = {"shot_id":"S1","purpose":"CONTEXT","source_support":["public exhibition before auction"],"visual_subject":"the black strapless dress","visual_description":"The enclosing exhibition architecture becomes visible around the same dress.","action":"CONTEXT_REVEAL: The gallery entrance and complete exhibition bay emerge around the stationary dress, establishing renewed public presentation.","environment":"public gallery","composition":"dress anchored inside the revealed exhibition bay","camera":"restrained pullback","lighting":"stable gallery light","foreground":"clear floor","background":"gallery entrance without text","transition_in":"begin on the dress","transition_out":"settle on the full display context","continuity_requirements":["same dress and mannequin"],"must_show":["dress","exhibition bay"],"must_avoid":story["unsupported_visuals"],"duration_seconds":10,"reference_frame_required":True}
        package = {"storyboard":[shot],"muted_test_v2":{"status":"PASS"},"generic_video_test_v2":{"status":"PASS","reusable_for_unrelated_stories":False}}
        self.assertTrue(validate_storyboard(story, plan, package, 10)["checks"]["article_specific_visual_progression"])

    def test_acceptable_narration_gap_does_not_force_full_core_message(self):
        story = self.story(); analysis = analyze_visualizability(story)
        authority = creative_qc_authority(story, {"visual_message":analysis["primary_visual_story"], "visualizability_analysis":analysis, "narration_gap":analysis["narration_gap"]})
        self.assertTrue(authority["narration_gap_acceptable"])
        self.assertTrue(authority["narration_must_explain"])

    def test_weak_primary_visual_story_still_fails(self):
        result = normalize_creative_qc({"subject_clarity":90,"story_progression":80,"article_specificity":80,"visual_impact":80,"visual_continuity":90,"narrative_progression":80,"environmental_storytelling":80,"generic_ad_risk":10,"visual_semantic_coverage":{"overall_score":20},"shot_progression":[],"fake_information_panel_detected":False,"model_final_story_pass":"PASS","muted_primary_visual_story_pass":"PASS"}, 60, True)
        self.assertEqual(result["final_story_pass"], "FAIL")


if __name__ == "__main__":
    unittest.main()
