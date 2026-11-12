"""Real provider HTTP adapters with explicit activation and no import-time calls."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


PUBLICATION_RESULT_FIELDS = frozenset({
    "provider", "provider_post_id", "native_post_id", "native_url", "status",
    "platform", "created_at", "updated_at", "scheduled_at", "published_at",
    "data_source", "provider_mode", "is_simulated",
})


def sanitize_publication_result(result: Any) -> dict[str, Any]:
    """Return the small, non-sensitive subset safe to persist and expose.

    Provider payloads are untrusted. This intentionally uses an allowlist rather
    than attempting to enumerate every possible token, credential, account, or
    authorization field that a provider may add in the future.
    """
    if not isinstance(result, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in PUBLICATION_RESULT_FIELDS:
        value = result.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    provider = str(safe.get("provider") or "")
    simulated_value = safe.get("is_simulated")
    simulated = provider == "fake" if simulated_value is None else bool(simulated_value)
    safe["is_simulated"] = simulated
    safe["data_source"] = str(safe.get("data_source") or ("synthetic" if simulated else "provider"))
    safe["provider_mode"] = str(safe.get("provider_mode") or ("fake" if simulated else "live"))
    return safe


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    def __init__(self, provider: str, status_code: int, message: str, retryable: bool = False):
        super().__init__(f"{provider} request failed ({status_code}): {message[:300]}")
        self.provider, self.status_code, self.retryable = provider, status_code, retryable


def _provider_error_detail(payload: Any) -> str:
    """Extract a useful validation error without echoing arbitrary provider data."""
    if isinstance(payload, str):
        return payload[:300]
    if isinstance(payload, list):
        details = [_provider_error_detail(item) for item in payload[:5]]
        return "; ".join(detail for detail in details if detail)[:300]
    if not isinstance(payload, dict):
        return ""
    details: list[str] = []
    for key in ("message", "detail", "error", "errors"):
        if key not in payload:
            continue
        value = payload[key]
        if key == "error" and isinstance(value, dict):
            value = {safe_key: value[safe_key] for safe_key in ("message", "detail", "code", "errors") if safe_key in value}
        detail = _provider_error_detail(value)
        if detail and detail not in details:
            details.append(detail)
    if not details:
        field = str(payload.get("field") or payload.get("loc") or "").strip()
        message = str(payload.get("msg") or payload.get("reason") or "").strip()
        if message:
            details.append(f"{field}: {message}" if field else message)
    return "; ".join(details)[:300]


async def _json_request(client: httpx.AsyncClient, provider: str, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        try:
            detail = _provider_error_detail(response.json()) or "Request rejected"
        except ValueError:
            detail = "Request rejected"
        raise ProviderResponseError(provider, response.status_code, str(detail), response.status_code in {408, 429, 500, 502, 503, 504})
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderResponseError(provider, response.status_code, "Invalid JSON response") from exc


class PostForMeAdapter:
    def __init__(self, api_key: str | None = None, base_url: str = "https://api.postforme.dev", client: httpx.AsyncClient | None = None,
                 upload_client: httpx.AsyncClient | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("POST_FOR_ME_API_KEY", "")
        if not self.api_key:
            raise ProviderConfigurationError("POST_FOR_ME_API_KEY is not configured.")
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        self.upload_client = upload_client

    async def create_connection_url(self, platform: str, redirect_url: str, external_id: str) -> dict[str, Any]:
        return await _json_request(self.client, "post_for_me", "POST", f"{self.base_url}/v1/social-accounts/auth-url",
                                   json={"platform": platform, "redirect_url": redirect_url, "external_id": external_id, "permissions": ["posts", "feeds"]})

    async def list_accounts(self, platform: str = "") -> dict[str, Any]:
        return await _json_request(self.client, "post_for_me", "GET", f"{self.base_url}/v1/social-accounts", params={"platform": platform} if platform else None)

    async def upload_media(self, path: Path, content_type: str = "video/mp4") -> str:
        """Stage a local file in Post for Me's short-lived media storage."""
        upload = await _json_request(
            self.client,
            "post_for_me",
            "POST",
            f"{self.base_url}/v1/media/create-upload-url",
            json={},
        )
        upload_url = str(upload.get("upload_url") or "")
        media_url = str(upload.get("media_url") or "")
        if urlparse(upload_url).scheme != "https" or urlparse(media_url).scheme != "https":
            raise ProviderResponseError("post_for_me", 502, "Media upload service returned invalid URLs", retryable=True)
        upload_client = self.upload_client or httpx.AsyncClient(timeout=180, follow_redirects=False)
        try:
            response = await upload_client.put(upload_url, content=path.read_bytes(), headers={"Content-Type": content_type})
        finally:
            if self.upload_client is None:
                await upload_client.aclose()
        if response.status_code >= 400:
            raise ProviderResponseError(
                "post_for_me",
                response.status_code,
                "Temporary media upload failed",
                response.status_code in {408, 429, 500, 502, 503, 504},
            )
        return media_url

    async def publish(self, publication: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"caption": publication.get("caption", ""), "social_accounts": [publication["destination_id"]],
                                   "media": [{"url": publication.get("media_url", "")}], "external_id": idempotency_key}
        if publication.get("scheduled_at"):
            payload["scheduled_at"] = publication["scheduled_at"]
        result = await _json_request(self.client, "post_for_me", "POST", f"{self.base_url}/v1/social-posts", json=payload,
                                     headers={"Idempotency-Key": idempotency_key})
        return sanitize_publication_result({
            **result,
            "provider": "post_for_me",
            "provider_post_id": str(result.get("id") or result.get("post_id") or ""),
            "status": str(result.get("status") or "processing").lower(),
            "data_source": "provider",
            "provider_mode": "live",
            "is_simulated": False,
        })

    async def feed(self, social_account_id: str) -> dict[str, Any]:
        return await _json_request(self.client, "post_for_me", "GET", f"{self.base_url}/v1/social-account-feeds/{social_account_id}", params={"expand": "metrics"})


def customer_social_accounts(result: Any, customer_id: str, platform: str = "") -> list[dict[str, Any]]:
    """Build a minimal customer-owned account list from a provider response.

    Quickstart receives the Viralizer customer id as ``external_id`` when the
    hosted connection session is created. Accounts without that exact owner
    marker are deliberately excluded, including accounts connected directly
    in the shared Post for Me dashboard.
    """
    if isinstance(result, list):
        rows = result
    elif isinstance(result, dict):
        rows = next((result.get(key) for key in ("data", "accounts", "items", "results") if isinstance(result.get(key), list)), [])
    else:
        rows = []
    expected_platform = platform.strip().lower()
    owned: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict) or str(raw.get("external_id") or "") != customer_id:
            continue
        provider = str(raw.get("platform") or raw.get("provider") or "").lower()
        if expected_platform and provider != expected_platform:
            continue
        account_id = str(raw.get("id") or raw.get("social_account_id") or "")
        if not account_id:
            continue
        owned.append({
            "id": account_id,
            "platform": provider,
            "username": str(raw.get("username") or raw.get("name") or raw.get("display_name") or provider.title()),
            "status": str(raw.get("status") or "connected").lower(),
        })
    return owned


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
