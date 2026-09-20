import tempfile
import unittest
from pathlib import Path

from achievement_representation import analyze_achievement_representation
from generated_text_router import CONTROLLED_OVERLAY_TEXT, SOURCE_UI_TEXT, route_generated_text
from generalization_diversity_qc import scan_production_special_cases
from scene_evidence import (
    MEANING_BEARING_REQUIRES_EVIDENCE,
    SOURCE_ASSERTED,
    build_source_evidence_locks,
    classify_scene_element,
    infer_temporal_status,
)
from scene_evidence_sanitizer import sanitize_storyboard
from story_type_qc import evaluate_story_type_qc


class GeneralizationRemediationTests(unittest.TestCase):
    def test_counted_achievement_routes_count_away_from_generated_objects(self):
        article = {
            "headline": "Teen athlete completes 10 international records",
            "article_body": "She completed 10 international records. In one feat she delivered 340 punches in one minute while holding eggs securely.",
        }
        story = {
            "what_happened": article["article_body"],
            "new_development": "The athlete completed 10 records.",
            "core_message": "A controlled martial-arts performance produced a counted achievement.",
            "key_visual_facts": ["She delivered 340 punches in one minute while holding eggs securely."],
        }
        result = analyze_achievement_representation(article, story)
        self.assertEqual(result["achievement_type"], "COUNTED_ACHIEVEMENT")
        self.assertTrue(result["controlled_text_dependent"])
        self.assertTrue(any("punch" in item.lower() for item in result["visually_demonstrated"]))
        self.assertFalse(result["count_requires_literal_objects"])

    def test_person_action_qc_rejects_generic_award_payoff(self):
        representation = {
            "visually_demonstrated": ["athlete punches rapidly while holding two fragile objects"],
            "controlled_text_dependent": ["10 records"],
        }
        story = {"visualizability_analysis": {"story_type": "PERSON_ACTION"}}
        plan = {"story_type": "PERSON_ACTION", "core_visual_subject": "young martial artist", "achievement_representation": representation}
        storyboard = [{"visual_description": "The athlete poses beside a trophy.", "action": "Camera pushes in.", "purpose": "HERO PAYOFF"}]
        result = evaluate_story_type_qc(storyboard, story, plan)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["checks"]["non_generic_payoff"])

    def test_person_action_qc_accepts_supported_action_payoff_without_visible_count(self):
        representation = {
            "visually_demonstrated": ["athlete punches rapidly while holding two fragile objects"],
            "controlled_text_dependent": ["10 records"],
        }
        story = {"visualizability_analysis": {"story_type": "PERSON_ACTION"}}
        plan = {"story_type": "PERSON_ACTION", "core_visual_subject": "young martial artist", "achievement_representation": representation}
        storyboard = [{"visual_description": "The athlete punches rapidly while holding two fragile objects.", "action": "She completes the sequence; both objects remain intact.", "purpose": "HERO PAYOFF"}]
        self.assertEqual(evaluate_story_type_qc(storyboard, story, plan)["status"], "PASS")

    def test_source_asserted_element_receives_immutable_lock(self):
        story = {"key_visual_facts": ["the original compact device remains beside the new larger device"]}
        plan = {"core_visual_subject": "two research devices", "must_show": ["original compact device", "new larger device"]}
        result = classify_scene_element("the original compact device", story, plan)
        self.assertEqual(result["classification"], SOURCE_ASSERTED)
        self.assertTrue(result["evidence_lock"])
        self.assertEqual(result["semantic_role"], "ORIGINAL_SATELLITE")

    def test_sanitizer_preserves_source_locked_multiple_objects(self):
        story = {"key_visual_facts": ["original compact device", "new larger device"], "unsupported_visuals": []}
        plan = {"core_visual_subject": "original and new research devices", "must_show": ["original compact device", "new larger device"], "must_avoid": []}
        shot = {
            "shot_id": "S1", "purpose": "DEVELOPMENT", "visual_subject": plan["core_visual_subject"],
            "visual_description": "The original compact device sits beside the new larger device.",
            "action": "TEMPORAL_CONTRAST: the original compact device remains beside the new larger device.",
            "environment": "neutral lab", "composition": "both devices side by side", "foreground": "original compact device",
            "background": "new larger device", "important_objects": ["original compact device", "new larger device"],
            "must_show": ["original compact device", "new larger device"],
            "after_viewer_understands": "A newer device follows the original.", "before_viewer_understands": "Two devices are visible.",
        }
        result = sanitize_storyboard(story, plan, {"storyboard": [shot]})
        rendered = str(result["storyboard"][0]).lower()
        self.assertIn("original compact device", rendered)
        self.assertIn("new larger device", rendered)

    def test_unsupported_third_duplicate_is_rejected(self):
        story = {"key_visual_facts": ["original device and new device"]}
        plan = {"core_visual_subject": "two devices", "must_show": ["original device", "new device"]}
        result = classify_scene_element("a third additional device", story, plan)
        self.assertEqual(result["classification"], MEANING_BEARING_REQUIRES_EVIDENCE)

    def test_temporal_status_distinguishes_planned_and_completed(self):
        self.assertEqual(infer_temporal_status("the mission will launch next year"), "PLANNED_FUTURE")
        self.assertEqual(infer_temporal_status("the mission launched last year"), "PAST_CONFIRMED")

    def test_source_lock_records_temporal_and_semantic_fields(self):
        story = {"key_visual_facts": ["the original compact device was launched", "the new larger device will launch next year"]}
        plan = {"must_show": []}
        locks = build_source_evidence_locks(story, plan)
        self.assertEqual(locks[0]["temporal_status"], "PAST_CONFIRMED")
        self.assertEqual(locks[1]["temporal_status"], "PLANNED_FUTURE")
        self.assertTrue(all(item["evidence_lock"] for item in locks))

    def test_unverified_readable_text_routes_to_controlled_overlay(self):
        shots = [{"shot_id": "S1", "visual_description": "Show a timeline label 'Phase-out Announcement' beside 2023.", "action": "", "environment": "", "composition": "", "foreground": "", "background": "", "must_avoid": []}]
        result = route_generated_text(shots, [])
        self.assertTrue(result["controlled_overlay_text"])
        self.assertTrue(all(item["route"] == CONTROLLED_OVERLAY_TEXT for item in result["routes"]))
        self.assertNotIn("2023", result["storyboard"][0]["visual_description"])

    def test_verified_source_ui_text_is_preserved_as_source_pixels(self):
        shots = [{"shot_id": "S1", "visual_description": "Preserve 'Settings' on the interface.", "action": "", "environment": "", "composition": "", "foreground": "", "background": "", "must_avoid": []}]
        media = [{"url": "https://publisher.example/interface.png", "description": "Settings interface", "context_verified": True}]
        result = route_generated_text(shots, media)
        self.assertEqual(result["routes"][0]["route"], SOURCE_UI_TEXT)
        self.assertFalse(result["controlled_overlay_text"])

    def test_event_qc_rejects_planned_event_shown_completed(self):
        lock = {"element": "new research device will launch", "evidence_lock": True, "temporal_status": "PLANNED_FUTURE"}
        story = {"visualizability_analysis": {"story_type": "EVENT"}}
        plan = {"story_type": "EVENT", "source_evidence_locks": [lock]}
        storyboard = [{"visual_description": "The new research device will launch, then is deployed and operational.", "action": "PROCESS_PROGRESSION: completed launch.", "purpose": "HERO PAYOFF"}]
        result = evaluate_story_type_qc(storyboard, story, plan)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["checks"]["planned_not_shown_as_completed"])

    def test_transformation_story_with_temporal_locks_uses_event_qc(self):
        lock = {"element": "new research device will launch", "evidence_lock": True, "semantic_role": "LAUNCH_CONTEXT", "temporal_status": "PLANNED_FUTURE"}
        story = {"visualizability_analysis": {"story_type": "TRANSFORMATION"}}
        plan = {"story_type": "TRANSFORMATION", "source_evidence_locks": [lock]}
        storyboard = [{"visual_description": "Researchers prepare the new device before launch.", "action": "PROCESS_PROGRESSION: the team tests components, then coordinates planned work.", "purpose": "DEVELOPMENT"}]
        result = evaluate_story_type_qc(storyboard, story, plan)
        self.assertEqual(result["story_type"], "TRANSFORMATION")
        self.assertIn("planned_not_shown_as_completed", result["checks"])

    def test_production_code_contains_no_named_fixture_special_case(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(scan_production_special_cases(root)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
