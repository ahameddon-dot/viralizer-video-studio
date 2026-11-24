import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conversation.store import (
    complete_tool_execution,
    confirm_tool_execution,
    create_conversation,
    propose_tool_execution,
)


class ToolExecutionRetryTests(unittest.TestCase):
    def test_failed_provider_execution_is_cloned_for_an_explicit_retry(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            "os.environ", {"DATABASE_URL": "", "APP_DATA_DIR": folder}, clear=False
        ), patch("conversation.store.authorize_tool", side_effect=lambda *args, **kwargs: {
            "authorized": bool(kwargs.get("cost_confirmed")),
            "execution_enabled": bool(kwargs.get("cost_confirmed")),
            "code": "authorized" if kwargs.get("cost_confirmed") else "cost_confirmation_required",
            "reason": "",
        }):
            root = Path(folder)
            conversation = create_conversation(root, "customer", "Retry test")
            first = propose_tool_execution(
                root, "customer", conversation["id"], "generate_keyframe",
                {"concept_id": "concept-1", "scene_index": 24}, "keyframe-retry-1", "corr-retry-1",
            )
            running = confirm_tool_execution(root, "customer", conversation["id"], first["id"])
            complete_tool_execution(root, "customer", running["id"], error={"message": "provider failed"})
            retried = confirm_tool_execution(root, "customer", conversation["id"], first["id"])
            self.assertNotEqual(first["id"], retried["id"])
            self.assertEqual("proposed", retried["status"])
            self.assertEqual("confirmed", retried["approval_status"])


if __name__ == "__main__":
    unittest.main()
