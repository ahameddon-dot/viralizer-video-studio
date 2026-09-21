import unittest

from media_finisher import _media_request_headers, _media_url_candidates, _normalize_media_url


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

    def test_pixverse_download_preserves_original_then_tries_decoded_path(self):
        raw = "https://media.pixverse.ai/pixverse%2Fmp4%2Fvideo.mp4"
        self.assertEqual(
            _media_url_candidates(raw),
            [raw, "https://media.pixverse.ai/pixverse/mp4/video.mp4"],
        )

    def test_pixverse_download_uses_required_media_headers(self):
        headers = _media_request_headers("https://media.pixverse.ai/video.mp4")
        self.assertEqual(headers["Referer"], "https://app.pixverse.ai/")
        self.assertIn("Mozilla/5.0", headers["User-Agent"])
        self.assertEqual(_media_request_headers("https://example.com/video.mp4"), {})


if __name__ == "__main__":
    unittest.main()