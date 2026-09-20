import copy
import unittest

from scene_evidence import build_scene_evidence_preflight
from scene_evidence_sanitizer import (
    only_scene_clutter_failed,
    sanitize_if_simple_clutter,
    sanitize_storyboard,
)


class SceneEvidenceSanitizerTests(unittest.TestCase):
    def authority(self):
        story = {
            "key_visual_facts": [
                "black strapless silk Revenge Dress",
                "single mannequin exhibition display",
                "public exhibition",
            ],
            "unsupported_visuals": ["crowds", "fabricated documents"],
        }
        plan = {
            "core_visual_subject": "black strapless silk Revenge Dress displayed on a single mannequin",
            "must_show": ["black strapless silk dress", "single mannequin", "gallery environment"],
            "must_avoid": ["crowds", "text"],
            "source_visual_evidence": [],
        }
        return story, plan

    def shot(self, **changes):
        shot = {
            "shot_id": "S1",
            "purpose": "CONTEXT",
            "visual_subject": "black strapless silk Revenge Dress displayed on a single mannequin",
            "visual_description": "The dress stands on one mannequin in a gallery with additional empty mannequins.",
            "action": "CONTEXT_REVEAL: reveal the public exhibition around the same dress.",
            "environment": "neutral gallery with additional empty mannequins",
            "composition": "dress centered against a neutral wall",
            "foreground": "single mannequin and dress",
            "background": "additional empty mannequins",
            "important_objects": ["black dress", "additional empty mannequins"],
            "must_show": ["black strapless silk dress", "single mannequin display"],
            "before_viewer_understands": "The dress is visible.",
            "after_viewer_understands": "The dress is publicly exhibited.",
        }
        shot.update(changes)
        return shot

    def test_removable_unsupported_prop(self):
        story, plan = self.authority()
        result = sanitize_storyboard(story, plan, {"storyboard": [self.shot()]})
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(any("mannequin" in item.lower() for item in result["removed_elements"]))

    def test_neutral_replacement(self):
        story, plan = self.authority()
        result = sanitize_storyboard(story, plan, {"storyboard": [self.shot()]})
        self.assertIn("empty negative space", str(result["storyboard"][0]).lower())

    def test_source_supported_element_preserved(self):
        story, plan = self.authority()
        result = sanitize_storyboard(story, plan, {"storyboard": [self.shot()]})
        rendered = str(result["storyboard"][0]).lower()
        self.assertIn("black strapless silk", rendered)
        self.assertIn("single mannequin", rendered)

    def test_meaning_preserving_sanitization(self):
        story, plan = self.authority()
        original = self.shot()
        result = sanitize_storyboard(story, plan, {"storyboard": [original]})
        sanitized = result["storyboard"][0]
        self.assertTrue(result["meaning_preserved"])
        self.assertEqual(original["purpose"], sanitized["purpose"])
        self.assertEqual(original["after_viewer_understands"], sanitized["after_viewer_understands"])

    def test_sanitization_blocked_when_removal_destroys_meaning(self):
        story, plan = self.authority()
        shot = self.shot(
            action="PHYSICAL_ACTION: a worker removes a protective cover",
            visual_description="A worker removes a protective cover.",
            environment="neutral gallery",
            background="plain wall",
        )
        result = sanitize_storyboard(story, plan, {"storyboard": [shot]})
        self.assertEqual(result["status"], "SANITIZATION_BLOCKED")

    def test_no_creative_revision_consumed_for_simple_clutter(self):
        story, plan = self.authority()
        package = {"storyboard": [self.shot()], "creative_revision_count": 2}
        before = copy.deepcopy(package)
        validation = {
            "status": "FAIL",
            "checks": {
                "storyboard_structure": True,
                "unsupported_assets_rejected": False,
                "scene_evidence_status": False,
            },
        }
        self.assertTrue(only_scene_clutter_failed(validation))
        result = sanitize_if_simple_clutter(story, plan, package, validation)
        self.assertFalse(result["creative_revision_consumed"])
        self.assertEqual(package["creative_revision_count"], before["creative_revision_count"])

    def test_clean_scene_passes_factual_preflight(self):
        story, plan = self.authority()
        result = sanitize_storyboard(story, plan, {"storyboard": [self.shot()]})
        preflight = build_scene_evidence_preflight(story, plan, result["storyboard"])
        self.assertEqual(preflight["scene_evidence_status"], "PASS")
        self.assertFalse(preflight["meaning_bearing_unsupported_elements"])
        self.assertFalse(preflight["fabricated_event_elements"])

    def test_generic_unsupported_detail_preserves_source_context(self):
        story = {"key_visual_facts": ["Arsenal players on a football pitch"]}
        plan = {"core_visual_subject": "Arsenal players", "must_show": ["players", "football pitch"]}
        shot = {
            "shot_id": "S1", "purpose": "CONTEXT", "visual_subject": "Arsenal players",
            "visual_description": "Arsenal players on a football pitch beside an unsupported decorative crest sculpture.",
            "action": "CONTEXT_REVEAL: players continue moving on the pitch.",
            "environment": "football pitch beside an unsupported decorative crest sculpture",
            "composition": "players remain the focal subject", "foreground": "players",
            "background": "unsupported decorative crest sculpture", "important_objects": [],
            "must_show": ["players", "football pitch"],
            "before_viewer_understands": "Players are visible.",
            "after_viewer_understands": "The story concerns Arsenal on the pitch.",
        }
        result = sanitize_storyboard(story, plan, {"storyboard": [shot]})
        rendered = str(result["storyboard"][0]).lower()
        self.assertIn("source-supported context", rendered)
        self.assertNotIn("neutral background", rendered)


if __name__ == "__main__":
    unittest.main()
