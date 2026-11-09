import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autopilot_growth import growth_dashboard, list_connections, save_attribution_event, save_connection
from creatorthon_store import _connect


class AutopilotGrowthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data")})
        self.environment.start()
        with _connect(self.root):
            pass

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_connection_api_never_returns_secret_reference(self):
        connection = save_connection(self.root, "customer-1", {
            "provider": "post_for_me", "external_account_id": "account-1", "display_name": "YouTube",
            "status": "connected", "capabilities": ["posts", "feeds"], "secret_reference": "vault://post-for-me/account-1",
        })
        self.assertNotIn("secret_reference", connection)
        self.assertNotIn("secret_reference", list_connections(self.root, "customer-1")[0])
        self.assertEqual([], list_connections(self.root, "customer-2"))

    def test_raw_provider_token_is_rejected(self):
        with self.assertRaises(ValueError):
            save_connection(self.root, "customer-1", {"provider": "ga4", "secret_reference": "plain-token"})

    def test_ga4_and_shopify_revenue_are_never_summed(self):
        save_attribution_event(self.root, "customer-1", {
            "provider": "ga4", "event_key": "ga-1", "sessions": 100, "conversions": 4,
            "revenue": 250, "currency": "USD", "attribution_status": "attributed",
        })
        save_attribution_event(self.root, "customer-1", {
            "provider": "shopify", "event_key": "order-1", "conversions": 1,
            "revenue": 180, "currency": "USD", "attribution_status": "unattributed",
        })
        dashboard = growth_dashboard(self.root, "customer-1")
        self.assertEqual(250, dashboard["commerce"]["ga4"]["reported_revenue"])
        self.assertEqual(180, dashboard["commerce"]["shopify"]["order_revenue"])
        self.assertEqual(180, dashboard["commerce"]["unattributed_shopify_revenue"])
        self.assertNotIn("total_revenue", dashboard["commerce"])

    def test_attribution_ingestion_is_idempotent(self):
        request = {"provider": "shopify", "event_key": "order-2", "revenue": 50}
        first, created = save_attribution_event(self.root, "customer-1", request)
        duplicate, duplicate_created = save_attribution_event(self.root, "customer-1", request)
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first["id"], duplicate["id"])


if __name__ == "__main__":
    unittest.main()
