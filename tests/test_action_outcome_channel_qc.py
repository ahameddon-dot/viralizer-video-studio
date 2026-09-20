import json
import unittest

from action_outcome_contract import build_action_outcome_contract
from creative_story_qc import creative_qc_authority, normalize_creative_qc
from editorial_story_layer import allocate_editorial_information
from storyboard_director import build_reference_frame_plan, build_visual_qc_spec
from storyboard_preflight_controls import enforce_storyboard_preflight_controls
from story_type_qc import evaluate_story_type_qc
from visual_generation_control import enrich_storyboard_frames


class ActionOutcomeChannelQCTests(unittest.TestCase):
    def setUp(self):
        self.source_fact = (
            "Fatima held eggs in her hands and delivered 340 punches in one minute, "
            "surpassing the previous record of 331."
        )
        self.contract = build_action_outcome_contract([self.source_fact])
        self.representation = {
            "visually_demonstrated": [self.source_fact],
            "narration_dependent": ["She surpassed the previous record of 331."],
            "controlled_text_dependent": ["10 world records"],
            "forbidden_inventions": ["trophy ceremony", "judges", "scoreboard"],
            "action_outcome_contract": self.contract,
        }
        self.story = {
            "core_message": "A precise physical feat combines speed with control.",
            "viewer_takeaway": "The action is notable because the fragile objects survive the completed feat.",
            "key_visual_facts": [self.source_fact],
            "factual_boundaries": ["Do not invent judges, ceremonies, or awards."],
            "visualizability_analysis": {"story_type": "PERSON_ACTION"},
            "achievement_representation": self.representation,
            "action_outcome_contract": self.contract,
        }
        self.plan = {
            "story_type": "PERSON_ACTION",
            "core_visual_subject": "the martial artist performing the supported feat",
            "visual_style": "grounded sports editorial",
            "must_show": ["the performer", "the same eggs", "the completed punch sequence"],
            "must_avoid": ["trophies", "judges", "badges", "scoreboard"],
            "achievement_representation": self.representation,
            "action_outcome_contract": self.contract,
        }

    def _shots(self, visible_result=True):
        payoff = (
            "After the punch sequence completes, the same eggs remain visibly held "
            "with no visible breakage."
            if visible_result else
            "The performer finishes punching and poses toward the camera."
        )
        return [
            {
                "shot_id": "S1", "purpose": "HOOK",
                "visual_subject": self.plan["core_visual_subject"],
                "visual_description": "The performer holds eggs securely before beginning the punch sequence.",
                "action": "She braces her hands and begins the supported sequence.",
                "environment": "restrained training space", "composition": "hands and stance readable",
                "camera": "steady medium view", "lighting": "neutral editorial light",
                "foreground": "the same eggs", "background": "restrained training wall",
                "must_show": self.plan["must_show"], "must_avoid": self.plan["must_avoid"],
                "continuity_requirements": ["same performer, eggs, wardrobe, and room"],
                "reference_frame_required": True, "duration_seconds": 5,
                "action_outcome_contract": self.contract,
            },
            {
                "shot_id": "S2", "purpose": "HERO PAYOFF",
                "visual_subject": self.plan["core_visual_subject"],
                "visual_description": payoff, "action": payoff,
                "environment": "the same restrained training space", "composition": "close stable proof in the hands",
                "camera": "steady close-up", "lighting": "same neutral editorial light",
                "foreground": "the same eggs", "background": "the same restrained training wall",
                "must_show": self.plan["must_show"], "must_avoid": self.plan["must_avoid"],
                "continuity_requirements": ["same performer, eggs, wardrobe, and room"],
                "reference_frame_required": True, "duration_seconds": 5,
                "action_outcome_contract": self.contract,
            },
        ]

    def _allocation(self):
        visualizability = {
            "visualizable_facts": [self.source_fact],
            "narration_dependent_meanings": ["She surpassed the previous record of 331."],
            "narration_gap": {"viewer_should_understand_visually": [self.source_fact]},
        }
        specificity = {"identity_details_for_narration": ["Fatima"]}
        article = {
            "headline": "Fatima completes 10 world records",
            "article_body": self.source_fact + " She has completed 10 world records.",
        }
        return allocate_editorial_information(self.story, visualizability, specificity, article)

    def _qc_result(self, **overrides):
        value = {
            "viewer_inferred_story": "A martial artist completes a precise punch feat while protecting fragile eggs.",
            "subject_clarity": 92, "story_progression": 86, "article_specificity": 82,
            "visual_impact": 78, "visual_continuity": 90, "narrative_progression": 84,
            "environmental_storytelling": 70, "generic_ad_risk": 12,
            "visual_semantic_coverage": {"overall_score": 88, "communicated": ["supported action", "intact result"], "partial": [], "weak_or_missing": []},
            "visual_channel_coverage": 88,
            "shot_progression": [
                {"shot_id": "S1", "new_meaning": "setup", "adds_new_meaning": True},
                {"shot_id": "S2", "new_meaning": "visible intact result", "adds_new_meaning": True},
            ],
            "fake_information_panel_detected": False,
            "model_final_story_pass": "PASS", "muted_primary_visual_story_pass": "PASS",
            "failure_reasons": [],
            "action_result_qc": {
                "ACTION_CLEAR": "PASS", "ACTION_ARTICLE_SPECIFIC": "PASS", "RESULT_VISIBLE": "PASS",
                "RESULT_MATCHES_EVIDENCE": "PASS", "CAUSE_EFFECT_CLEAR": "PASS", "PAYOFF_NON_GENERIC": "PASS",
            },
        }
        value.update(overrides)
        return value

    def test_action_without_observable_result_fails_person_action_qc(self):
        qc = evaluate_story_type_qc(self._shots(False), self.story, self.plan)
        self.assertEqual(qc["status"], "FAIL")
        self.assertFalse(qc["checks"]["observable_result_payoff"])

    def test_action_with_article_supported_visible_result_passes(self):
        qc = evaluate_story_type_qc(self._shots(True), self.story, self.plan)
        self.assertEqual(qc["status"], "PASS")
        self.assertTrue(qc["checks"]["observable_result_payoff"])

    def test_exact_achievement_count_routes_to_controlled_text(self):
        allocation = self._allocation()
        self.assertIn("10 world records", [item.lower() for item in allocation["text_channel"]])
        self.assertFalse(any("10 world records" in item.lower() for item in allocation["visual_channel"]))

    def test_visual_qc_does_not_fail_for_text_channel_count(self):
        allocation = self._allocation()
        story = dict(self.story, editorial_allocation=allocation)
        plan = dict(self.plan, editorial_allocation=allocation)
        authority = creative_qc_authority(story, plan)
        result = self._qc_result(
            model_final_story_pass="FAIL",
            muted_primary_visual_story_pass="FAIL",
            failure_reasons=["The 10 world records count is not visible."],
        )
        qc = normalize_creative_qc(result, storyboard=self._shots(True), authority=authority)
        self.assertEqual(qc["final_story_pass"], "PASS")
        self.assertNotIn("10 world records", " ".join(qc["failure_reasons"]).lower())

    def test_opponent_context_routes_to_narration_when_not_visual_responsibility(self):
        allocation = self._allocation()
        self.assertTrue(any("previous record" in item.lower() for item in allocation["narration_channel"]))
        self.assertFalse(any("previous record" in item.lower() for item in allocation["visual_channel"]))

    def test_symbolic_achievement_substitutes_are_removed_and_rejected(self):
        shots = self._shots(True)
        shots[-1]["visual_description"] += " Trophy podium and achievement badge appear."
        controlled = enforce_storyboard_preflight_controls(shots, self.story, self.plan)
        positive = json.dumps(controlled, ensure_ascii=False).lower()
        self.assertNotIn("trophy podium", positive)
        self.assertNotIn("achievement badge", positive)
        self.assertIn("symbolic badges", positive)

    def test_payoff_has_result_state_reference_and_qc_contract(self):
        controlled = enforce_storyboard_preflight_controls(self._shots(True), self.story, self.plan)
        enriched = enrich_storyboard_frames(controlled)
        payoff = enriched[-1]
        reference = build_reference_frame_plan(payoff, self.plan)
        qc_spec = build_visual_qc_spec(payoff, reference, self.story, self.plan)
        self.assertIn("no visible breakage", reference["result_state_reference"]["post_action_state"].lower())
        self.assertTrue(qc_spec["action_result_qc_required"])
        self.assertEqual(payoff["continuity_frame_strategy"], "reuse_previous_end_frame_to_build_result_state")

    def test_visual_and_multimodal_coverage_are_separate_stages(self):
        allocation = self._allocation()
        authority = creative_qc_authority(
            dict(self.story, editorial_allocation=allocation),
            dict(self.plan, editorial_allocation=allocation),
        )
        qc = normalize_creative_qc(self._qc_result(), storyboard=self._shots(True), authority=authority)
        self.assertEqual(qc["coverage_stage"], "VISUAL_PRODUCTION_QC")
        self.assertEqual(qc["visual_channel_coverage"], 88)
        self.assertIsNone(qc["narration_channel_coverage"])
        self.assertIsNone(qc["text_channel_coverage"])
        self.assertIsNone(qc["final_multimodal_coverage"])


if __name__ == "__main__":
    unittest.main()
