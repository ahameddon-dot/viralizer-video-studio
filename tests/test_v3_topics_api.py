import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

import app as viralizer_app


class V3TopicsApiTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, key: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=viralizer_app.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://v3.test") as client:
            return await client.get("/api/v1/hot-topics?limit=5", headers={"X-API-Key": key})

    async def test_endpoint_requires_scoped_key_and_returns_verified_rank(self):
        raw = [{"topic_id": "topic-1", "topic": "AI retail"}]
        details = {"viral_rank": 7, "summary": "Verified V3 detail"}
        with patch.dict(os.environ, {"VIRALIZER_TOPICS_API_KEYS": "backend-key"}, clear=False), patch(
            "app.get_hot_topics_from_mcp", new=AsyncMock(return_value=raw)
        ), patch("app.get_hot_topic_details_from_mcp", new=AsyncMock(return_value=details)):
            denied = await self.request("wrong-key")
            response = await self.request("backend-key")
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "Viralizer MCP")
        self.assertEqual(payload["topics"][0]["viral_rank"], 7)


if __name__ == "__main__":
    unittest.main()
