import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CreatorthonBrandingTests(unittest.TestCase):
    def test_supplied_official_logos_are_present(self):
        self.assertTrue((ROOT / "static" / "viralizer-logo-black.png").is_file())
        self.assertTrue((ROOT / "static" / "viralizer-logo-white.png").is_file())

    def test_all_creatorthon_versions_use_theme_appropriate_official_logo(self):
        v1 = (ROOT / "static" / "creatorthon.html").read_text(encoding="utf-8")
        v2 = (ROOT / "static" / "creatorthon-v2.html").read_text(encoding="utf-8")
        v3 = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("/static/viralizer-logo-white.png", v1)
        self.assertIn("/static/viralizer-logo-black.png", v2)
        self.assertIn("/static/viralizer-logo-black.png", v3)


if __name__ == "__main__":
    unittest.main()
