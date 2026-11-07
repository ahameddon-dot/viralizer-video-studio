import unittest
from unittest.mock import AsyncMock, patch

from pixverse_client import PixVerseClient, PixVerseError


class PixVerseRequestRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_prompt_is_compacted_and_retried(self):
        with patch.dict("os.environ", {"PIXVERSE_API_KEY": "test-key"}):
            client = PixVerseClient()
        client._post_generation = AsyncMock(side_effect=[
            PixVerseError("Prompt is too long", error_type="TEXT_LENGTH_EXCEEDS_THRESHOLD", trace_id="trace-1"),
            {"video_id": 123},
        ])

        result = await client.generate("cinematic direction " * 400)

        self.assertEqual(result, 123)
        first_payload = client._post_generation.await_args_list[0].args[1]
        retry_payload = client._post_generation.await_args_list[1].args[1]
        self.assertLessEqual(len(first_payload["prompt"]), 1800)
        self.assertLessEqual(len(retry_payload["prompt"]), 1000)

    async def test_unsupported_quality_duration_uses_safe_combination(self):
        with patch.dict("os.environ", {"PIXVERSE_API_KEY": "test-key"}):
            client = PixVerseClient()
        client._post_generation = AsyncMock(side_effect=[
            PixVerseError(
                "Unsupported quality and duration",
                error_type="QUALITY_DURATION_MODEL_UNSUPPORTED",
                trace_id="trace-2",
            ),
            {"video_id": 456},
        ])

        result = await client.generate("Pizza hero reveal", duration=15, quality="1080p")

        self.assertEqual(result, 456)
        retry_payload = client._post_generation.await_args_list[1].args[1]
        self.assertEqual(retry_payload["quality"], "540p")
        self.assertEqual(retry_payload["duration"], 10)


if __name__ == "__main__":
    unittest.main()
