import asyncio
import base64
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from autopilot_providers import GA4DataAdapter, PostForMeAdapter, ShopifyAdminAdapter, customer_social_accounts, sanitize_publication_result, verify_post_for_me_webhook, verify_shopify_webhook


class AutopilotProviderTests(unittest.TestCase):
    def test_publication_result_sanitizer_uses_allowlist_and_drops_nested_secrets(self):
        safe = sanitize_publication_result({
            "provider": "post_for_me", "status": "published", "native_url": "https://social.test/post/1",
            "access_token": "secret", "refresh_token": "secret", "authorization": "Bearer secret",
            "social_accounts": [{"id": "account-1", "access_token": "nested-secret"}],
            "account": {"email": "private@example.com"}, "unexpected": "not persisted",
            "is_simulated": False, "data_source": "provider", "provider_mode": "live",
        })
        self.assertEqual("post_for_me", safe["provider"])
        self.assertEqual("https://social.test/post/1", safe["native_url"])
        self.assertFalse(safe["is_simulated"])
        for key in ("access_token", "refresh_token", "authorization", "social_accounts", "account", "unexpected"):
            self.assertNotIn(key, safe)

    def test_publication_result_sanitizer_rejects_non_mapping_payload(self):
        self.assertEqual({}, sanitize_publication_result([{"access_token": "secret"}]))

    def test_publication_result_sanitizer_adds_required_provenance(self):
        live = sanitize_publication_result({"provider": "post_for_me", "status": "processing"})
        fake = sanitize_publication_result({"provider": "fake", "status": "published"})
        self.assertEqual({"is_simulated": False, "data_source": "provider", "provider_mode": "live"},
                         {key: live[key] for key in ("is_simulated", "data_source", "provider_mode")})
        self.assertEqual({"is_simulated": True, "data_source": "synthetic", "provider_mode": "fake"},
                         {key: fake[key] for key in ("is_simulated", "data_source", "provider_mode")})

    def test_post_for_me_contract_uses_bearer_idempotency_and_exact_destination(self):
        captured = {}

        def handler(request):
            captured.update({"url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content)})
            return httpx.Response(200, json={"id": "post-1", "status": "processing"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer test-key"})
        adapter = PostForMeAdapter(api_key="test-key", base_url="https://provider.test", client=client)
        result = asyncio.run(adapter.publish({"caption": "Exact", "destination_id": "social-1", "media_url": "https://media.test/video.mp4"}, "publication:1"))
        asyncio.run(client.aclose())
        self.assertEqual("https://provider.test/v1/social-posts", captured["url"])
        self.assertEqual("Bearer test-key", captured["headers"]["authorization"])
        self.assertEqual("publication:1", captured["headers"]["idempotency-key"])
        self.assertEqual(["social-1"], captured["body"]["social_accounts"])
        self.assertEqual("post-1", result["provider_post_id"])
        self.assertEqual("post_for_me", result["provider"])
        self.assertEqual("provider", result["data_source"])
        self.assertFalse(result["is_simulated"])

    def test_post_for_me_quickstart_connection_contract(self):
        captured = {}
        def handler(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"url": "https://connect.test/session"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = PostForMeAdapter(api_key="test-key", base_url="https://provider.test", client=client)
        result = asyncio.run(adapter.create_connection_url("instagram", "https://app.test/connections", "customer-1"))
        asyncio.run(client.aclose())
        self.assertEqual("https://connect.test/session", result["url"])
        self.assertEqual("customer-1", captured["body"]["external_id"])
        self.assertEqual("instagram", captured["body"]["platform"])

    def test_post_for_me_temporary_media_upload_contract(self):
        calls = []

        def api_handler(request):
            calls.append((request.method, str(request.url)))
            return httpx.Response(200, json={
                "upload_url": "https://uploads.provider.test/signed",
                "media_url": "https://media.provider.test/approved.mp4",
            })

        def upload_handler(request):
            calls.append((request.method, str(request.url), request.headers.get("content-type"), request.content))
            return httpx.Response(200)

        api_client = httpx.AsyncClient(transport=httpx.MockTransport(api_handler))
        upload_client = httpx.AsyncClient(transport=httpx.MockTransport(upload_handler))
        adapter = PostForMeAdapter(api_key="test-key", base_url="https://provider.test", client=api_client, upload_client=upload_client)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "approved.mp4"
            path.write_bytes(b"exact-approved-video")
            media_url = asyncio.run(adapter.upload_media(path))
        asyncio.run(api_client.aclose())
        asyncio.run(upload_client.aclose())
        self.assertEqual("https://media.provider.test/approved.mp4", media_url)
        self.assertEqual(("POST", "https://provider.test/v1/media/create-upload-url"), calls[0])
        self.assertEqual("PUT", calls[1][0])
        self.assertEqual("video/mp4", calls[1][2])
        self.assertEqual(b"exact-approved-video", calls[1][3])

    def test_post_for_me_accounts_are_strictly_customer_scoped(self):
        response = {"data": [
            {"id": "ig-1", "platform": "instagram", "username": "owner", "external_id": "customer-1", "status": "connected"},
            {"id": "yt-2", "platform": "youtube", "username": "other", "external_id": "customer-2", "status": "connected"},
            {"id": "shared", "platform": "instagram", "username": "dashboard", "status": "connected"},
        ]}
        self.assertEqual(["ig-1"], [item["id"] for item in customer_social_accounts(response, "customer-1")])
        self.assertEqual([], customer_social_accounts(response, "customer-1", "youtube"))

    def test_post_for_me_account_response_shapes_are_normalized(self):
        account = {"social_account_id": "yt-1", "provider": "youtube", "display_name": "Channel", "external_id": "customer-1"}
        for response in ([account], {"accounts": [account]}, {"items": [account]}, {"results": [account]}):
            self.assertEqual([{"id": "yt-1", "platform": "youtube", "username": "Channel", "status": "connected"}],
                             customer_social_accounts(response, "customer-1"))

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
