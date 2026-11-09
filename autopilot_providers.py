"""Real provider HTTP adapters with explicit activation and no import-time calls."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

import httpx


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    def __init__(self, provider: str, status_code: int, message: str, retryable: bool = False):
        super().__init__(f"{provider} request failed ({status_code}): {message[:300]}")
        self.provider, self.status_code, self.retryable = provider, status_code, retryable


async def _json_request(client: httpx.AsyncClient, provider: str, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        try:
            detail = (response.json().get("message") or response.json().get("detail") or "Request rejected")
        except (ValueError, AttributeError):
            detail = "Request rejected"
        raise ProviderResponseError(provider, response.status_code, str(detail), response.status_code in {408, 429, 500, 502, 503, 504})
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderResponseError(provider, response.status_code, "Invalid JSON response") from exc


class PostForMeAdapter:
    def __init__(self, api_key: str | None = None, base_url: str = "https://api.postforme.dev", client: httpx.AsyncClient | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("POST_FOR_ME_API_KEY", "")
        if not self.api_key:
            raise ProviderConfigurationError("POST_FOR_ME_API_KEY is not configured.")
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})

    async def create_connection_url(self, platform: str, redirect_url: str, external_id: str) -> dict[str, Any]:
        return await _json_request(self.client, "post_for_me", "POST", f"{self.base_url}/v1/social-accounts/auth-url",
                                   json={"platform": platform, "redirect_url": redirect_url, "external_id": external_id, "permissions": ["posts", "feeds"]})

    async def list_accounts(self, platform: str = "") -> dict[str, Any]:
        return await _json_request(self.client, "post_for_me", "GET", f"{self.base_url}/v1/social-accounts", params={"platform": platform} if platform else None)

    async def publish(self, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"caption": publication.get("caption", ""), "social_accounts": [publication["destination_id"]],
                                   "media": [{"url": publication.get("media_url", "")}], "external_id": idempotency_key}
        if publication.get("scheduled_at"):
            payload["scheduled_at"] = publication["scheduled_at"]
        return await _json_request(self.client, "post_for_me", "POST", f"{self.base_url}/v1/social-posts", json=payload,
                                   headers={"Idempotency-Key": idempotency_key})

    async def feed(self, social_account_id: str) -> dict[str, Any]:
        return await _json_request(self.client, "post_for_me", "GET", f"{self.base_url}/v1/social-account-feeds/{social_account_id}", params={"expand": "metrics"})


class GA4DataAdapter:
    def __init__(self, access_token: str, client: httpx.AsyncClient | None = None):
        if not access_token:
            raise ProviderConfigurationError("A GA4 OAuth access token reference must be resolved server-side.")
        self.client = client or httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})

    async def run_campaign_report(self, property_id: str, start_date: str = "14daysAgo", end_date: str = "yesterday") -> dict[str, Any]:
        if not property_id.isdigit():
            raise ValueError("GA4 property ID must be numeric.")
        payload = {"dateRanges": [{"startDate": start_date, "endDate": end_date}],
                   "dimensions": [{"name": name} for name in ("sessionSource", "sessionMedium", "sessionCampaignName", "sessionManualAdContent")],
                   "metrics": [{"name": name} for name in ("sessions", "engagedSessions", "keyEvents", "totalRevenue")],
                   "returnPropertyQuota": True, "limit": "10000"}
        return await _json_request(self.client, "ga4", "POST", f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport", json=payload)


class ShopifyAdminAdapter:
    def __init__(self, shop_domain: str, access_token: str, client: httpx.AsyncClient | None = None, api_version: str = "2026-10"):
        if not shop_domain.endswith(".myshopify.com") or any(char in shop_domain for char in "/?#"):
            raise ValueError("Invalid Shopify shop domain.")
        if not access_token:
            raise ProviderConfigurationError("A Shopify offline access token reference must be resolved server-side.")
        self.url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        self.client = client or httpx.AsyncClient(timeout=30, headers={"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"})

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await _json_request(self.client, "shopify", "POST", self.url, json={"query": query, "variables": variables or {}})
        if result.get("errors"):
            raise ProviderResponseError("shopify", 200, "GraphQL returned errors")
        return result


def verify_post_for_me_webhook(received_secret: str, expected_secret: str) -> bool:
    return bool(received_secret and expected_secret and hmac.compare_digest(received_secret.encode(), expected_secret.encode()))


def verify_shopify_webhook(raw_body: bytes, signature: str, client_secret: str) -> bool:
    if not raw_body or not signature or not client_secret:
        return False
    expected = base64.b64encode(hmac.new(client_secret.encode(), raw_body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, signature)


def provider_readiness() -> dict[str, Any]:
    return {
        "pixverse": {"configured": bool(os.getenv("PIXVERSE_GROWTH_API_KEY") or os.getenv("PIXVERSE_API_KEY")), "capabilities": ["video", "image"]},
        "post_for_me": {"configured": bool(os.getenv("POST_FOR_ME_API_KEY")), "webhook_configured": bool(os.getenv("POST_FOR_ME_WEBHOOK_SECRET")), "mode": "quickstart"},
        "ga4": {"configured": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")), "scope": "analytics.readonly"},
        "shopify": {"configured": bool(os.getenv("SHOPIFY_CLIENT_ID") and os.getenv("SHOPIFY_CLIENT_SECRET")), "scopes": ["read_products", "read_orders"]},
        "live_calls_enabled": os.getenv("AUTOPILOT_PROVIDER_CALLS_ENABLED", "").lower() in {"1", "true", "yes"},
    }
