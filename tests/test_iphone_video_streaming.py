import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

from app import _video_byte_range, _video_file_response


def request_with_range(value: str = "") -> Request:
    headers = [(b"range", value.encode("ascii"))] if value else []
    return Request({"type": "http", "method": "GET", "path": "/video", "headers": headers})


class IPhoneVideoStreamingTests(unittest.TestCase):
    def test_parses_safari_probe_and_suffix_ranges(self):
        self.assertEqual(_video_byte_range("bytes=0-1", 100), (0, 1))
        self.assertEqual(_video_byte_range("bytes=50-", 100), (50, 99))
        self.assertEqual(_video_byte_range("bytes=-10", 100), (90, 99))

    def test_rejects_multiple_or_out_of_bounds_ranges(self):
        with self.assertRaises(HTTPException) as multiple:
            _video_byte_range("bytes=0-1,5-6", 100)
        self.assertEqual(multiple.exception.status_code, 416)
        with self.assertRaises(HTTPException) as outside:
            _video_byte_range("bytes=100-", 100)
        self.assertEqual(outside.exception.headers["Content-Range"], "bytes */100")

    def test_partial_response_has_ios_streaming_headers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "video.mp4"
            path.write_bytes(b"0123456789")
            response = _video_file_response(
                request_with_range("bytes=2-5"), path, "video.mp4"
            )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.media_type, "video/mp4")
        self.assertEqual(response.headers["accept-ranges"], "bytes")
        self.assertEqual(response.headers["content-range"], "bytes 2-5/10")
        self.assertEqual(response.headers["content-length"], "4")
        self.assertIn("inline", response.headers["content-disposition"])

    def test_download_response_uses_attachment(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "video.mp4"
            path.write_bytes(b"0123456789")
            response = _video_file_response(
                request_with_range(), path, "download.mp4", download=True
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
