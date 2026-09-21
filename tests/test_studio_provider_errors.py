import unittest
from pathlib import Path


class StudioProviderErrorTests(unittest.TestCase):
    def _studio(self):
        return (
            Path(__file__).resolve().parents[1] / "static" / "full_studio.html"
        ).read_text(encoding="utf-8")

    def test_studio_surfaces_backend_generation_error(self):
        studio = self._studio()
        self.assertIn(
            "current.error||current.detail||current.result?.error",
            studio,
        )

    def test_completed_video_is_rendered_before_optional_archiving(self):
        studio = self._studio()
        playback_flow = studio[studio.index("async function showFinishedVideo"):]
        render_position = playback_flow.index("renderPlayableVideo(videoUrl,readyMessage)")
        archive_position = playback_flow.index("archiveGeneratedVideo(videoUrl,outline")
        self.assertLess(render_position, archive_position)
        self.assertIn("The library copy could not be saved", studio)
        self.assertIn("the original generated video is shown", studio)


if __name__ == "__main__":
    unittest.main()
