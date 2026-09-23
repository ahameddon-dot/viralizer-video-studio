import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import durable_media_pipeline as pipeline


class DurableMediaQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"APP_DATA_DIR": self.temp.name}, clear=False)
        self.environment.start()
        os.environ.pop("DATABASE_URL", None)
        pipeline._SCHEMA_READY = False
        self.root = Path.cwd()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()
        pipeline._SCHEMA_READY = False

    def test_claims_each_job_only_once_while_lease_is_active(self):
        first = pipeline.enqueue(self.root, "user", provider="pixverse", provider_job_id="one")
        second = pipeline.enqueue(self.root, "user", provider="pixverse", provider_job_id="two")
        self.assertEqual([first["id"]], [job["id"] for job in pipeline.due(self.root, 1)])
        self.assertEqual([second["id"]], [job["id"] for job in pipeline.due(self.root, 1)])

    def test_worker_heartbeat_is_visible_to_health_checks(self):
        pipeline.heartbeat(self.root, "worker", state="idle")
        self.assertTrue(pipeline.worker_health(self.root)["ready"])

    def test_permanent_configuration_errors_do_not_retry(self):
        self.assertTrue(pipeline._retryable("connection timeout"))
        self.assertFalse(pipeline._retryable("OPENAI_API_KEY is required to add speech."))


class DurableMediaResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_archived_raw_video_skips_provider_download(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"APP_DATA_DIR": folder}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            pipeline._SCHEMA_READY = False
            root = Path.cwd()
            job = pipeline.enqueue(root, "user", provider="pixverse", provider_job_id="job", raw_video_url="https://media.example/video.mp4", narration="hello")
            job = pipeline._update(root, job["id"], raw_object_key="raw_videos/job.mp4", status="finishing")

            async def restore(path, key):
                path.write_bytes(b"video")
                return True

            async def finish(*args, **kwargs):
                output = Path(folder) / ("viralizer-" + "a" * 32 + ".mp4")
                output.write_bytes(b"finished")
                return output

            download = AsyncMock()
            with patch.object(pipeline, "restore_file", side_effect=restore), patch.object(pipeline, "_download", download), patch.object(pipeline, "finish_video", side_effect=finish), patch.object(pipeline, "upload_file", new=AsyncMock(return_value=True)):
                await pipeline.process_one(root, job)
            download.assert_not_awaited()
            self.assertEqual("completed", pipeline.get(root, "user", job["id"])["status"])
            pipeline._SCHEMA_READY = False


if __name__ == "__main__":
    unittest.main()
