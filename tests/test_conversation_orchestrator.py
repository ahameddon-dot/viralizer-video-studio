import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import save_brand_profile
from conversation.orchestrator import _execute, respond, tool_definitions
from conversation.store import append_message, create_conversation, get_conversation
from creatorthon_store import _connect


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


class ConversationOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data"), "OPENAI_API_KEY": "test-only"})
        self.environment.start()
        save_brand_profile(self.root, "customer-1", {"customer_type": "creator", "voice": ["clear"], "confirmed": True})
        self.thread = create_conversation(self.root, "customer-1", "Brand help")
        self.user_message = append_message(self.root, "customer-1", self.thread["id"], "user", {"text": "What is my brand voice?"})

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_safe_tool_executes_and_assistant_response_is_persisted(self):
        client = FakeClient([
            FakeResponse({"id": "resp-1", "output": [{"type": "function_call", "name": "get_brand_profile", "call_id": "call-1", "arguments": "{}"}]}),
            FakeResponse({"id": "resp-2", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Your confirmed brand voice is clear."}]}]}),
        ])
        with patch("conversation.orchestrator.MODEL_ORCHESTRATION_ENABLED", True):
            result = asyncio.run(respond(self.root, "customer-1", self.thread["id"], "owner", self.user_message["id"], client=client))
        self.assertEqual("Your confirmed brand voice is clear.", result["message"]["content"]["text"])
        self.assertEqual(2, len(client.requests))
        self.assertEqual("https://api.openai.com/v1/responses", client.requests[0][0])
        self.assertIn("function_call_output", str(client.requests[1][1]["json"]["input"]))
        loaded = get_conversation(self.root, "customer-1", self.thread["id"])
        self.assertEqual("assistant", loaded["messages"][-1]["role"])
        with _connect(self.root) as db:
            execution = dict(db.execute("SELECT status,result_json FROM conversation_tool_executions").fetchone())
        self.assertEqual("succeeded", execution["status"])
        self.assertNotIn("test-only", execution["result_json"])

    def test_registry_exposes_safe_and_approval_only_tools(self):
        definitions = {item["name"]: item for item in tool_definitions()}
        self.assertIn("discover_topics", definitions)
        self.assertIn("generate_keyframe", definitions)
        self.assertIn("prepare_publication", definitions)
        self.assertFalse(definitions["prepare_publication"]["strict"])

    def test_chat_discovery_uses_canonical_v3_topics(self):
        topics = [{"topic": "Verified V3 topic", "viral_rank": 88}]
        with patch("conversation.orchestrator.fetch_v3_worldwide_topics", return_value=(topics, "Viralizer V3 MCP")) as fetch:
            result = asyncio.run(_execute(self.root, "customer-1", "discover_topics", {"limit": 5}))
        self.assertEqual(topics, result["topics"])
        self.assertEqual("viralizer_v3", result["provenance"]["data_source"])
        fetch.assert_called_once_with(5)


if __name__ == "__main__":
    unittest.main()
