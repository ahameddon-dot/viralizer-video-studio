import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import mcp_outline_client as client


class ViralizerProTopicApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_api_starts_and_polls_topic_task(self):
        started = httpx.Response(
            200,
            request=httpx.Request("POST", "https://pro.test/analyze/topic"),
            json={"records": {"task_id": "task-123"}},
        )
        completed = httpx.Response(
            200,
            request=httpx.Request("GET", "https://pro.test/view/task_page/task-123"),
            json={
                "topic": "AI creator tools",
                "topicAnalysis": [{"key": "contentOutline", "data": {"contentOutline": {"title_hook": {"data": "AI creator tools that save hours"}}}}],
            },
        )
        session = AsyncMock()
        session.post.return_value = started
        session.get.return_value = completed
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=session)
        manager.__aexit__ = AsyncMock(return_value=None)

        env = {
            "VIRALIZER_PRO_AUTH_TOKEN": "test-token",
            "VIRALIZER_PRO_API_BASE_URL": "https://pro.test",
            "VIRALIZER_PRO_POLL_SECONDS": "2",
            "VIRALIZER_PRO_MAX_WAIT_SECONDS": "15",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "mcp_outline_client.httpx.AsyncClient", return_value=manager
        ), patch("mcp_outline_client.asyncio.sleep", new=AsyncMock()):
            result = await client._get_full_report_from_pro_api("AI creator tools")

        self.assertEqual(result["topic"], "AI creator tools")
        session.post.assert_awaited_once()
        session.get.assert_awaited_once()

    async def test_mcp_is_used_when_direct_api_is_not_configured(self):
        expected = {"topic": "Fashion", "topicAnalysis": []}
        with patch.dict(
            os.environ,
            {"VIRALIZER_PRO_AUTH_TOKEN": "", "MCP_AUTH_TOKEN": ""},
            clear=False,
        ), patch(
            "mcp_outline_client._get_full_report_from_mcp_only",
            new=AsyncMock(return_value=expected),
        ) as fallback:
            result = await client.get_full_report_from_mcp("Fashion")

        self.assertEqual(result, expected)
        fallback.assert_awaited_once_with("Fashion")

    async def test_pending_pro_job_does_not_start_duplicate_mcp_job(self):
        with patch(
            "mcp_outline_client._get_full_report_from_pro_api",
            new=AsyncMock(side_effect=client.ViralizerProPendingError("still running")),
        ), patch(
            "mcp_outline_client._get_full_report_from_mcp_only",
            new=AsyncMock(),
        ) as fallback:
            with self.assertRaises(client.ViralizerProPendingError):
                await client.get_full_report_from_mcp("Fashion")

        fallback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
