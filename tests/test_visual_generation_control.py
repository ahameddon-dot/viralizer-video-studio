import os
import unittest
from unittest.mock import patch

from visual_generation_control import (
    OpenAIReferenceImageProvider,
    PixVerseProvider,
    assembly_eligibility,
    build_reference_qc_spec,
    compile_reference_prompt,
    continuity_preflight,
    continuity_qc_spec,
    enrich_storyboard_frames,
    qc_decision,
    regeneration_scope,
)


def shot(shot_id="S1"):
    return {
        "shot_id": shot_id,
        "visual_subject": "Princess Diana's black strapless Revenge Dress",
        "visual_description": "A narrow gallery light travels across the dress and reveals its silhouette.",
        "action": "A narrow gallery light travels across the dress.",
        "environment": "a factual public gallery display",
        "composition": "dress centered against restrained gallery depth",
        "camera": "one slow controlled push-in",
        "lighting": "one narrow gallery spotlight",
        "must_show": ["the black silk dress", "the gallery display"],
        "must_avoid": ["Princess Diana reenactment", "fabricated archival photographs"],
    }


def reference():
    return {
        "shot_id": "S1",
        "subject": "Princess Diana's black strapless Revenge Dress",
        "environment": "a factual public gallery display",
        "composition": "dress centered against restrained gallery depth",
        "camera_position": "one slow controlled push-in",
        "lens_feel": "natural perspective",
        "lighting": "one narrow gallery spotlight",
        "wardrobe_or_materials": "black silk; exact strapless geometry",
        "important_objects": ["the black silk dress", "the gallery display"],
        "spatial_relationships": ["dress in front of restrained gallery depth"],
        "visual_style": "factual museum-fashion editorial",
        "must_preserve": ["dress geometry", "black silk material"],
        "must_not_generate": ["Princess Diana reenactment", "fabricated archival photographs"],
    }


class FakePixVerse:
    def __init__(self):
        self.calls = []

    async def upload_image(self, **kwargs):
        self.calls.append(("upload", kwargs)); return 77

    async def generate_from_image(self, image_id, prompt, **kwargs):
        self.calls.append(("image", image_id, prompt, kwargs)); return 88

    async def generate(self, prompt, **kwargs):
        self.calls.append(("text", prompt, kwargs)); return 99


class VisualGenerationControlTests(unittest.IsolatedAsyncioTestCase):
    def test_reference_prompt_is_composition_only_and_preserves_authority(self):
        item = shot(); item["start_frame"] = "The same dress is partially visible in near-shadow."
        prompt = compile_reference_prompt(item, reference(), ["Do not depict Diana wearing the dress"], item["visual_subject"])
        self.assertIn("Reference start frame for S1", prompt)
        self.assertIn("Core Visual Subject: Princess Diana's black strapless Revenge Dress", prompt)
        self.assertIn("Factual Boundaries", prompt)
        self.assertNotIn("slow controlled push-in", prompt.lower())

    def test_reference_qc_contract_contains_all_hard_checks(self):
        spec = build_reference_qc_spec(shot(), reference(), ["Do not invent an auction event"])
        for key in ("core_subject_present", "composition_match", "material_or_wardrobe_match", "environment_match", "important_objects_present", "forbidden_objects_absent", "factual_boundaries_respected", "no_generated_readable_text", "no_unauthorized_logos", "no_subject_duplication", "no_geometry_or_anatomy_failure"):
            self.assertIn(key, spec)

    def test_reference_qc_requires_available_explicit_pass_and_score(self):
        self.assertEqual(qc_decision({"available": True, "decision": "PASS", "overall_quality_score": 91})["status"], "PASS")
        self.assertEqual(qc_decision({"available": True, "decision": "REGENERATE", "overall_quality_score": 91})["status"], "REGENERATE")
        self.assertEqual(qc_decision({"available": False, "reason": "offline"})["status"], "BLOCKED")

    def test_previous_end_becomes_next_start(self):
        items = enrich_storyboard_frames([shot("S1"), shot("S2"), shot("S3")])
        self.assertEqual(items[1]["start_frame"], items[0]["end_frame"])
        self.assertTrue(items[1]["reuse_previous_end_frame"])
        self.assertEqual(items[2]["continuity_frame_strategy"], "reuse_previous_end_frame")

    def test_reference_provider_reports_real_configuration(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "OPENAI_IMAGE_MODEL": "gpt-image-2"}, clear=False):
            caps = OpenAIReferenceImageProvider().capabilities
        self.assertTrue(caps.supports_generation)
        self.assertTrue(caps.supports_reference_edit)
        self.assertEqual(caps.model, "gpt-image-2")

    def test_pixverse_capabilities_are_documented_only(self):
        caps = PixVerseProvider(FakePixVerse()).capabilities
        self.assertTrue(caps.supports_text_to_video)
        self.assertTrue(caps.supports_image_to_video)
        self.assertTrue(caps.supports_start_frame)
        self.assertFalse(caps.supports_end_frame)
        self.assertFalse(caps.supports_audio)
        self.assertEqual(caps.supported_durations, (5, 8, 10))

    async def test_pixverse_adapter_uses_image_to_video_for_start_reference(self):
        client = FakePixVerse(); provider = PixVerseProvider(client)
        result = await provider.generate_shot(motion_prompt="approved motion", text_prompt="fallback", start_reference=b"png", end_reference=None, duration=5, aspect_ratio="9:16", quality="720p", negative_prompt="text")
        self.assertEqual(result["mode"], "image_to_video")
        self.assertEqual(result["video_id"], 88)
        self.assertEqual([call[0] for call in client.calls], ["upload", "image"])

    async def test_pixverse_adapter_rejects_unsupported_end_frame(self):
        with self.assertRaisesRegex(ValueError, "does not support an end-frame"):
            await PixVerseProvider(FakePixVerse()).generate_shot(motion_prompt="m", text_prompt="t", start_reference=b"start", end_reference=b"end", duration=5, aspect_ratio="9:16", quality="720p", negative_prompt="n")

    def test_continuity_contract_and_preflight(self):
        items = enrich_storyboard_frames([shot("S1"), shot("S2")])
        self.assertEqual(continuity_preflight(items[0], items[1])["status"], "PASS")
        self.assertEqual(continuity_qc_spec(items[0], items[1])["failure_action"], "REGENERATE NEXT SHOT")

    def test_regeneration_is_limited_to_failed_shot(self):
        retry = regeneration_scope("S2", "continuity_qc", "match the previous ending")
        self.assertEqual(retry, {"action": "REGENERATE_SHOT", "shot_id": "S2", "failed_gate": "continuity_qc", "correction": "match the previous ending"})

    def test_motion_runner_accepts_legitimate_not_applicable_semantic_gate(self):
        from long_video import _motion_preflight_passes
        self.assertTrue(_motion_preflight_passes({
            "preflight_consistency": {"status": "PASS"},
            "motion_semantic_qc": "NOT_APPLICABLE",
        }))
        self.assertFalse(_motion_preflight_passes({
            "preflight_consistency": {"status": "PASS"},
            "motion_semantic_qc": "FAIL",
        }))
        self.assertFalse(_motion_preflight_passes({
            "preflight_consistency": {"status": "FAIL"},
            "motion_semantic_qc": "PASS",
        }))

    def test_final_assembly_blocks_any_failed_gate(self):
        passed = {"shot_id": "S1", "reference_qc": "PASS", "motion_semantic_qc": "PASS", "shot_visual_qc": "PASS", "continuity_qc": "PASS"}
        failed = {**passed, "shot_id": "S2", "shot_visual_qc": "REGENERATE"}
        self.assertTrue(assembly_eligibility([passed])["eligible"])
        result = assembly_eligibility([passed, failed])
        self.assertFalse(result["eligible"])
        self.assertIn("S2:shot_visual_qc", result["failures"])


if __name__ == "__main__":
    unittest.main()
