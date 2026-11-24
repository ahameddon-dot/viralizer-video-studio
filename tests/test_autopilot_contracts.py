import unittest

from pydantic import ValidationError

from autopilot_contracts import KeyframeAnimateRequest, KeyframeGenerateRequest


class AutopilotContractTests(unittest.TestCase):
    def test_fourth_scene_is_valid_for_longer_storyboards(self):
        self.assertEqual(3, KeyframeGenerateRequest(scene_index=3).scene_index)
        self.assertEqual(3, KeyframeAnimateRequest(scene_index=3).scene_index)

    def test_scene_index_still_has_a_safe_upper_bound(self):
        with self.assertRaises(ValidationError):
            KeyframeGenerateRequest(scene_index=21)
        with self.assertRaises(ValidationError):
            KeyframeAnimateRequest(scene_index=21)


if __name__ == "__main__":
    unittest.main()
