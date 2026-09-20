import unittest
from pathlib import Path

from generalization_diversity_qc import (
    ROUTE_EVENT_PROCESS,
    ROUTE_PERSON_ACTION,
    ROUTE_PRODUCT_TECH,
    compare_storyboards,
    detect_template_reuse,
    route_story,
    scan_production_special_cases,
    storyboard_signature,
)


class GeneralizationDiversityQCTests(unittest.TestCase):
    def case(self, case_id, story_type, mechanism, camera, purpose="HOOK", route=None):
        subject = f"distinct {case_id} subject"
        return {
            "case_id": case_id,
            "route": route,
            "story_understanding": {"what_happened": f"{subject} reaches a new supported development."},
            "visualizability_analysis": {"story_type": story_type},
            "visual_story_plan": {"core_visual_subject": subject, "hero_payoff": f"The {case_id} development resolves visibly."},
            "storyboard": [
                {
                    "purpose": purpose,
                    "visual_description": f"Article-specific evidence around {subject} becomes visible.",
                    "action": f"{mechanism}: supported action changes the scene.",
                    "environment": f"source-supported {case_id} environment",
                    "camera": camera,
                    "composition": "article-specific composition",
                    "transition_in": "continuous arrival",
                    "transition_out": "match transition",
                }
            ],
        }

    def test_person_action_routing(self):
        self.assertEqual(route_story({}, {"story_type": "PERSON_ACTION"}), ROUTE_PERSON_ACTION)

    def test_product_tech_routing(self):
        story = {"new_development": "A new robot prototype launches."}
        self.assertEqual(route_story(story, {"story_type": "PRODUCT"}), ROUTE_PRODUCT_TECH)

    def test_event_process_routing(self):
        self.assertEqual(route_story({}, {"story_type": "PROCESS"}), ROUTE_EVENT_PROCESS)
        self.assertEqual(
            route_story({"new_development": "A space mission deploys new satellite technology."}, {"story_type": "EVENT"}),
            ROUTE_EVENT_PROCESS,
        )

    def test_cross_story_storyboard_diversity(self):
        cases = [
            self.case("person", "PERSON_ACTION", "PHYSICAL_ACTION", "tracking", route=ROUTE_PERSON_ACTION),
            self.case("product", "PRODUCT", "OBJECT_STATE_TRANSITION", "orbit", route=ROUTE_PRODUCT_TECH),
            self.case("process", "PROCESS", "PROCESS_PROGRESSION", "locked", route=ROUTE_EVENT_PROCESS),
        ]
        result = compare_storyboards(cases)
        self.assertEqual(result["status"], "GENERALIZATION_PASS")
        self.assertTrue(result["different_visual_mechanisms"])

    def test_template_reuse_detection(self):
        left = storyboard_signature(self.case("person", "PERSON_ACTION", "CONTEXT_REVEAL", "close-up then pullback", route=ROUTE_PERSON_ACTION))
        right_case = self.case("product", "PRODUCT", "CONTEXT_REVEAL", "close-up then pullback", route=ROUTE_PRODUCT_TECH)
        right_case["storyboard"][0]["visual_description"] = left["rendered_story_text"]
        right = storyboard_signature(right_case)
        right["rendered_story_text"] = left["rendered_story_text"].replace("person", "product")
        result = detect_template_reuse(left, right)
        self.assertTrue(result["template_reuse_detected"])

    def test_production_code_has_no_diana_special_case(self):
        result = scan_production_special_cases(Path(__file__).resolve().parents[1])
        self.assertEqual(result["status"], "PASS", result["findings"])

    def test_diana_golden_regression_artifacts_remain_locked(self):
        root = Path(__file__).resolve().parents[1]
        final_report = root / "test-output" / "diana-final-editorial-20260920-191918" / "FINAL-EDITORIAL-REPORT.json"
        final_video = root / "test-output" / "diana-final-editorial-20260920-191918" / "diana-final-editorial-10s.mp4"
        self.assertTrue(final_report.is_file())
        self.assertTrue(final_video.is_file())
        self.assertGreater(final_video.stat().st_size, 100_000)
