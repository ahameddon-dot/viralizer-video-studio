import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from creatorthon_store import (
    claim_next_insight_job,
    delete_insight_job,
    enqueue_insight_job,
    finish_insight_job,
    get_cached_category_topics,
    get_cached_topic_insight,
    list_insight_jobs,
    retry_insight_job,
    save_cached_category_topics,
    save_cached_topic_insight,
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

    def test_one_selected_insight_can_be_deleted_without_affecting_the_others(self):
        first, _ = enqueue_insight_job(self.root, "user-1", {"topic": "First topic"})
        second, _ = enqueue_insight_job(self.root, "user-1", {"topic": "Second topic"})
        self.assertTrue(delete_insight_job(self.root, "user-1", first["id"]))
        self.assertFalse(delete_insight_job(self.root, "another-user", second["id"]))
        self.assertEqual([item["id"] for item in list_insight_jobs(self.root, "user-1")], [second["id"]])

    def test_scheduled_topic_and_insight_cache_is_shared_and_normalized(self):
        topics = [{"topic": "A Fashion Topic", "category": "Fashion"}]
        save_cached_category_topics(self.root, "Fashion", topics, ttl_seconds=3600)
        self.assertEqual(get_cached_category_topics(self.root, " fashion "), topics)

        result = {"parser_version": 2, "metrics": {"viral_topic_rank": 17}}
        save_cached_topic_insight(self.root, "A Fashion Topic", result, ttl_seconds=3600)
        cached = get_cached_topic_insight(self.root, "  a FASHION topic ")
        self.assertEqual(cached["metrics"]["viral_topic_rank"], 17)
        self.assertTrue(cached["cached"])


if __name__ == "__main__":
    unittest.main()
