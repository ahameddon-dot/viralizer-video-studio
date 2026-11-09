import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_intelligence import save_brand_profile
from autopilot_operations import worker_tick
from autopilot_orchestrator import create_objective, make_selection
from autopilot_store import get_workflow_run


class AutopilotOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()
        save_brand_profile(self.root, "customer-1", {
            "customer_type": "business", "positioning": "A practical growth platform",
            "voice": ["clear"], "audiences": ["founders"], "goals": ["qualified traffic"],
            "products_services": [], "visual_style": [], "constraints": [], "social_urls": [], "confirmed": True,
        })

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_agents_execute_and_stop_at_human_opportunity_gate(self):
        result = create_objective(self.root, "customer-1", {
            "objective": "Explain agentic content operations", "seed_topics": ["Human approval for AI content"],
        })
        run_id = result["run"]["id"]
        asyncio.run(worker_tick(self.root, "test-worker", mode="fake", limit=10, customer_id="customer-1"))
        asyncio.run(worker_tick(self.root, "test-worker", mode="fake", limit=10, customer_id="customer-1"))
        status = get_workflow_run(self.root, "customer-1", run_id)
        self.assertEqual("waiting_user", status["run"]["status"])
        states = {step["agent_type"]: step["status"] for step in status["steps"]}
        self.assertEqual("succeeded", states["trend_discovery"])
        self.assertEqual("succeeded", states["opportunity_ranking"])
        self.assertEqual("waiting_user", states["opportunity_selection"])
        ranking = next(step for step in status["steps"] if step["agent_type"] == "opportunity_ranking")
        self.assertIn("opportunities", ranking["output_json"])

    def test_selection_queues_creative_agent(self):
        result = create_objective(self.root, "customer-1", {"objective": "Explain AI workflows"})
        run_id = result["run"]["id"]
        asyncio.run(worker_tick(self.root, "test-worker", mode="fake", limit=10, customer_id="customer-1"))
        asyncio.run(worker_tick(self.root, "test-worker", mode="fake", limit=10, customer_id="customer-1"))
        status = get_workflow_run(self.root, "customer-1", run_id)
        ranking = next(step for step in status["steps"] if step["agent_type"] == "opportunity_ranking")
        import json
        opportunity_id = json.loads(ranking["output_json"])["opportunities"][0]["id"]
        make_selection(self.root, "customer-1", run_id, "opportunity_selection", {"entity_id": opportunity_id})
        status = get_workflow_run(self.root, "customer-1", run_id)
        self.assertIn("creative_direction", [step["agent_type"] for step in status["steps"]])


if __name__ == "__main__":
    unittest.main()
