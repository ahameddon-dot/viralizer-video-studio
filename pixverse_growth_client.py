import os
import uuid
from typing import Any

import httpx


GROWTH_BASE_PATH = "/openapi/v1"


class PixVerseGrowthError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", retryable: bool = False, request_id: str = ""):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.request_id = request_id


class PixVerseGrowthClient:
    def __init__(self, api_key: str | None = None, timeout: float = 45.0):
        self.api_key = (api_key or os.getenv("PIXVERSE_GROWTH_API_KEY", "")).strip()
        self.base_url = os.getenv("PIXVERSE_GROWTH_BASE_URL", "https://growth-api.pixverse.ai").rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise PixVerseGrowthError("PIXVERSE_GROWTH_API_KEY is not configured on the server.")
        if not self.api_key.startswith("mh_live_"):
            raise PixVerseGrowthError("Growth Studio requires a production API key beginning with mh_live_.")

    def _headers(self, *, json_request: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Ai-Trace-Id": f"viralizer-{uuid.uuid4()}",
            "Accept": "application/json",
        }
        if json_request:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise PixVerseGrowthError(
                f"Growth Studio returned an invalid response ({response.status_code}).",
                request_id=response.headers.get("X-Request-Id", ""),
            ) from exc
        if response.is_error:
            error = payload.get("error") or {}
            raise PixVerseGrowthError(
                str(error.get("message") or f"Growth Studio request failed ({response.status_code})."),
                code=str(error.get("code") or ""),
                retryable=bool(error.get("retryable")),
                request_id=str(payload.get("request_id") or response.headers.get("X-Request-Id", "")),
            )
        return payload

    async def _request(self, method: str, path: str, **kwargs: Any) -> tuple[dict[str, Any], httpx.Response]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.request(method, f"{self.base_url}{GROWTH_BASE_PATH}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise PixVerseGrowthError(f"Could not connect to PixVerse Growth Studio: {exc}", retryable=True) from exc
        return self._payload(response), response

    async def avatars(self) -> dict[str, Any]:
        payload, _ = await self._request("GET", "/avatars", headers=self._headers())
        return payload

    async def upload_image(self, image: bytes, filename: str, content_type: str) -> dict[str, Any]:
        payload, _ = await self._request(
            "POST", "/image/upload", headers=self._headers(), files={"image": (filename, image, content_type)}
        )
        return payload

    async def create_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        result, _ = await self._request("POST", "/videos", headers=self._headers(json_request=True), json=payload)
        return result

    async def video_details(self, video_id: str) -> dict[str, Any]:
        result, response = await self._request("GET", f"/videos/{video_id}", headers=self._headers())
        result["retry_after"] = int(response.headers.get("Retry-After", "5") or 5)
        return result

    async def list_videos(self, *, limit: int = 20, cursor: str = "", status: str = "") -> dict[str, Any]:
        params: dict[str, Any] = {"limit": max(1, min(100, limit))}
        if cursor:
            params["cursor"] = cursor
        if status:
            params["status"] = status
        result, _ = await self._request("GET", "/videos", headers=self._headers(), params=params)
        return result

    async def edit_video(self, video_id: str, clip_index: int, instruction: str) -> dict[str, Any]:
        result, _ = await self._request(
            "POST", f"/videos/{video_id}/edit", headers=self._headers(json_request=True),
            json={"clip_index": clip_index, "instruction": instruction},
        )
        return result
