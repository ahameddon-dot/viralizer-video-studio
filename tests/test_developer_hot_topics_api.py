import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import app as viralizer_app


class DeveloperHotTopicsApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        viralizer_app.DEVELOPER_TOPIC_CACHE.clear()

    async def request(self, path: str, key: str | None = "developer-test-key", json=None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        transport = httpx.ASGITransport(app=viralizer_app.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            if json is not None:
                return await client.post(path, headers=headers, json=json)
            return await client.get(path, headers=headers)

    async def test_api_requires_configured_valid_key(self):
        with patch.dict(os.environ, {"VIRALIZER_TOPICS_API_KEYS": "developer-test-key"}, clear=False):
            response = await self.request("/api/v1/hot-topics", key="wrong")
        self.assertEqual(response.status_code, 401)

    async def test_api_normalizes_filters_and_paginates_worldwide_topics(self):
        raw = [
            {
                "topic_id": "ai-1",
                "topic": "AI changes retail",
                "image": "https://images.test/ai.jpg",
                "groups": ["Technology", "United States"],
                "group_keys": ["technology", "US"],
                "viral_rank": 12,
            },
            {
                "topic_id": "food-1",
                "topic": "Global restaurant trend",
                "groups": ["Food", "India"],
                "group_keys": ["food", "IN"],
            },
        ]
        with patch.dict(os.environ, {"VIRALIZER_TOPICS_API_KEYS": "developer-test-key"}, clear=False), patch(
            "app.discover_global_sources", new=AsyncMock(return_value=raw)
        ):
            response = await self.request("/api/v1/hot-topics?category=Technology&country=US&limit=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["api_version"], "v1")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["topics"][0]["id"], "ai-1")
        self.assertEqual(payload["topics"][0]["title"], "AI changes retail")
        self.assertEqual(payload["topics"][0]["thumbnail_url"], "https://images.test/ai.jpg")
        self.assertEqual(payload["topics"][0]["viral_rank"], 12)

    async def test_autopilot_v3_client_uses_server_key_and_preserves_rank(self):
        response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://v3.test/api/v1/hot-topics"),
            json={"source": "Viralizer MCP", "topics": [{"title": "AI retail", "viral_rank": 7}]},
        )
        session = AsyncMock()
        session.get.return_value = response
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=session)
        manager.__aexit__ = AsyncMock(return_value=None)
        with patch.dict(os.environ, {
            "VIRALIZER_V3_TOPICS_API_KEY": "server-only-key",
            "VIRALIZER_V3_TOPICS_API_URL": "https://v3.test/api/v1/hot-topics",
        }, clear=False), patch("app.httpx.AsyncClient", return_value=manager):
            topics, source = await viralizer_app._v3_worldwide_topics()
        self.assertEqual(source, "Viralizer MCP")
        self.assertEqual(topics[0]["topic"], "AI retail")
        self.assertEqual(topics[0]["viral_rank"], 7)
        self.assertEqual(session.get.await_args.kwargs["headers"]["X-API-Key"], "server-only-key")

    async def test_api_uses_viralizer_worldwide_intelligence(self):
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
            "app.discover_global_sources", new=AsyncMock(return_value=raw)
        ):
            response = await self.request("/api/v1/hot-topics?search=energy")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "Viralizer Worldwide Intelligence")
        self.assertEqual(payload["topics"][0]["category"], "Energy")
        self.assertEqual(payload["topics"][0]["sources"][0]["url"], "https://publisher.test/story")

    async def test_api_never_queries_mcp(self):
        raw = [{
            "topic": "Restaurant menus shift toward regional ingredients",
            "category": "Food",
            "published_at": "2026-11-16T08:00:00+00:00",
            "summary": "A current food-industry development.",
            "source_urls": ["https://publisher.test/food-story"],
            "source_platforms": ["GDELT"],
            "mentions": 4,
        }]
        with patch.dict(os.environ, {"VIRALIZER_TOPICS_API_KEYS": "developer-test-key"}, clear=False), patch(
            "app.get_hot_topics_from_mcp", new=AsyncMock(side_effect=AssertionError("MCP must not be called"))
        ), patch("app.discover_global_sources", new=AsyncMock(return_value=raw)) as discover:
            response = await self.request("/api/v1/hot-topics?category=Food")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "Viralizer Worldwide Intelligence")
        self.assertEqual(payload["topics"][0]["category"], "Food")
        discover.assert_awaited_once()

    async def test_topic_intelligence_requires_key_and_returns_normalized_topics(self):
        raw = [{
            "topic": "Enterprise AI adoption accelerates",
            "category": "Artificial Intelligence",
            "summary": "Companies expand production AI deployments.",
            "source_urls": ["https://publisher.test/ai"],
            "source_platforms": ["Publisher"],
        }]
        payload = {
            "category": "Artificial Intelligence",
            "super_category": "Technology",
            "keyword": "enterprise adoption",
            "lens": "companies",
            "reputation": "mixed",
        }
        with patch.dict(os.environ, {"VIRALIZER_TOPICS_API_KEYS": "developer-test-key"}, clear=False), patch(
            "app.discover_category_topics", new=AsyncMock(return_value=raw)
        ) as discover, patch("app.annotate_topic_taxonomy", side_effect=lambda items, *_: items):
            response = await self.request("/api/v1/topic-intelligence?limit=20", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "Viralizer Worldwide Intelligence")
        self.assertEqual(body["topics"][0]["title"], "Enterprise AI adoption accelerates")
        discover.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
