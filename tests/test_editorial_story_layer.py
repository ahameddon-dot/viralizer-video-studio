import unittest

from editorial_story_layer import (
    allocate_editorial_information,
    build_article_evidence_index,
    build_controlled_text_plan,
    direct_narration,
    multimodal_story_preflight,
)


class EditorialStoryLayerTests(unittest.TestCase):
    def setUp(self):
        self.article = {
            "headline": "Princess Diana's Revenge Dress returns before auction",
            "standfirst": "Princess Diana's iconic Revenge Dress will be on public display before auction at Sotheby's New York on December 9.",
            "article_body": (
                "The black strapless silk evening dress is expected to sell for between $150,000 and $300,000. "
                "Diana chose the bold black dress, creating a lasting image of confidence and resilience."
            ),
        }
        self.story = {
            "core_message": "The Revenge Dress returns to public attention before auction as a symbol of confidence and resilience.",
            "viewer_takeaway": "The garment carries cultural meaning beyond fashion.",
            "key_visual_facts": ["black strapless silk Revenge Dress", "mannequin exhibition display", "public exhibition"],
            "factual_boundaries": ["Do not invent historical claims."],
            "unsupported_visuals": ["Princess Diana recreation"],
        }
        self.visualizability = {
            "visualizable_facts": self.story["key_visual_facts"],
            "partially_visualizable_meanings": ["The dress has cultural significance."],
            "narration_dependent_meanings": ["The dress became a symbol of confidence and resilience."],
            "unsafe_to_visualize_without_source_media": ["Princess Diana recreation"],
            "narration_gap": {
                "viewer_should_understand_visually": self.story["key_visual_facts"],
                "narration_must_explain": ["identity", "confidence and resilience"],
            },
        }
        self.specificity = {
            "visual_identity_anchors": self.story["key_visual_facts"],
            "nonvisual_identity_anchors": ["Princess Diana", "Revenge Dress"],
            "identity_details_for_narration": ["This is Princess Diana's Revenge Dress."],
            "maximum_visual_specificity": 50,
            "identity_narration_required": True,
        }
        self.allocation = allocate_editorial_information(self.story, self.visualizability, self.specificity, self.article)
        evidence = build_article_evidence_index(self.article)
        self.identity_id = next(item["id"] for item in evidence if "public display" in item["excerpt"])
        self.meaning_id = next(item["id"] for item in evidence if "confidence and resilience" in item["excerpt"])
        self.price_id = next(item["id"] for item in evidence if "$150,000" in item["excerpt"])

    def _narration(self, text="Princess Diana's Revenge Dress is on public display.", end=4.0):
        return direct_narration(
            self.article, self.story, [], [{"start": 0, "end": end}], self.allocation, end,
            [{"start": 0, "end": end, "text": text, "supported_by": [self.identity_id], "purpose": "identity"}],
        )

    def _visual_result(self, related=True):
        return {
            "final_story_pass": "FAIL",
            "subject_clarity": 85 if related else 20,
            "visual_continuity": 95,
            "fake_information_panel_detected": False,
            "visual_identity_anchors_used": self.story["key_visual_facts"] if related else [],
            "article_specificity_raw": 40,
        }

    def test_visual_and_narration_information_allocation(self):
        self.assertIn("black strapless silk Revenge Dress", self.allocation["visual_channel"])
        self.assertTrue(any("confidence and resilience" in item for item in self.allocation["narration_channel"]))
        self.assertNotIn("Princess Diana recreation", self.allocation["visual_channel"])

    def test_narration_dependent_identity_is_allocated(self):
        self.assertTrue(any("Princess Diana" in item for item in self.allocation["narration_channel"]))
        self.assertTrue(self.specificity["identity_narration_required"])

    def test_narration_evidence_grounding_passes(self):
        self.assertEqual(self._narration()["status"], "PASS")

    def test_unsupported_narration_is_rejected(self):
        result = self._narration("The dress sold yesterday for $2,000,000.")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["errors"])

    def test_duration_aware_script_fitting_rejects_fast_speech(self):
        result = self._narration("Princess Diana's Revenge Dress is on public display before auction at Sotheby's New York.", 2.0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["timing_fits"])

    def test_controlled_text_requires_factual_grounding(self):
        good = build_controlled_text_plan(
            self.article, self.allocation, 10,
            [{"start": 0, "end": 3, "text": "$150,000–$300,000 estimate", "supported_by": [self.price_id]}],
        )
        bad = build_controlled_text_plan(
            self.article, self.allocation, 10,
            [{"start": 0, "end": 3, "text": "$9,000,000 estimate", "supported_by": [self.price_id]}],
        )
        self.assertEqual(good["status"], "PASS")
        self.assertEqual(bad["status"], "BLOCKED")

    def test_visual_narration_redundancy_allows_planned_identity_reinforcement(self):
        narration = self._narration()
        text = build_controlled_text_plan(
            self.article, self.allocation, 10,
            [{"start": 0, "end": 3, "text": "Princess Diana's Revenge Dress", "supported_by": [self.identity_id]}],
        )
        qc = multimodal_story_preflight(self.story, self.allocation, narration, text, self._visual_result(), self.specificity)
        self.assertFalse(qc["redundancy"]["excessive"])

    def test_multimodal_semantic_coverage_combines_channels(self):
        narration = direct_narration(
            self.article, self.story, [], [], self.allocation, 10,
            [
                {"start": 0, "end": 5, "text": "Princess Diana's Revenge Dress returns to public display before auction.", "supported_by": [self.identity_id], "purpose": "identity and return"},
                {"start": 5, "end": 10, "text": "It remains a fashion symbol of confidence and resilience.", "supported_by": [self.meaning_id], "purpose": "meaning"},
            ],
        )
        text = build_controlled_text_plan(self.article, self.allocation, 10, [])
        qc = multimodal_story_preflight(self.story, self.allocation, narration, text, self._visual_result(), self.specificity)
        self.assertGreaterEqual(qc["core_message_coverage"], 70)

    def test_evidence_limited_supporting_visuals_can_pass(self):
        qc = multimodal_story_preflight(
            self.story, self.allocation, self._narration(),
            build_controlled_text_plan(self.article, self.allocation, 10, []),
            self._visual_result(), self.specificity,
        )
        self.assertEqual(qc["visual_classification"], "EVIDENCE_LIMITED_SUPPORTING_VISUALS")
        self.assertEqual(qc["VISUAL_CHANNEL_PASS"], "PASS")

    def test_unrelated_generic_visuals_still_fail(self):
        qc = multimodal_story_preflight(
            self.story, self.allocation, self._narration(),
            build_controlled_text_plan(self.article, self.allocation, 10, []),
            self._visual_result(False), self.specificity,
        )
        self.assertEqual(qc["visual_classification"], "GENERIC_VISUAL_FAILURE")
        self.assertEqual(qc["VISUAL_CHANNEL_PASS"], "FAIL")


if __name__ == "__main__":
    unittest.main()
