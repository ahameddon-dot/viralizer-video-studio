import unittest

from motion_director import build_motion_plan


class MotionDirectorTests(unittest.TestCase):
    def plan(self, topic, idea="", generation_type="image_to_video", quality=True):
        return build_motion_plan(
            {"topic": topic, "video_idea": idea},
            5,
            generation_type=generation_type,
            quality_mode=quality,
        )

    def test_vinyl_music_interface_keeps_ui_locked(self):
        plan = self.plan("Dreamy vinyl record music player interface", "Create a seamless ambient loop")
        self.assertEqual(plan.scene_type, "UI_ANIMATION")
        self.assertIn("same angular speed", plan.final_prompt)
        self.assertIn("camera completely locked", plan.final_prompt)
        self.assertIn("Do not alter existing text, numbers, icons, buttons or panels", plan.final_prompt)

    def test_moba_character_idle_locks_hud_and_identity(self):
        plan = self.plan("MOBA hero character selection screen", "The armored mage idles while energy glows")
        self.assertEqual(plan.scene_type, "GAMING")
        self.assertEqual(plan.preservation_map["identity"], "STRICT")
        self.assertIn("HUD, stats, currency", plan.final_prompt)
        self.assertIn("pixel-stable", plan.final_prompt)

    def test_product_ad_preserves_geometry(self):
        plan = self.plan("Luxury fragrance product commercial", "Reveal the bottle as light moves across glass")
        self.assertIn(plan.scene_type, {"PRODUCT", "BEAUTY"})
        self.assertEqual(plan.preservation_map["geometry"], "STRICT")
        self.assertIn("clean, stable hero view", plan.final_prompt)

    def test_portrait_preserves_identity(self):
        plan = self.plan("Editorial portrait of a creator", "A living portrait with subtle expression")
        self.assertEqual(plan.scene_type, "PORTRAIT")
        self.assertIn("breathes gently", plan.final_prompt)
        self.assertIn("Preserve the original facial identity", plan.final_prompt)

    def test_moving_car_uses_axle_and_parallax(self):
        plan = self.plan("Premium automotive car driving on a coastal road", "Track the moving vehicle")
        self.assertEqual(plan.scene_type, "AUTOMOTIVE")
        self.assertIn("wheel axle", plan.final_prompt)
        self.assertIn("consistent parallax", plan.final_prompt)

    def test_generic_cinematic_text_to_video_creates_scene(self):
        plan = self.plan("A cinematic documentary about a city changing at sunrise", "Reveal a human-scale transformation", "text_to_video")
        self.assertEqual(plan.generation_type, "text_to_video")
        self.assertTrue(plan.final_prompt.startswith("Create one uninterrupted 5-second vertical 9:16"))
        self.assertNotIn("supplied source image", plan.final_prompt)

    def test_fast_mode_is_shorter_but_keeps_preservation(self):
        full = self.plan("MOBA hero character selection screen", quality=True)
        fast = self.plan("MOBA hero character selection screen", quality=False)
        self.assertLess(len(fast.final_prompt), len(full.final_prompt))
        self.assertIn("supplied image as the visual source of truth", fast.final_prompt)
        self.assertIn("HUD", fast.final_prompt)


if __name__ == "__main__":
    unittest.main()
