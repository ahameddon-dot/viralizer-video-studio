import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chat_video_attachments import get, save


class ChatVideoAttachmentTests(unittest.TestCase):
    def test_snapshot_survives_process_memory_loss(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            "os.environ", {"DATABASE_URL": "", "APP_DATA_DIR": folder}, clear=False
        ):
            root = Path(folder)
            saved = save(root, "customer", "chat-1", "doomsday", "quick", {
                "stage": "completed", "finalVideoUrl": "/api/finished-video/viralizer-autopilot-abc.mp4",
                "finalAsset": {"id": "asset-1"},
            })
            restored = get(root, "customer", "chat-1", "doomsday", "quick")
            self.assertEqual(saved["final_asset_id"], "asset-1")
            self.assertEqual(restored["snapshot"]["stage"], "completed")

    def test_customer_and_chat_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            "os.environ", {"DATABASE_URL": "", "APP_DATA_DIR": folder}, clear=False
        ):
            root = Path(folder)
            save(root, "customer-a", "chat-1", "topic", "quick", {"stage": "completed"})
            self.assertIsNone(get(root, "customer-b", "chat-1"))
            self.assertIsNone(get(root, "customer-a", "chat-2"))


if __name__ == "__main__":
    unittest.main()
