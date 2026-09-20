import unittest

from generation_router import choose_provider_mode
from provider_capability_routing import ProviderModeObservation, classify_shot_capabilities


FATIMA_S2 = {
    "purpose": "DEVELOPMENT",
    "visual_subject": "adolescent female martial arts performer holding eggs",
    "action": "perform rapid repeated alternating punches continuously while holding eggs",
}


class ProviderCapabilityRoutingTests(unittest.TestCase):
    def observation(self, mode="standard_image_to_video"):
        return ProviderModeObservation(
            provider="pixverse",
            mode=mode,
            shot_capabilities=("HUMAN_REPETITIVE_ACTION", "HUMAN_HIGH_MOTION"),
            attempts=2,
            identity_preservation="strong",
            object_preservation="strong",
            continuity="strong",
            action_execution="failed",
            failure_classification="SHOT_EXECUTION_FAILURE",
        )

    def test_fatima_s2_classifies_as_repetitive_high_motion(self):
        self.assertEqual(
            classify_shot_capabilities(FATIMA_S2),
            ("HUMAN_REPETITIVE_ACTION", "HUMAN_HIGH_MOTION"),
        )

    def test_standard_i2v_is_not_retried_after_two_action_only_failures(self):
        route = choose_provider_mode(FATIMA_S2, [self.observation()], fusion_supported=True)
        self.assertFalse(route["standard_i2v_retry_allowed"])
        self.assertEqual(route["mode"], "fusion_reference_to_video")

    def test_fusion_is_a_single_benchmark_not_assumed_better(self):
        observations = [self.observation(), self.observation("fusion_reference_to_video")]
        route = choose_provider_mode(FATIMA_S2, observations, fusion_supported=True)
        self.assertEqual(route["provider"], "alternate_video_provider")

    def test_without_fusion_support_route_to_alternate_provider(self):
        route = choose_provider_mode(FATIMA_S2, [self.observation()], fusion_supported=False)
        self.assertEqual(route["provider"], "alternate_video_provider")

    def test_pixverse_remains_eligible_without_matching_failure_history(self):
        low_motion = {"visual_subject": "a person", "action": "slowly raises one hand"}
        route = choose_provider_mode(low_motion, [self.observation()], fusion_supported=True)
        self.assertEqual(route["provider"], "pixverse")
        self.assertEqual(route["mode"], "standard_image_to_video")


if __name__ == "__main__":
    unittest.main()
