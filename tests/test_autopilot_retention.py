import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_growth import save_connection
from autopilot_retention import delete_customer_data, deletion_preview, export_customer_data


class AutopilotRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()
        save_connection(self.root, "customer-1", {"provider": "ga4", "external_account_id": "property-1", "secret_reference": "vault://ga4/one"})
        save_connection(self.root, "customer-2", {"provider": "ga4", "external_account_id": "property-2", "secret_reference": "vault://ga4/two"})

    def tearDown(self):
        self.environment.stop(); self.temp.cleanup()

    def test_export_is_customer_scoped_and_excludes_secret_references(self):
        exported = export_customer_data(self.root, "customer-1")
        rows = exported["tables"]["autopilot_provider_connections"]
        self.assertEqual(1, len(rows))
        self.assertEqual("property-1", rows[0]["external_account_id"])
        self.assertNotIn("secret_reference", rows[0])

    def test_delete_requires_exact_customer_specific_confirmation(self):
        with self.assertRaises(PermissionError):
            delete_customer_data(self.root, "customer-1", "DELETE")
        deleted = delete_customer_data(self.root, "customer-1", "DELETE customer-1")
        self.assertEqual(1, deleted["autopilot_provider_connections"])
        self.assertEqual(0, deletion_preview(self.root, "customer-1")["autopilot_provider_connections"])
        self.assertEqual(1, deletion_preview(self.root, "customer-2")["autopilot_provider_connections"])

    def test_admin_operations_page_exposes_retry_and_dry_run_retention(self):
        page = (Path(__file__).resolve().parents[1] / "static" / "autopilot-admin.html").read_text(encoding="utf-8")
        self.assertIn("/api/admin/autopilot/action-required", page)
        self.assertIn("/api/admin/autopilot/retry/", page)
        self.assertIn("/api/admin/autopilot/retention-preview", page)
        self.assertIn("APPLY RETENTION", page)


if __name__ == "__main__": unittest.main()
