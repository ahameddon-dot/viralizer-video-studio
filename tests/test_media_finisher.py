import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_finisher import _append_outro, _media_request_headers, _media_url_candidates, _normalize_media_url, _speech_retryable


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

    def test_speech_retries_only_temporary_service_errors(self):
        self.assertTrue(_speech_retryable(None))
        self.assertTrue(_speech_retryable(429))
        self.assertTrue(_speech_retryable(503))
        self.assertFalse(_speech_retryable(400))
        self.assertFalse(_speech_retryable(401))

    def test_outro_is_fitted_to_the_generated_video_and_concatenated(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);video=root/"main.mp4";outro=root/"outro.mp4";output=root/"final.mp4"
            video.write_bytes(b"main");outro.write_bytes(b"outro")
            infos=[{"width":720,"height":1280,"duration":10.0,"audio":False},{"width":1280,"height":720,"duration":10.0,"audio":True}]
            with patch("media_finisher.shutil.which",return_value="ffmpeg"), patch("media_finisher._media_info",side_effect=infos), patch("media_finisher.subprocess.run") as run:
                run.return_value.returncode=0
                _append_outro(video,outro,output)
            command=run.call_args.args[0]
            filters=command[command.index("-filter_complex")+1]
            self.assertIn("scale=720:1280:force_original_aspect_ratio=decrease",filters)
            self.assertIn("concat=n=2:v=1:a=1",filters)
            self.assertIn("anullsrc=r=48000:cl=stereo",command)


if __name__ == "__main__":
    unittest.main()
