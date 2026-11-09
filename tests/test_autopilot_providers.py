import asyncio
import base64
import hashlib
import hmac
import json
import unittest

import httpx

from autopilot_providers import GA4DataAdapter, PostForMeAdapter, ShopifyAdminAdapter, verify_post_for_me_webhook, verify_shopify_webhook


class AutopilotProviderTests(unittest.TestCase):
    def test_post_for_me_contract_uses_bearer_idempotency_and_exact_destination(self):
        captured = {}

        def handler(request):
            captured.update({"url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content)})
            return httpx.Response(200, json={"id": "post-1", "status": "processing"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer test-key"})
        adapter = PostForMeAdapter(api_key="test-key", base_url="https://provider.test", client=client)
        asyncio.run(adapter.publish({"caption": "Exact", "destination_id": "social-1", "media_url": "https://media.test/video.mp4"}, "publication:1"))
        asyncio.run(client.aclose())
        self.assertEqual("https://provider.test/v1/social-posts", captured["url"])
        self.assertEqual("Bearer test-key", captured["headers"]["authorization"])
        self.assertEqual("publication:1", captured["headers"]["idempotency-key"])
        self.assertEqual(["social-1"], captured["body"]["social_accounts"])

    def test_ga4_contract_is_read_only_report(self):
        captured = {}

        def handler(request):
            captured.update({"url": str(request.url), "body": json.loads(request.content)})
            return httpx.Response(200, json={"rows": []})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        asyncio.run(GA4DataAdapter("token", client).run_campaign_report("12345"))
        asyncio.run(client.aclose())
        self.assertIn("properties/12345:runReport", captured["url"])
        self.assertIn({"name": "sessions"}, captured["body"]["metrics"])
        self.assertTrue(captured["body"]["returnPropertyQuota"])

    def test_shopify_contract_uses_versioned_graphql_endpoint(self):
        captured = {}

        def handler(request):
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"data": {"shop": {"name": "Test"}}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        asyncio.run(ShopifyAdminAdapter("test.myshopify.com", "token", client).graphql("{ shop { name } }"))
        asyncio.run(client.aclose())
        self.assertEqual("https://test.myshopify.com/admin/api/2026-10/graphql.json", captured["url"])

    def test_webhook_verifiers_reject_mutation(self):
        self.assertTrue(verify_post_for_me_webhook("secret", "secret"))
        self.assertFalse(verify_post_for_me_webhook("changed", "secret"))
        body, secret = b'{"id":"1"}', "shop-secret"
        signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        self.assertTrue(verify_shopify_webhook(body, signature, secret))
        self.assertFalse(verify_shopify_webhook(body + b" ", signature, secret))


if __name__ == "__main__":
    unittest.main()
