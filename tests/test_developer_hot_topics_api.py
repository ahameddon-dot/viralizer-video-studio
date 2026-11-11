import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

import app as viralizer_app


class DeveloperHotTopicsApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        viralizer_app.DEVELOPER_TOPIC_CACHE.clear()

    async def request(self, path: str, key: str | None = "developer-test-key") -> httpx.Response:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        transport = httpx.ASGITransport(app=viralizer_app.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            return await client.get(path, headers=headers)

    async def test_api_requires_configured_valid_key(self):
        with patch.dict(os.environ, {"VIRALIZER_TOPICS_API_KEYS": "developer-test-key"}, clear=False):
            response = await self.request("/api/v1/hot-topics", key="wrong")
        self.assertEqual(response.status_code, 401)

    async def test_api_normalizes_filters_and_paginates_mcp_topics(self):
        raw = [
            {
                "topic_id": "ai-1",
                "topic": "AI changes retail",
                "image": "https://images.test/ai.jpg",
                "groups": ["Technology", "United States"],
                "group_keys": ["technology", "US"],
            },
            {
                "topic_id": "food-1",
                "topic": "Global restaurant trend",
                "groups": ["Food", "India"],
                "group_keys": ["food", "IN"],
            },
        ]
        with patch.dict(os.environ, {"VIRALIZER_TOPICS_API_KEYS": "developer-test-key"}, clear=False), patch(
            "app.get_hot_topics_from_mcp", new=AsyncMock(return_value=raw)
        ):
            response = await self.request("/api/v1/hot-topics?category=Technology&country=US&limit=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["api_version"], "v1")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["topics"][0]["id"], "ai-1")
        self.assertEqual(payload["topics"][0]["title"], "AI changes retail")
        self.assertEqual(payload["topics"][0]["thumbnail_url"], "https://images.test/ai.jpg")

    async def test_api_uses_public_source_fallback_with_same_contract(self):
        raw = [{
            "topic": "Worldwide energy breakthrough",
            "category": "Energy",
            "published_at": "2026-11-12T08:00:00+00:00",
            "summary": "A current worldwide energy development.",
            "source_urls": ["https://publisher.test/story"],
            "source_platforms": ["GDELT"],
            "mentions": 3,
        }]
        with patch.dict(os.environ, {"VIRALIZER_TOPICS_API_KEYS": "developer-test-key"}, clear=False), patch(
            "app.get_hot_topics_from_mcp", new=AsyncMock(side_effect=viralizer_app.MCPOutlineError("offline"))
        ), patch("app.discover_global_sources", new=AsyncMock(return_value=raw)):
            response = await self.request("/api/v1/hot-topics?search=energy")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "Worldwide public sources")
        self.assertEqual(payload["topics"][0]["category"], "Energy")
        self.assertEqual(payload["topics"][0]["sources"][0]["url"], "https://publisher.test/story")


if __name__ == "__main__":
    unittest.main()
