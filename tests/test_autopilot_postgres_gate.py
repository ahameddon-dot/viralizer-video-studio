import os
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_store import claim_due_steps, create_workflow_run, enqueue_workflow_step


ROOT = Path(__file__).resolve().parents[1]
TEST_DSN = os.getenv("AUTOPILOT_TEST_DATABASE_URL", "")


@unittest.skipUnless(TEST_DSN, "AUTOPILOT_TEST_DATABASE_URL is required for the PostgreSQL release gate")
class AutopilotPostgresGateTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"DATABASE_URL": TEST_DSN})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_skip_locked_claim_and_idempotency(self):
        customer = "postgres-release-gate"
        run = create_workflow_run(ROOT, {"customer_id": customer, "workflow_type": "release_gate"})
        request = {"customer_id": customer, "run_id": run["id"], "agent_type": "release_gate",
                   "idempotency_key": f"release-gate:{run['id']}", "input": {}}
        first, created = enqueue_workflow_step(ROOT, request)
        duplicate, duplicate_created = enqueue_workflow_step(ROOT, request)
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first["id"], duplicate["id"])
        claimed = claim_due_steps(ROOT, "postgres-gate-worker", limit=10)
        matching = [step for step in claimed if step["id"] == first["id"]]
        self.assertEqual(1, len(matching))
        replay = claim_due_steps(ROOT, "postgres-gate-worker-2", limit=10)
        self.assertNotIn(first["id"], {step["id"] for step in replay})


if __name__ == "__main__":
    unittest.main()
