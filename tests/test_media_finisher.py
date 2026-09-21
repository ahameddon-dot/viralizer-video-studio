import unittest

from media_finisher import _normalize_media_url


class MediaFinisherUrlTests(unittest.TestCase):
    def test_decodes_pixverse_encoded_path_separators(self):
        raw = "https://media.pixverse.ai/pixverse%2Fmp4%2Fmedia%2Fweb%2Fori%2Fvideo_seed1.mp4"
        self.assertEqual(
            _normalize_media_url(raw),
            "https://media.pixverse.ai/pixverse/mp4/media/web/ori/video_seed1.mp4",
        )

    def test_does_not_rewrite_unrelated_hosts(self):
        raw = "https://example.com/folder%2Fvideo.mp4?token=abc"
        self.assertEqual(_normalize_media_url(raw), raw)


if __name__ == "__main__":
    unittest.main()