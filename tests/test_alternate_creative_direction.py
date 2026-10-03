import unittest

from app import _creatorthon_user_variation, _creatorthon_variation_narration, apply_selected_alternate_direction
from pixverse_client import build_video_prompt


class AlternateCreativeDirectionTests(unittest.TestCase):
    def base_content(self):
        return {
            "topic": "Three siblings build a growing beauty brand",
            "category": "Beauty",
            "story_understanding": {
                "core_message": "Three siblings combine different skills to grow one beauty brand.",
                "factual_boundaries": ["Do not invent people, products, or endorsements."],
                "unsupported_visuals": ["invented celebrity endorsement"],
            },
            "visual_story_plan": {
                "core_visual_subject": "three siblings working together on their beauty products",
                "visual_message": "Their different roles combine into one coordinated product launch.",
                "story_beats": [{"visual": "The siblings coordinate product preparation and presentation."}],
                "must_show": ["three siblings", "beauty products", "coordinated work"],
                "must_avoid": ["unrelated luxury showroom"],
                "visual_style": "factual beauty-business editorial",
            },
            "selected_alternate_concept": "Hero reveal",
        }

    def test_selected_alternate_becomes_authoritative_shot(self):
        content = self.base_content()
        direction = "Open on a finished bottle detail, then reveal all three siblings coordinating the launch."
        result = apply_selected_alternate_direction(content, direction)
        self.assertEqual(result["current_story_beat"], f"Hero reveal: {direction}")
        self.assertIn("pullback", result["alternate_camera_direction"])
        self.assertIn("three siblings", result["alternate_must_show"])

    def test_different_alternates_compile_to_different_prompts(self):
        hero = self.base_content()
        human = self.base_content()
        human["selected_alternate_concept"] = "Human impact"
        hero_direction = "Open on a finished bottle detail, then reveal all three siblings coordinating the launch."
        human_direction = "Follow one sibling handing prepared products to the others, ending on their shared reaction."
        hero_prompt = build_video_prompt(
            apply_selected_alternate_direction(hero, hero_direction),
            10,
            user_prompt=hero_direction,
        )
        human_prompt = build_video_prompt(
            apply_selected_alternate_direction(human, human_direction),
            10,
            user_prompt=human_direction,
        )
        self.assertNotEqual(hero_prompt, human_prompt)
        self.assertIn("pullback", hero_prompt.lower())
        self.assertIn("eye-level tracking", human_prompt.lower())

    def test_same_topic_gets_stable_but_diverse_user_variations(self):
        topic = {"topic": "Macy's Unveils Its 2026 Fall Fashion Campaign"}
        first = _creatorthon_user_variation("user-1", topic)
        self.assertEqual(first, _creatorthon_user_variation("user-1", topic))
        variations = {_creatorthon_user_variation(f"user-{index}", topic)["creator_angle"] for index in range(20)}
        self.assertGreaterEqual(len(variations), 18)
        self.assertTrue(all("Macy's" in angle for angle in variations))

    def test_variation_changes_narration_hook_and_hashtags(self):
        topic = {"topic": "Macy's Unveils Its 2026 Fall Fashion Campaign"}
        first = _creatorthon_user_variation("user-1", topic)
        second = _creatorthon_user_variation("user-2", topic)
        script = "This campaign is changing the conversation for American fashion audiences today."
        self.assertNotEqual(
            _creatorthon_variation_narration(script, first),
            _creatorthon_variation_narration(script, second),
        )
        self.assertEqual(len(first["variation_hashtags"]), 2)


if __name__ == "__main__":
    unittest.main()
