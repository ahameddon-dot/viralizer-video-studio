import unittest

from creative_revision_director import (
    apply_revision_to_visual_plan,
    classify_creative_failure,
    revision_limit,
    route_revision,
    validate_revision,
)


def valid_revision():
    return {
        "failure_diagnosis": ["The sequence repeats the display without adding meaning."],
        "preserve": ["the exact core visual subject"],
        "remove": ["repeated wider product views"],
        "change": ["make the environment reveal a new article-specific relationship"],
        "missing_meanings": ["renewed public attention"],
        "new_visual_mechanism": "The article-specific subject crosses a visual threshold from concealed private space into an open public presentation.",
        "revised_hook": "A physical foreground obstruction conceals most of the subject before clearing.",
        "revised_story_beats": [
            {"purpose": "HOOK", "visual": "The article-specific subject is partly concealed by a real foreground boundary.", "before_viewer_understands": "An unknown object is concealed.", "after_viewer_understands": "This particular subject has been held out of view."},
            {"purpose": "DEVELOPMENT", "visual": "The boundary clears into the source-supported public setting.", "before_viewer_understands": "The subject was concealed.", "after_viewer_understands": "The subject is now returning to public attention."},
            {"purpose": "HERO PAYOFF", "visual": "The opened space frames the unchanged subject as the visual authority.", "before_viewer_understands": "The subject has returned.", "after_viewer_understands": "Its significance extends beyond decorative display."},
        ],
        "revised_continuity_strategy": "Preserve subject identity while the physical environment changes meaning.",
        "revised_hero_payoff": "The unchanged subject holds an open, authoritative public composition.",
        "expected_viewer_inference": "A meaningful subject once concealed is returning to public attention with renewed significance.",
    }


class CreativeRevisionDirectorTests(unittest.TestCase):
    def test_real_diana_v2_metrics_route_to_creative_revision(self):
        qc = {"available": True, "visual_continuity": 100, "story_progression": 35, "narrative_progression": 30, "visual_semantic_coverage": {"overall_score": 50}, "environmental_storytelling": 50, "article_specificity": 25, "generic_ad_risk": 70, "fake_information_panel_detected": True}
        failures = classify_creative_failure(qc)
        self.assertIn("STORYBOARD_FAILURE", failures)
        self.assertIn("SEMANTIC_COVERAGE_FAILURE", failures)
        self.assertIn("GENERIC_VIDEO_FAILURE", failures)
        route = route_revision(failures)
        self.assertEqual(route["repair_layer"], "CREATIVE_REVISION_DIRECTOR")
        self.assertFalse(route["reuse_prior_references"])

    def test_technical_failure_routes_to_failed_shots_only(self):
        route = route_revision(["TECHNICAL_GENERATION_FAILURE"])
        self.assertEqual(route["regenerate"], "FAILED_SHOTS_ONLY")
        self.assertTrue(route["reuse_prior_references"])

    def test_continuity_failure_routes_to_adjacent_shots(self):
        self.assertEqual(route_revision(["CONTINUITY_FAILURE"])["regenerate"], "ADJACENT_AFFECTED_SHOTS")

    def test_revision_requires_new_meaning_per_beat(self):
        revision = valid_revision()
        revision["revised_story_beats"][1]["after_viewer_understands"] = revision["revised_story_beats"][1]["before_viewer_understands"]
        result = validate_revision(revision)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["checks"]["meaning_added_per_beat"])

    def test_revision_rejects_unsupported_visuals(self):
        revision = valid_revision(); revision["revised_hook"] = "A fabricated archival photograph fills the frame."
        self.assertFalse(validate_revision(revision, ["fabricated archival photograph"])["checks"]["factual_boundaries_respected"])

    def test_apply_revision_preserves_semantic_subject_and_message(self):
        original = {"core_visual_subject": "approved exact subject", "visual_message": "approved message", "selected_creative_concept": "weak concept"}
        revised = apply_revision_to_visual_plan(original, valid_revision())
        self.assertEqual(revised["core_visual_subject"], "approved exact subject")
        self.assertEqual(revised["visual_message"], "approved message")
        self.assertNotEqual(revised["selected_creative_concept"], "weak concept")

    def test_revision_limit_is_small_and_capped(self):
        self.assertEqual(revision_limit(99), 2)
        self.assertEqual(revision_limit(-4), 0)
        self.assertEqual(revision_limit("invalid"), 2)


if __name__ == "__main__":
    unittest.main()
