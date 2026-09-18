import os
import unittest
from unittest.mock import patch

from social_publisher import MANDATORY_HASHTAG, build_hashtags, publishing_status


class SocialPublisherTests(unittest.TestCase):
    def test_hashtags_are_relevant_and_mandatory_tag_is_first(self):
        tags = build_hashtags({
            "topic": "Kerala Showcases Diverse Tourism Offerings at Travel Meet in Dubai",
            "category_label": "Travel",
            "summary": "Kerala backwaters, culture and destination experiences",
        })
        self.assertEqual(tags[0], MANDATORY_HASHTAG)
        self.assertIn("#Kerala", tags)
        self.assertIn("#Travel", tags)
        self.assertEqual(len(tags), len(set(tag.lower() for tag in tags)))

    def test_platforms_are_never_reported_connected_without_credentials(self):
        keys = [
            "META_ACCESS_TOKEN", "INSTAGRAM_USER_ID", "FACEBOOK_PAGE_ID",
            "PUBLIC_BASE_URL", "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_AUTHOR_URN",
        ]
        with patch.dict(os.environ, {key: "" for key in keys}, clear=False):
            status = publishing_status()
        self.assertFalse(status["instagram"]["configured"])
        self.assertFalse(status["facebook"]["configured"])
        self.assertFalse(status["linkedin"]["configured"])


if __name__ == "__main__":
    unittest.main()
