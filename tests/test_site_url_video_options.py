import asyncio
import unittest
from unittest.mock import patch

from app import SiteUrlVideoRequest, analyze_site_url
from global_sources import suggest_logos_for_content


class SiteUrlVideoOptionTests(unittest.TestCase):
    def test_every_discovered_option_gets_prompt_and_narration(self):
        analysis = {
            "source_type": "news",
            "site_name": "Example News",
            "source_url": "https://example.com/lead",
            "selected": {"title": "Lead story", "summary": "Lead summary", "published_at": "2026-09-19"},
            "alternatives": [
                {"title": "Second story", "summary": "Second summary", "url": "https://example.com/second", "published_at": ""}
            ],
            "content": {
                "topic": "Lead story",
                "suggested_title": "Lead story",
                "summary": "Lead summary",
                "why_it_matters": "Lead summary",
                "video_idea": "Explain the verified story visually.",
                "source_url": "https://example.com/lead",
                "source_urls": ["https://example.com/lead"],
            },
        }
        with patch("app.analyze_website", return_value=analysis):
            result = asyncio.run(analyze_site_url(SiteUrlVideoRequest(url="https://example.com", duration=10, aspect_ratio="16:9")))
        self.assertEqual(len(result["content_options"]), 2)
        self.assertEqual(result["content_options"][1]["content"]["topic"], "Second story")
        self.assertTrue(all(option["prompt"] for option in result["content_options"]))
        self.assertTrue(all(option["narration"] for option in result["content_options"]))
        self.assertEqual(result["aspect_ratio"], "16:9")

    def test_company_site_uses_verified_source_logo_not_category_brand(self):
        content = {
            "topic": "Predictive AI for Viral Content | Intuition Intelligence",
            "summary": "Intuition Intelligence develops predictive AI for viral content.",
            "source_type": "company",
            "source_site": "Intuition Intelligence",
            "source_url": "https://intuition-intelligence.com/",
        }
        logos = asyncio.run(suggest_logos_for_content(content))
        self.assertEqual(logos[0]["name"], "Intuition Intelligence")
        self.assertNotIn("nvidia", str(logos).lower())


if __name__ == "__main__":
    unittest.main()