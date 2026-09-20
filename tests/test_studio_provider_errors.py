import unittest
from pathlib import Path


class StudioProviderErrorTests(unittest.TestCase):
    def test_studio_surfaces_backend_generation_error(self):
        studio = (
            Path(__file__).resolve().parents[1] / "static" / "full_studio.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "current.error||current.detail||current.result?.error",
            studio,
        )


if __name__ == "__main__":
    unittest.main()
