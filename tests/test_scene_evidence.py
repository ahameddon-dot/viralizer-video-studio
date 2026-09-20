import unittest

from scene_evidence import (
    MEANING_BEARING_REQUIRES_EVIDENCE,
    REJECTED,
    SAFE_CONTEXTUAL_COMPLETION,
    SOURCE_ASSERTED,
    build_scene_evidence_preflight,
    classify_scene_element,
    collect_source_visual_evidence,
)


class SceneEvidenceTests(unittest.TestCase):
    def authority(self):
        story = {
            "key_visual_facts": ["black strapless Revenge Dress", "single mannequin exhibition display", "public exhibition"],
            "unsupported_visuals": ["crowds", "fabricated documents", "cover-removal action"],
        }
        plan = {
            "core_visual_subject": "black strapless Revenge Dress on a single exhibition mannequin",
            "must_show": ["black strapless Revenge Dress", "single mannequin", "public exhibition"],
            "source_visual_evidence": [],
        }
        return story, plan

    def test_harmless_neutral_environment_completion(self):
        story, plan = self.authority()
        result = classify_scene_element("neutral wall and plain floor", story, plan)
        self.assertEqual(result["classification"], SAFE_CONTEXTUAL_COMPLETION)

    def test_fabricated_event_rejection(self):
        story, plan = self.authority()
        result = classify_scene_element("a worker removes a cover from the dress", story, plan)
        self.assertEqual(result["classification"], REJECTED)

    def test_plausible_meaning_bearing_detail_requires_evidence(self):
        story, plan = self.authority()
        result = classify_scene_element("velvet ropes and auction staff", story, plan)
        self.assertEqual(result["classification"], MEANING_BEARING_REQUIRES_EVIDENCE)

    def test_minimal_context_passes_without_clutter(self):
        story, plan = self.authority()
        shot = {"shot_id":"S1","must_show":["black strapless Revenge Dress", "single mannequin exhibition display"],"environment":"neutral exhibition space, plain floor, neutral wall","foreground":"single mannequin exhibition display","background":"empty negative space","action":"CONTEXT_REVEAL: reveal the public exhibition around the same dress"}
        result = build_scene_evidence_preflight(story, plan, [shot])
        self.assertEqual(result["scene_evidence_status"], "PASS")
        self.assertTrue(result["safe_contextual_completion"])

    def test_source_media_backed_environmental_detail(self):
        story, plan = self.authority()
        plan["source_visual_evidence"] = [{"description":"the dress stands against a blue stone gallery wall", "context_verified":True}]
        result = classify_scene_element("blue stone gallery wall", story, plan, plan["source_visual_evidence"])
        self.assertEqual(result["classification"], SOURCE_ASSERTED)

    def test_unsupported_before_after_state_rejected(self):
        story, plan = self.authority()
        result = classify_scene_element("empty display case transforms and reveals the dress", story, plan)
        self.assertEqual(result["classification"], REJECTED)

    def test_article_supported_context_reveal(self):
        story, plan = self.authority()
        result = classify_scene_element("CONTEXT_REVEAL: reveal the public exhibition around the same Revenge Dress", story, plan)
        self.assertEqual(result["classification"], SOURCE_ASSERTED)

    def test_environmental_clutter_is_not_safe_completion(self):
        story, plan = self.authority()
        result = classify_scene_element("benches, velvet ropes, photographers, and auction furniture", story, plan)
        self.assertEqual(result["classification"], MEANING_BEARING_REQUIRES_EVIDENCE)

    def test_source_visual_evidence_uses_existing_metadata_only(self):
        evidence = collect_source_visual_evidence({"image_captions":["Dress on a mannequin"],"json_ld":{"image":{"url":"https://publisher.example/image.jpg","caption":"Gallery display"}}})
        self.assertEqual(len(evidence), 2)
        self.assertTrue(any(item.get("url") for item in evidence))

    def test_negated_other_objects_does_not_invent_objects(self):
        story, plan = self.authority()
        result = classify_scene_element(
            "Open and uncluttered space without other objects or people.",
            story,
            plan,
        )
        self.assertNotEqual(result["classification"], MEANING_BEARING_REQUIRES_EVIDENCE)

    def test_none_means_no_requested_element(self):
        story, plan = self.authority()
        result = classify_scene_element("None", story, plan)
        self.assertEqual(result["classification"], SAFE_CONTEXTUAL_COMPLETION)


if __name__ == "__main__":
    unittest.main()
