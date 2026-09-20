import unittest

from visual_specificity_analyzer import (
    RAW_ARTICLE_SPECIFICITY_THRESHOLD,
    analyze_visual_specificity,
    evaluate_evidence_relative_specificity,
)


class VisualSpecificityAnalyzerTests(unittest.TestCase):
    def analysis(self, facts, narration=None):
        return {
            "visualizable_facts": facts,
            "narration_dependent_meanings": narration or [],
        }

    def test_visually_distinctive_story_has_high_ceiling(self):
        result = analyze_visual_specificity(
            {"what_happened": "A distinctive red angular prototype vehicle is revealed."},
            self.analysis(["distinctive red angular prototype vehicle", "specific landmark test track"]),
            [{"url": "https://publisher.example/prototype.jpg", "description": "Exact red prototype at the test track", "context_verified": True}],
        )
        self.assertGreaterEqual(result["maximum_visual_specificity"], 90)

    def test_generic_looking_object_has_low_ceiling(self):
        result = analyze_visual_specificity(
            {"what_happened": "A company discusses a plain bottle.", "core_message": "Its reputation changed."},
            self.analysis(["plain bottle"], ["The company's reputation changed."]),
        )
        self.assertLess(result["maximum_visual_specificity"], RAW_ARTICLE_SPECIFICITY_THRESHOLD)

    def test_missed_available_distinctive_visual_anchor(self):
        specificity = {
            "visual_identity_anchors": ["distinctive red angular prototype vehicle", "triangular rear wing"],
            "maximum_visual_specificity": 85,
            "identity_narration_required": False,
        }
        result = evaluate_evidence_relative_specificity(
            [{"visual_description": "A generic silver car drives on a road."}],
            specificity,
            35,
            primary_visual_story_pass=True,
            generic_ad_risk=20,
        )
        self.assertEqual(result["specificity_classification"], "MISSED_VISUAL_SPECIFICITY")
        self.assertFalse(result["specificity_gate_pass"])

    def test_narration_dependent_identity(self):
        result = analyze_visual_specificity(
            {
                "what_happened": "Princess Diana's Revenge Dress returns to public exhibition.",
                "core_message": "It represents empowerment and resilience.",
            },
            self.analysis(
                ["black strapless silk dress", "single mannequin exhibition display"],
                ["Its identity and empowerment history require explanation."],
            ),
        )
        self.assertTrue(result["identity_narration_required"])
        self.assertTrue(result["identity_details_for_narration"])

    def test_source_image_enhances_specificity(self):
        without = analyze_visual_specificity(
            {"what_happened": "A black dress is exhibited."},
            self.analysis(["black strapless silk dress"]),
        )
        with_image = analyze_visual_specificity(
            {"what_happened": "A black dress is exhibited."},
            self.analysis(["black strapless silk dress"]),
            [{"url": "https://publisher.example/dress.jpg", "description": "Exact exhibited dress", "context_verified": True}],
        )
        self.assertGreater(with_image["maximum_visual_specificity"], without["maximum_visual_specificity"])
        self.assertTrue(with_image["source_media_identity_anchors"])

    def test_publisher_navigation_is_not_a_visual_anchor(self):
        result = analyze_visual_specificity(
            {"what_happened": "A new device interface launches."},
            self.analysis(["new split-screen interface", "Read also - There's a New No."]),
        )
        self.assertNotIn("Read also - There's a New No.", result["visual_identity_anchors"])

    def test_low_raw_but_strong_evidence_relative_specificity(self):
        specificity = {
            "visual_identity_anchors": ["black strapless silk dress", "single mannequin exhibition display"],
            "maximum_visual_specificity": 45,
            "identity_narration_required": True,
        }
        result = evaluate_evidence_relative_specificity(
            [{"visual_subject": "black strapless silk dress", "visual_description": "The dress is shown on a single mannequin exhibition display."}],
            specificity,
            30,
            primary_visual_story_pass=True,
            generic_ad_risk=20,
        )
        self.assertTrue(result["specificity_gate_pass"])
        self.assertEqual(result["specificity_classification"], "EVIDENCE_LIMITED_SPECIFICITY")

    def test_genuinely_generic_storyboard_still_fails(self):
        specificity = {
            "visual_identity_anchors": ["black strapless silk dress"],
            "maximum_visual_specificity": 45,
            "identity_narration_required": True,
        }
        result = evaluate_evidence_relative_specificity(
            [{"visual_description": "A black strapless silk dress rotates like a generic advertisement."}],
            specificity,
            30,
            primary_visual_story_pass=True,
            generic_ad_risk=85,
        )
        self.assertFalse(result["specificity_gate_pass"])
        self.assertEqual(result["specificity_classification"], "GENERIC_STORYBOARD")

    def test_global_raw_threshold_is_not_weakened(self):
        self.assertEqual(RAW_ARTICLE_SPECIFICITY_THRESHOLD, 65)
        specificity = {
            "visual_identity_anchors": ["distinctive red prototype vehicle"],
            "maximum_visual_specificity": 90,
            "identity_narration_required": False,
        }
        result = evaluate_evidence_relative_specificity(
            [{"visual_description": "The distinctive red prototype vehicle is shown."}],
            specificity,
            30,
            primary_visual_story_pass=True,
            generic_ad_risk=10,
        )
        self.assertFalse(result["specificity_gate_pass"])


if __name__ == "__main__":
    unittest.main()
