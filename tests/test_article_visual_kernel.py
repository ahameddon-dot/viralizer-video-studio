import inspect
import unittest

import article_visual_kernel as avk
from creative_story_qc import normalize_creative_qc
from motion_director import build_motion_directed_prompt


def case(headline, body, subjects, change, facts, primary):
    article = {"headline": headline, "standfirst": body.split(".")[0], "article_body": body, "extraction_state": "complete"}
    story = {
        "what_happened": body.split(".")[0], "main_subjects": subjects,
        "important_context": "The article describes the state before the reported change.",
        "new_development": change, "core_message": change,
        "viewer_takeaway": change, "key_visual_facts": facts,
        "factual_boundaries": ["Show only supported states and relationships."],
        "unsupported_visuals": ["Invented devices", "fabricated documentary events"],
    }
    visual = {
        "story_type": "OTHER", "visualizable_facts": facts,
        "partially_visualizable_meanings": [], "narration_dependent_meanings": [],
        "unsafe_to_visualize_without_source_media": [], "primary_visual_story": primary,
        "narration_gap": {"visual_story_target": primary, "viewer_should_understand_visually": facts, "narration_must_explain": [], "visual_semantic_coverage_target": 70, "narration_gap_acceptable": True},
    }
    return article, story, visual


class ArticleVisualKernelTests(unittest.TestCase):
    def setUp(self):
        self.sixg = case(
            "India joins 24 countries in global initiative on 6G technology",
            "India joined an international initiative focused on future 6G standards and research. The collaboration links national telecom planning with a wider standards network; deployment is not complete.",
            ["future 6G telecom standards collaboration"],
            "National telecom planning becomes connected to a wider international standards and research network.",
            ["telecom planning connects with an international standards network", "future wireless infrastructure remains in planning"],
            "future wireless planning connecting into a wider standards collaboration network",
        )
        self.cyber = case(
            "Gemini hacked three companies in first known breakout by Google's AI",
            "An AI agent crossed a sandbox security boundary and reached several isolated target environments. Investigators contained the incident and examined the affected systems.",
            ["AI agent security containment incident"],
            "An AI-agent execution path crossed its containment boundary into multiple isolated target environments before containment.",
            ["AI agent path crosses a sandbox boundary", "multiple isolated target environments are affected", "incident containment follows"],
            "an AI-agent execution path crossing a security boundary into isolated targets before containment",
        )

    def kernel(self, fixture):
        return avk.build_article_visual_kernel(*fixture)

    def compile_fixture(self, fixture):
        article, story, visual = fixture
        plan = avk.strengthen_article_visual_plan(article, story, visual, {
            "story_beats": [{"visual": visual["primary_visual_story"]}],
            "must_show": story["key_visual_facts"], "must_avoid": story["unsupported_visuals"],
            "visual_style": "factual editorial",
        }, {})
        kernel = plan["article_visual_kernel"]
        shot = avk.attach_shot_meaning_contracts([{
            "shot_id": "S1", "purpose": "DEVELOPMENT", "visual_subject": plan["core_visual_subject"],
            "visual_description": kernel["visual_story_sentence"],
            "action": f"{plan['selected_visual_mechanism']}: {kernel['visual_story_sentence']}",
            "environment": kernel["location_or_environment_if_supported"][-1],
            "composition": "article-specific focal composition",
            "camera": "follow the selected visual mechanism, then hold on its result",
            "lighting": "stable realistic source-faithful lighting",
            "source_support": kernel["physical_evidence"], "must_show": plan["must_show"],
            "must_avoid": plan["must_avoid"], "continuity_requirements": ["preserve the same subject and spatial relationships"],
            "duration_seconds": 10, "reference_frame_required": True,
        }], plan)[0]
        prompt, debug = build_motion_directed_prompt({
            "topic": article["headline"], "story_understanding": story,
            "visual_story_plan": plan, "approved_storyboard_shot": shot,
            "reference_frame_plan": {},
        }, 10)
        return plan, shot, prompt, debug

    def test_policy_collaboration_story_type_and_system_mechanism(self):
        kernel = self.kernel(self.sixg)
        self.assertEqual(kernel["story_type"], "POLICY_COLLABORATION")
        self.assertEqual(kernel["selected_visual_mechanism"], "SYSTEM_CONNECTION")
        self.assertNotIn("laboratory", kernel["visual_story_sentence"].lower())
        contract = kernel["collaboration_visibility_contract"]
        self.assertTrue(contract["required"])
        self.assertIn("local", contract["local_system"])
        self.assertIn("separate", contract["peer_systems"])
        self.assertIn("coordinated", contract["collaborative_payoff"])

    def test_policy_collaboration_prompt_requires_visible_relationship(self):
        plan, shot, prompt, debug = self.compile_fixture(self.sixg)
        self.assertIn("Collaboration visibility:", prompt)
        self.assertIn("visibly separate", prompt)
        self.assertIn("coordinated multi-system collaboration", prompt)
        self.assertEqual(debug["semantic_validation"]["article_prompt_quality_gate"]["status"], "PASS")

    def test_policy_collaboration_pixel_qc_cannot_pass_without_contract(self):
        plan, shot, prompt, debug = self.compile_fixture(self.sixg)
        result = normalize_creative_qc({
            "subject_clarity": 90, "story_progression": 90, "article_specificity": 90,
            "visual_impact": 90, "visual_continuity": 90, "narrative_progression": 90,
            "environmental_storytelling": 90, "generic_ad_risk": 5, "article_relation": 90,
            "genericity": 5, "visual_evidence_usage": 90, "story_type_match": 90,
            "visual_semantic_coverage": {"overall_score": 90}, "visual_channel_coverage": 90,
            "shot_progression": [], "model_final_story_pass": "PASS",
            "muted_primary_visual_story_pass": "PASS", "narration_gap_acceptable": True,
            "failure_reasons": [],
        }, 70, True, storyboard=[shot], authority={"story_type": "POLICY_COLLABORATION", "editorial_allocation": plan["editorial_channel_allocation"]})
        self.assertEqual(result["policy_collaboration_qc"]["VIEWER_CAN_INFER_COLLABORATION"], "FAIL")
        self.assertEqual(result["final_story_pass"], "FAIL")

    def test_cyber_incident_extracts_boundary_mechanism(self):
        kernel = self.kernel(self.cyber)
        self.assertEqual(kernel["story_type"], "CYBERSECURITY_INCIDENT")
        self.assertEqual(kernel["selected_visual_mechanism"], "BOUNDARY_CROSSING")
        self.assertIn("security boundary", kernel["visual_story_sentence"].lower())

    def test_article_visual_kernel_schema_is_complete(self):
        required = {"article_event", "main_change", "core_visual_subject", "visualizable_action_or_change", "before_state", "after_state", "important_relationships", "physical_evidence", "location_or_environment_if_supported", "temporal_status", "unique_visual_anchors", "nonvisual_facts", "abstract_meanings", "visual_story_sentence"}
        self.assertTrue(required <= self.kernel(self.cyber).keys())

    def test_three_candidates_are_ranked_by_article_relation(self):
        candidates = avk.build_concept_candidates(self.kernel(self.sixg))
        self.assertGreaterEqual(len(candidates), 3)
        self.assertGreaterEqual(candidates[0]["article_visual_relation_score"], candidates[-1]["article_visual_relation_score"])

    def test_category_template_and_generic_tech_lab_are_rejected(self):
        kernel = self.kernel(self.sixg)
        result = avk.article_relation_score("A technology business editorial with scientists in a laboratory while an engineer demonstrates technology.", kernel)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["generic_patterns"])

    def test_generic_cyber_office_is_rejected(self):
        result = avk.article_relation_score("People staring at code screens beside a hoodie hacker and green code rain.", self.kernel(self.cyber))
        self.assertEqual(result["status"], "FAIL")

    def test_unsupported_devices_are_rejected(self):
        result = avk.article_relation_score("A holographic chip powers a futuristic cylinder and fictional scanner.", self.kernel(self.sixg))
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["unsupported_tech_decoration"])

    def test_human_presence_requires_story_justification(self):
        self.assertFalse(self.kernel(self.sixg)["human_presence"]["required"])
        person = case("Athlete completes a record lift", "An athlete lifted the supported weight and completed the feat.", ["athlete"], "The athlete completes the lift.", ["athlete lifts the supported weight"], "athlete completes the supported physical lift")
        self.assertTrue(self.kernel(person)["human_presence"]["required"])

    def test_readable_screen_content_is_routed_out_of_generated_prompt(self):
        plan = {"article_visual_kernel": self.kernel(self.cyber)}
        result = avk.evaluate_final_prompt("Show the AI path crossing the sandbox boundary, then display readable terminal commands.", plan)
        self.assertFalse(result["text_safety"])

    def test_temporal_truth_rejects_planned_as_completed(self):
        kernel = self.kernel(self.sixg); kernel["temporal_status"] = "PLANNED_FUTURE"
        result = avk.evaluate_final_prompt("Show future wireless planning as a fully deployed completed network.", {"article_visual_kernel": kernel})
        self.assertFalse(result["temporal_truth"])

    def test_shot_meaning_contract_requires_new_meaning(self):
        kernel = self.kernel(self.cyber)
        plan = {"article_visual_kernel": kernel, "selected_visual_mechanism": "BOUNDARY_CROSSING", "must_avoid": ["hoodie hacker"]}
        shots = avk.attach_shot_meaning_contracts([{"shot_id": "S1", "visual_description": "The execution path crosses the security boundary.", "source_support": kernel["physical_evidence"]}], plan)
        self.assertNotEqual(shots[0]["viewer_understands_before"], shots[0]["viewer_understands_after"])
        self.assertEqual(avk.evaluate_storyboard_article_relation(shots, plan)["status"], "PASS")

    def test_final_prompt_must_be_story_first(self):
        kernel = self.kernel(self.cyber)
        good = "Create one continuous vertical shot showing an AI execution path crossing a sandbox security boundary into isolated targets."
        bad = "Create a cinematic technology business editorial showing an AI execution path crossing a sandbox security boundary."
        self.assertTrue(avk.evaluate_final_prompt(good, {"article_visual_kernel": kernel})["story_first_ordering"])
        self.assertFalse(avk.evaluate_final_prompt(bad, {"article_visual_kernel": kernel})["story_first_ordering"])

    def test_mixed_story_types_route_to_distinct_mechanisms(self):
        fixtures = [
            case("New phone launches", "A company launched a phone with a folding display.", ["folding phone"], "The folding phone launches with a new display state.", ["folding display opens"], "folding display opens from compact to full state"),
            case("Chef completes precision cut", "A chef cuts one sheet into a precise pattern.", ["chef"], "The chef completes the precise cut.", ["chef cuts the sheet"], "chef cuts and reveals a precise pattern"),
            case("Researchers discover material change", "Researchers discovered a material changing state under pressure.", ["material sample"], "The sample changes state under measured pressure.", ["sample changes state"], "material sample changes state under pressure"),
            case("Company acquires delivery network", "A company acquired a delivery network and connected its distribution operations.", ["distribution operations"], "Two distribution operations become connected.", ["distribution networks connect"], "distribution networks become operationally connected"),
        ]
        kernels = [self.kernel(item) for item in fixtures]
        self.assertEqual(kernels[1]["story_type"], "PERSON_ACTION")
        self.assertEqual(kernels[3]["story_type"], "BUSINESS_CHANGE")
        mechanisms = {kernel["selected_visual_mechanism"] for kernel in kernels}
        self.assertGreaterEqual(len(mechanisms), 4)

    def test_mixed_story_set_compiles_article_specific_pixverse_prompts(self):
        fixtures = [
            self.sixg, self.cyber,
            case("New phone launches", "A company launched a phone with a folding display.", ["folding phone"], "The folding phone launches with a new display state.", ["folding display opens"], "folding display opens from compact to full state"),
            case("Chef completes precision cut", "A chef cuts one sheet into a precise pattern.", ["chef"], "The chef completes the precise cut.", ["chef cuts the sheet"], "chef cuts and reveals a precise pattern"),
            case("Researchers discover material change", "Researchers discovered a material changing state under pressure.", ["material sample"], "The sample changes state under measured pressure.", ["sample changes state"], "material sample changes state under pressure"),
            case("Company acquires delivery network", "A company acquired a delivery network and connected its distribution operations.", ["distribution operations"], "Two distribution operations become connected.", ["distribution networks connect"], "distribution networks become operationally connected"),
        ]
        for fixture in fixtures:
            with self.subTest(article=fixture[0]["headline"]):
                plan, shot, prompt, debug = self.compile_fixture(fixture)
                self.assertEqual(debug["semantic_validation"]["article_prompt_quality_gate"]["status"], "PASS")
                self.assertGreaterEqual(plan["article_visual_relation"]["score"], 60)
                self.assertIn(plan["selected_visual_mechanism"], prompt)
                self.assertTrue(shot["new_article_meaning_added"])
                self.assertNotIn("team member demonstrates", prompt.lower())

    def test_example_names_are_not_hard_coded_in_production_module(self):
        source = inspect.getsource(avk).lower()
        for forbidden in ("gemini", "google", "india", "akashvani", "6g"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
