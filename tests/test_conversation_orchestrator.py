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
        save_brand_profile(self.root, "customer-1", {
            "customer_type": "creator", "positioning": "Clear practical brand voice guidance",
            "audiences": ["content creators"], "products_services": ["brand voice guides"], "confirmed": True,
        })
        topics = [{"topic": "Clear creator brand voice guide", "viral_rank": 88}]
        with patch("conversation.orchestrator.fetch_v3_worldwide_topics", return_value=(topics, "Viralizer V3 MCP")) as fetch:
            result = asyncio.run(_execute(self.root, "customer-1", "discover_topics", {"limit": 5}))
        self.assertEqual(["Clear creator brand voice guide"], [item["topic"] for item in result["topics"]])
        self.assertEqual("viralizer_v3", result["provenance"]["data_source"])
        self.assertTrue(result["provenance"]["profile_match_verified"])
        fetch.assert_called_once_with(5, category="")

    def test_discovery_never_exposes_unfiltered_worldwide_topics_as_profile_matches(self):
        save_brand_profile(self.root, "food-channel", {
            "customer_type": "creator", "category": "Food & Cooking", "positioning": "Food and cooking videos",
            "audiences": ["home cooks"], "products_services": ["recipes"],
            "keywords": ["food", "cooking", "recipe"], "confirmed": True,
        })
        topics = [
            {"topic": "Iran's Role in Middle Eastern Geopolitics", "viral_rank": 45},
            {"topic": "Microsoft Cloud Reliability Strategies", "viral_rank": 57},
            {"topic": "Easy chicken biryani recipe for home cooks", "viral_rank": 38},
        ]
        with patch("conversation.orchestrator.fetch_v3_worldwide_topics", return_value=(topics, "Viralizer V3 MCP")) as fetch:
            result = asyncio.run(_execute(self.root, "food-channel", "discover_topics", {"limit": 5}))
        self.assertEqual(["Easy chicken biryani recipe for home cooks"], [item["topic"] for item in result["topics"]])
        self.assertEqual(2, result["provenance"]["rejected_unrelated_count"])
        fetch.assert_called_once_with(5, category="Food")

    def test_discovery_prefers_same_v3_category_catalog_visible_in_product(self):
        save_brand_profile(self.root, "food-channel", {
            "customer_type": "creator", "category": "Food & Cooking",
            "positioning": "Food and cooking videos", "audiences": ["home cooks"],
            "products_services": ["recipes"], "keywords": ["food", "cooking"], "confirmed": True,
        })
        catalog = [{"topic": "UN aims to halve global food waste by 2030", "category": "Food", "viral_rank": 132}]
        with patch("conversation.orchestrator.get_cached_category_topics", return_value=catalog) as cached, \
             patch("conversation.orchestrator.fetch_v3_worldwide_topics") as fetch:
            result = asyncio.run(_execute(self.root, "food-channel", "discover_topics", {"limit": 5}))
        self.assertEqual(["UN aims to halve global food waste by 2030"], [item["topic"] for item in result["topics"]])
        cached.assert_called_once_with(self.root, "Food", allow_stale=True)
        fetch.assert_not_called()

    def test_empty_rank_result_archives_stale_opportunities(self):
        with patch("conversation.orchestrator.rank_opportunities", return_value=[]) as rank, \
             patch("conversation.orchestrator.archive_other_opportunities") as archive:
            result = asyncio.run(_execute(self.root, "customer-1", "rank_opportunities", {"topics": [{"topic": "Iran geopolitics"}]}))
        self.assertEqual([], result["opportunities"])
        rank.assert_called_once()
        archive.assert_called_once_with(self.root, "customer-1", [])

    def test_no_verified_matches_returns_contextual_actions_instead_of_raw_topics(self):
        client = FakeClient([
            FakeResponse({"id": "resp-1", "output": [{"type": "function_call", "name": "rank_opportunities", "call_id": "call-1", "arguments": "{\"topics\":[{\"topic\":\"Iran geopolitics\"}]}"}]}),
        ])
        with patch("conversation.orchestrator.MODEL_ORCHESTRATION_ENABLED", True), \
             patch("conversation.orchestrator.rank_opportunities", return_value=[]), \
             patch("conversation.orchestrator.archive_other_opportunities"):
            result = asyncio.run(respond(self.root, "customer-1", self.thread["id"], "owner", self.user_message["id"], client=client))
        self.assertIn("rejected the unrelated results", result["message"]["content"]["text"])
        self.assertEqual(
            ["Refresh relevant trends", "Re-analyze my brand", "Use my own idea"],
            [item["label"] for item in result["suggestions"]],
        )
        self.assertEqual(1, len(client.requests))

    def test_discover_only_model_call_cannot_narrate_raw_unrelated_feed(self):
        save_brand_profile(self.root, "customer-1", {
            "customer_type": "creator", "positioning": "Food and cooking videos",
            "audiences": ["home cooks"], "products_services": ["recipes"],
            "keywords": ["food", "cooking", "recipe"], "confirmed": True,
        })
        client = FakeClient([
            FakeResponse({"id": "resp-1", "output": [{"type": "function_call", "name": "discover_topics", "call_id": "call-1", "arguments": "{\"limit\":5}"}]}),
        ])
        raw_topics = [{"topic": "Iran's Role in Middle Eastern Geopolitics", "viral_rank": 45}]
        with patch("conversation.orchestrator.MODEL_ORCHESTRATION_ENABLED", True), \
             patch("conversation.orchestrator.fetch_v3_worldwide_topics", return_value=(raw_topics, "Viralizer V3 MCP")):
            result = asyncio.run(respond(self.root, "customer-1", self.thread["id"], "owner", self.user_message["id"], client=client))
        self.assertNotIn("Iran", result["message"]["content"]["text"])
        self.assertIn("rejected the unrelated results", result["message"]["content"]["text"])
        self.assertEqual(["Refresh relevant trends", "Re-analyze my brand", "Use my own idea"],
                         [item["label"] for item in result["suggestions"]])
        self.assertEqual(1, len(client.requests))

    def test_concept_creation_attaches_shared_project_to_chat(self):
        concepts = [{"id": "concept-1", "content": {"storyboard": [{}, {}, {}]}}]
        with patch("conversation.orchestrator.generate_concepts", return_value=concepts), \
             patch("conversation.orchestrator.list_opportunities", return_value=[{"id": "opportunity-1", "title": "Creator growth"}]), \
             patch("conversation.orchestrator.ensure_autopilot_project", return_value={"id": "project-1", "revision": 1}), \
             patch("conversation.orchestrator.attach_project") as attach:
            result = asyncio.run(_execute(
                self.root, "customer-1", "create_concepts",
                {"opportunity_id": "opportunity-1"}, self.thread["id"], "owner",
            ))
        self.assertEqual("project-1", result["project"]["id"])
        attach.assert_called_once_with(self.root, "customer-1", self.thread["id"], "project-1")

    def test_numeric_topic_selection_resolves_to_saved_opportunity(self):
        concepts = [{"id": "concept-1", "content": {"storyboard": [{}, {}, {}]}}]
        opportunities = [
            {"id": "opportunity-1", "title": "First topic"},
            {"id": "opportunity-2", "title": "Second topic"},
        ]
        with patch("conversation.orchestrator.list_opportunities", return_value=opportunities), \
             patch("conversation.orchestrator.generate_concepts", return_value=concepts) as generate, \
             patch("conversation.orchestrator.ensure_autopilot_project", return_value={"id": "project-1", "revision": 1}), \
             patch("conversation.orchestrator.attach_project"):
            asyncio.run(_execute(self.root, "customer-1", "create_concepts", {"opportunity_id": "1"}, self.thread["id"], "owner"))
        self.assertEqual("opportunity-1", generate.call_args.args[2]["opportunity_id"])


if __name__ == "__main__":
    unittest.main()
