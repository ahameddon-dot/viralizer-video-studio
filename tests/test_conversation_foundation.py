import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import generate_concepts, rank_opportunities, save_brand_profile
from autopilot_lifecycle import start_content_workflow
from conversation import MODEL_ORCHESTRATION_ENABLED
from conversation.authorization import authorize_tool
from conversation.registry import TOOL_REGISTRY, public_registry
from conversation.store import (
    append_message,
    confirm_memory_fact,
    confirmed_memory,
    create_conversation,
    get_conversation,
    link_workflow,
    list_conversations,
    propose_memory_fact,
    propose_tool_execution,
)
from hybrid_project_state import ensure_autopilot_project


class ConversationFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()
        save_brand_profile(self.root, "customer-1", {"customer_type": "creator", "voice": ["clear"], "confirmed": True})
        opportunity = rank_opportunities(self.root, "customer-1", {"topics": [{"topic": "Creator growth", "viral_score": 92}]})[0]
        self.concept = generate_concepts(self.root, "customer-1", {"opportunity_id": opportunity["id"]})[0]
        self.project = ensure_autopilot_project(self.root, "customer-1", self.concept["id"])
        self.conversation = create_conversation(self.root, "customer-1", "Growth plan", self.project["id"], "owner@example.com")

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_conversations_and_messages_are_customer_scoped_and_ordered(self):
        first = append_message(self.root, "customer-1", self.conversation["id"], "user", {"text": "Find a topic"}, "corr-1")
        second = append_message(self.root, "customer-1", self.conversation["id"], "user", {"text": "Create a storyboard"}, "corr-2")
        self.assertEqual((1, 2), (first["sequence"], second["sequence"]))
        loaded = get_conversation(self.root, "customer-1", self.conversation["id"])
        self.assertEqual(["Find a topic", "Create a storyboard"], [item["content"]["text"] for item in loaded["messages"]])
        self.assertEqual(1, len(list_conversations(self.root, "customer-1")))
        self.assertEqual([], list_conversations(self.root, "customer-2"))
        with self.assertRaises(ValueError):
            get_conversation(self.root, "customer-2", self.conversation["id"])

    def test_message_and_tool_arguments_are_redacted_before_persistence(self):
        message = append_message(self.root, "customer-1", self.conversation["id"], "user", {
            "text": "connect account", "access_token": "secret", "nested": {"Authorization": "Bearer secret"},
        })
        self.assertEqual("[REDACTED]", message["content"]["access_token"])
        self.assertEqual("[REDACTED]", message["content"]["nested"]["Authorization"])
        execution = propose_tool_execution(
            self.root, "customer-1", self.conversation["id"], "get_brand_profile",
            {"api_key": "secret", "safe": "value"}, "read-brand-1", "corr-tool-1",
        )
        self.assertEqual("[REDACTED]", execution["arguments"]["api_key"])
        self.assertEqual("value", execution["arguments"]["safe"])
        self.assertTrue(execution["authorization"]["execution_enabled"])

    def test_memory_requires_confirmation_and_supersedes_prior_fact(self):
        message = append_message(self.root, "customer-1", self.conversation["id"], "user", {"text": "Use a premium tone"})
        first = propose_memory_fact(self.root, "customer-1", self.conversation["id"], "brand.voice", "premium", message["id"], .9)
        self.assertEqual([], confirmed_memory(self.root, "customer-1"))
        confirm_memory_fact(self.root, "customer-1", first["id"], "owner@example.com")
        second = propose_memory_fact(self.root, "customer-1", self.conversation["id"], "brand.voice", "educational", message["id"], .8)
        confirm_memory_fact(self.root, "customer-1", second["id"], "owner@example.com")
        facts = confirmed_memory(self.root, "customer-1")
        self.assertEqual(1, len(facts))
        self.assertEqual("educational", facts[0]["value"])
        self.assertEqual([], confirmed_memory(self.root, "customer-2"))

    def test_tool_registry_is_typed_mapped_and_globally_disabled(self):
        self.assertIsInstance(MODEL_ORCHESTRATION_ENABLED, bool)
        self.assertEqual(11, len(TOOL_REGISTRY))
        self.assertEqual(
            {"get_brand_profile", "analyze_brand_sources", "discover_topics", "rank_opportunities", "create_concepts", "get_growth_report"},
            {item.name for item in TOOL_REGISTRY.values() if item.model_execution_enabled},
        )
        self.assertEqual("autopilot_intelligence:get_brand_profile", TOOL_REGISTRY["get_brand_profile"].implementation)
        self.assertEqual("exact_content", TOOL_REGISTRY["prepare_publication"].approval)
        self.assertTrue(TOOL_REGISTRY["prepare_publication"].wrapper_required)
        self.assertFalse(TOOL_REGISTRY["create_concepts"].requires_project)
        self.assertTrue(all(item["input_schema"] and item["output_schema"] for item in public_registry()))

    def test_authorization_enforces_tenant_cost_and_human_approval(self):
        read = authorize_tool(self.root, "customer-1", "get_brand_profile")
        self.assertTrue(read["authorized"])
        self.assertTrue(read["execution_enabled"])
        cost = authorize_tool(self.root, "customer-1", "generate_keyframe", self.project["id"])
        self.assertEqual("cost_confirmation_required", cost["code"])
        confirmed = authorize_tool(self.root, "customer-1", "generate_keyframe", self.project["id"], cost_confirmed=True)
        self.assertFalse(confirmed["authorized"])
        self.assertEqual("manual_tool_only", confirmed["code"])
        foreign = authorize_tool(self.root, "customer-2", "generate_keyframe", self.project["id"], cost_confirmed=True)
        self.assertEqual("project_forbidden", foreign["code"])
        approval = authorize_tool(self.root, "customer-1", "prepare_publication", self.project["id"])
        self.assertEqual("human_approval_required", approval["code"])

    def test_tool_proposal_is_idempotent_and_never_executes(self):
        first = propose_tool_execution(
            self.root, "customer-1", self.conversation["id"], "generate_keyframe", {"scene_index": 0},
            "keyframe-1", "corr-1", cost_confirmed=False,
        )
        replay = propose_tool_execution(
            self.root, "customer-1", self.conversation["id"], "generate_keyframe", {"scene_index": 0},
            "keyframe-1", "corr-2", cost_confirmed=True,
        )
        self.assertEqual(first["id"], replay["id"])
        self.assertEqual("blocked", first["status"])
        self.assertEqual("cost_confirmation_required", first["authorization"]["code"])
        self.assertEqual({}, first["result"])

    def test_workflow_link_requires_same_customer(self):
        run = start_content_workflow(self.root, "customer-1", self.concept["id"])
        linked = link_workflow(self.root, "customer-1", self.conversation["id"], run["id"], self.project["id"], "content production")
        self.assertEqual(run["id"], linked["workflow_run_id"])
        with self.assertRaises(ValueError):
            link_workflow(self.root, "customer-2", self.conversation["id"], run["id"], self.project["id"])


class ConversationRouteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    def test_persistence_routes_exist_without_model_or_execution_endpoint(self):
        for route in ('/api/conversations', '/api/conversations/{conversation_id}/messages', '/api/conversation-tools'):
            self.assertIn(route, self.app)
        self.assertIn('"assistant_response": None', self.app)
        self.assertIn('"executed": False', self.app)
        self.assertIn('"execution_endpoint_enabled": MODEL_ORCHESTRATION_ENABLED', self.app)
        self.assertIn('/api/conversations/{conversation_id}/respond', self.app)


if __name__ == "__main__":
    unittest.main()
