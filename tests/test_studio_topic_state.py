import asyncio
import unittest
from pathlib import Path

from app import TopicRequest, prepare_exact_video_topic


class StudioTopicStateTests(unittest.TestCase):
    def test_refresh_restoration_is_local_exact_and_not_stale(self):
        result = asyncio.run(prepare_exact_video_topic(TopicRequest(topic="prawn: Seafood Cooking Techniques")))
        self.assertEqual(result["selected_topic"], "prawn: Seafood Cooking Techniques")
        self.assertEqual(result["outline"]["topic"], result["selected_topic"])
        self.assertIn("prawn", result["prompt"].lower())
        self.assertNotIn("nvidia", result["prompt"].lower())
        self.assertNotIn("chocolate", result["prompt"].lower())

    def test_transferred_report_wins_before_url_fallback(self):
        html = (Path(__file__).parents[1] / "static" / "full_studio.html").read_text(encoding="utf-8")
        self.assertIn("if(restoreTransferredVideo())return;if(await restoreTopicFromUrl())return", html)
        self.assertIn("protectedKeys=new Set(['topic','suggested_title'", html)
        restore = html[html.index("async function restoreTopicFromUrl"):html.index("function restoreTransferredVideo")]
        self.assertNotIn("localStorage.removeItem('viralizer_video_studio_transfer')", restore)
        self.assertIn("window.viralizerInitialization=initializeStudioPage()", html)
        self.assertIn("if(window.viralizerInitialization)await window.viralizerInitialization", html)
        self.assertIn("if(currentIdentity&&freshIdentity&&currentIdentity!==freshIdentity)return current", html)
        self.assertIn("document.querySelector('#duration').value='5'", html)


if __name__ == "__main__":
    unittest.main()