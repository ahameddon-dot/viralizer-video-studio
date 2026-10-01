import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from creatorthon_store import (
    claim_next_insight_job,
    enqueue_insight_job,
    finish_insight_job,
    list_insight_jobs,
    retry_insight_job,
)


class CreatorthonInsightQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(
            os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")}
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_jobs_are_deduplicated_and_processed_in_selection_order(self):
        first, created = enqueue_insight_job(self.root, "user-1", {"topic": "First topic"})
        self.assertTrue(created)
        duplicate, created = enqueue_insight_job(self.root, "user-1", {"topic": "  FIRST topic  "})
        self.assertFalse(created)
        self.assertEqual(duplicate["id"], first["id"])
        second, created = enqueue_insight_job(self.root, "user-1", {"topic": "Second topic"})
        self.assertTrue(created)
        self.assertEqual([item["position"] for item in list_insight_jobs(self.root, "user-1")], [1, 2])

        active = claim_next_insight_job(self.root, "user-1")
        self.assertEqual(active["id"], first["id"])
        self.assertIsNone(claim_next_insight_job(self.root, "user-1"))
        finish_insight_job(self.root, "user-1", first["id"], result={"topic": "First topic"})
        self.assertEqual(claim_next_insight_job(self.root, "user-1")["id"], second["id"])

    def test_failed_or_completed_job_can_be_retried_without_reordering(self):
        job, _ = enqueue_insight_job(self.root, "user-1", {"topic": "Retry topic"})
        claim_next_insight_job(self.root, "user-1")
        finish_insight_job(self.root, "user-1", job["id"], error="temporary failure")
        self.assertTrue(retry_insight_job(self.root, "user-1", job["id"]))
        retried = list_insight_jobs(self.root, "user-1")[0]
        self.assertEqual(retried["status"], "queued")
        self.assertEqual(retried["position"], 1)
        claimed = claim_next_insight_job(self.root, "user-1")
        finish_insight_job(self.root, "user-1", claimed["id"], result={"parser_version": 1})
        self.assertTrue(retry_insight_job(self.root, "user-1", job["id"]))
        self.assertEqual(list_insight_jobs(self.root, "user-1")[0]["position"], 1)


if __name__ == "__main__":
    unittest.main()
