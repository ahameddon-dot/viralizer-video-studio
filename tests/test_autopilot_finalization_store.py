import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_finalization_store import claim, claim_due, enqueue, finish, get, renew, retry
from creatorthon_store import _connect


class AutopilotFinalizationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(
            os.environ,
            {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")},
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_job_survives_process_memory_loss(self):
        job = enqueue(self.root, "customer", "concept", {"concept_id": "concept", "title": "Video"})
        claimed = claim(self.root, "customer", "concept")
        self.assertEqual(job["id"], claimed["id"])
        self.assertEqual("processing", get(self.root, "customer", "concept")["status"])
        self.assertIsNone(claim(self.root, "customer", "concept"))

        renew(self.root, "customer", "concept")
        completed = finish(
            self.root,
            "customer",
            "concept",
            result={"video_url": "/api/finished-video/video.mp4"},
        )
        self.assertEqual("succeeded", completed["status"])
        self.assertEqual(
            "/api/finished-video/video.mp4",
            get(self.root, "customer", "concept")["result"]["video_url"],
        )

    def test_expired_processing_job_can_be_reclaimed_after_restart(self):
        enqueue(self.root, "customer", "concept", {"concept_id": "concept"})
        first = claim(self.root, "customer", "concept", lease_seconds=180)
        with _connect(self.root) as db:
            db.execute(
                "UPDATE autopilot_finalization_jobs SET lease_until=0 WHERE id=?",
                (first["id"],),
            )
        recovered = claim(self.root, "customer", "concept", lease_seconds=180)
        self.assertEqual(first["id"], recovered["id"])
        self.assertEqual(2, recovered["attempt"])

    def test_failed_job_is_idempotently_requeued(self):
        first = enqueue(self.root, "customer", "concept", {"concept_id": "concept", "title": "Old"})
        claim(self.root, "customer", "concept")
        finish(self.root, "customer", "concept", error="temporary failure")
        retried = enqueue(self.root, "customer", "concept", {"concept_id": "concept", "title": "New"})
        self.assertEqual(first["id"], retried["id"])
        self.assertEqual("queued", retried["status"])
        self.assertEqual("New", retried["payload"]["title"])

    def test_temporary_failure_returns_processing_job_to_queue(self):
        enqueue(self.root, "customer", "concept", {"concept_id": "concept"})
        claim(self.root, "customer", "concept")
        queued = retry(self.root, "customer", "concept", "R2 timed out")
        self.assertEqual("queued", queued["status"])
        self.assertEqual("R2 timed out", queued["error"])
        self.assertIsNotNone(claim(self.root, "customer", "concept"))

    def test_dedicated_worker_claims_due_jobs(self):
        enqueue(self.root, "customer", "concept", {"concept_id": "concept"})
        jobs = claim_due(self.root)
        self.assertEqual(1, len(jobs))
        self.assertEqual("processing", jobs[0]["status"])
        self.assertEqual([], claim_due(self.root))


if __name__ == "__main__":
    unittest.main()

