import unittest

import storyboard_plan as sp


def fake_scene(start, end, purpose, narration, visual, motion):
    return {"start": start, "end": end, "purpose": purpose, "narration": narration, "on_screen_text": narration[:60],
            "keyframe_prompt": f"Base keyframe. {visual}.", "motion_prompt": f"Animate. {motion}.", "camera": motion}


class ScaledStoryboardTests(unittest.TestCase):
    def build(self, seconds):
        return sp.scaled_storyboard("Big hook.", "AI video", "creators", "Follow for more.", seconds, fake_scene)

    def test_scene_counts_and_timing(self):
        for seconds, count in ((5, 1), (10, 2), (15, 3), (30, 6), (60, 12)):
            scenes = self.build(seconds)
            self.assertEqual(count, len(scenes))
            self.assertEqual(seconds, scenes[-1]["end"])
            self.assertEqual([i * 5 for i in range(count)], [s["start"] for s in scenes])

    def test_first_is_hook_last_is_cta(self):
        scenes = self.build(30)
        self.assertEqual("hook", scenes[0]["purpose"])
        self.assertEqual("Big hook.", scenes[0]["narration"])
        self.assertEqual("action", scenes[-1]["purpose"])
        self.assertEqual("Follow for more.", scenes[-1]["narration"])

    def test_single_scene_is_the_hook(self):
        self.assertEqual("hook", self.build(5)[0]["purpose"])

    def test_long_video_has_varied_middle_beats(self):
        middle = [s["purpose"] for s in self.build(60)[1:-1]]
        self.assertGreater(len(set(middle)), 3)
        self.assertEqual(10, len(middle))

    def test_no_invented_statistics_in_templates(self):
        for scene in self.build(60):
            self.assertNotRegex(scene["narration"], r"\d")


class ScenePatchTests(unittest.TestCase):
    def scene(self):
        return fake_scene(0, 5, "hook", "Old line.", "A wide view", "Slow push-in")

    def test_narration_only_patch(self):
        patch = sp.scene_patch(self.scene(), narration="New line.")
        self.assertEqual({"narration", "on_screen_text"}, set(patch))

    def test_visual_edit_is_idempotent_and_replaces_previous_direction(self):
        scene = self.scene()
        first = sp.scene_patch(scene, visual="a crowd cheering")
        scene.update(first)
        second = sp.scene_patch(scene, visual="an empty street")
        self.assertEqual(1, second["keyframe_prompt"].count("[Direction:"))
        self.assertIn("an empty street", second["keyframe_prompt"])
        self.assertNotIn("crowd", second["keyframe_prompt"])
        self.assertTrue(second["keyframe_prompt"].startswith("Base keyframe. A wide view."))

    def test_style_keeps_existing_direction(self):
        scene = self.scene()
        scene.update(sp.scene_patch(scene, visual="a crowd"))
        patch = sp.scene_patch(scene, style="cinematic")
        self.assertIn("[Direction: a crowd]", patch["keyframe_prompt"])
        self.assertIn("[Style: cinematic]", patch["keyframe_prompt"])

    def test_motion_edit_updates_motion_and_camera(self):
        patch = sp.scene_patch(self.scene(), motion="fast whip pan")
        self.assertIn("[Motion: fast whip pan]", patch["motion_prompt"])
        self.assertEqual("fast whip pan", patch["camera"])

    def test_empty_request_returns_empty_patch(self):
        self.assertEqual({}, sp.scene_patch(self.scene()))

    def test_user_text_cannot_inject_tag_brackets(self):
        patch = sp.scene_patch(self.scene(), visual="x] [Style: evil")
        self.assertEqual(1, patch["keyframe_prompt"].count("["))
        self.assertNotIn("[Style:", patch["keyframe_prompt"])


if __name__ == "__main__":
    unittest.main()


