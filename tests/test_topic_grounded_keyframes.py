import unittest

from topic_prompt_grounding import topic_grounded_keyframe_prompt


class TopicGroundedKeyframePromptTests(unittest.TestCase):
    def test_trailer_is_metadata_not_a_literal_film_reel(self):
        prompt = topic_grounded_keyframe_prompt(
            {
                "title": "MARVEL'S AVENGERS 5: DOOMSDAY Official Trailer 2 (2026)",
                "hook": "A multiverse conflict puts the heroes against an armored mastermind.",
            },
            {"visual": "A fractured portal reveals the scale of the approaching conflict."},
            "Vertical cinematic explanatory frame.",
        )
        self.assertIn("MARVEL'S AVENGERS 5: DOOMSDAY", prompt)
        self.assertIn("source-format metadata", prompt)
        self.assertIn("Do not show a film reel", prompt)
        self.assertIn("fractured portal", prompt)

    def test_empty_context_preserves_original_prompt(self):
        self.assertEqual("Original prompt", topic_grounded_keyframe_prompt({}, {}, "Original prompt"))


if __name__ == "__main__":
    unittest.main()
