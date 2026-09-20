import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CreatorthonV3Tests(unittest.TestCase):
    def test_v3_is_an_isolated_route(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/creatorthon-v3/login"', app_source)
        self.assertIn('@app.get("/creatorthon-v3")', app_source)
        self.assertIn('ROOT / "static" / "creatorthon-v3.html"', app_source)

    def test_v3_contains_requested_creator_journey(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        for expected in (
            "Your categories to create content",
            "Choose an output",
            "Create with PixVerse",
            "Create with HeyGen",
            "CHATGPT IMAGE",
            "TOPIC RESEARCH",
            "/api/creatorthon/topics",
            "/api/video/prompt",
            "/api/video/generate",
        ):
            self.assertIn(expected, page)

    def test_v3_uses_original_logo_and_responsive_layout(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("/static/viralizer-original-logo.png", page)
        self.assertIn("@media(max-width:850px)", page)


if __name__ == "__main__":
    unittest.main()
