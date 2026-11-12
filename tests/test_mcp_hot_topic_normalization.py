import unittest

from mcp_outline_client import _hot_topics_from_payload


class HotTopicNormalizationTests(unittest.TestCase):
    def test_legacy_grouped_shape(self):
        payload = {"records": {"items": [{"key": "business", "label": "Business", "topics": [{"topic_id": "1", "topic": "AI tools for small businesses", "img": "image.jpg"}]}]}}
        topics = _hot_topics_from_payload(payload)
        self.assertEqual(topics[0]["topic_id"], "1")
        self.assertEqual(topics[0]["groups"], ["Business"])

    def test_new_nested_shape_and_duplicate_groups(self):
        payload = {"data": {"groups": [
            {"group_key": "youtube", "group_label": "YouTube", "items": [{"id": "2", "title": "Short-form search trends", "language": "en", "score": 83}]},
            {"key": "creator", "label": "Creators", "results": [{"topicId": "2", "name": "Short-form search trends"}]},
        ]}}
        topics = _hot_topics_from_payload(payload)
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]["topic"], "Short-form search trends")
        self.assertEqual(topics[0]["score"], 83)
        self.assertEqual(topics[0]["group_keys"], ["youtube", "creator"])

    def test_does_not_treat_group_as_topic(self):
        payload = {"id": "group-1", "title": "Business", "topics": []}
        self.assertEqual(_hot_topics_from_payload(payload), [])


if __name__ == "__main__":
    unittest.main()
