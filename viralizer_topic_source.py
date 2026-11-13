from __future__ import annotations

import os
from typing import Any

import httpx

from mcp_outline_client import MCPOutlineError


async def fetch_v3_worldwide_topics(limit: int = 20) -> tuple[list[dict[str, Any]], str]:
    """Fetch the canonical server-owned V3 topic feed for every Autopilot customer."""
    key = os.getenv("VIRALIZER_V3_TOPICS_API_KEY", "").strip()
    if not key:
        raise MCPOutlineError("V3 topics API key is not configured.")
    url = os.getenv("VIRALIZER_V3_TOPICS_API_URL", "https://v3.viralizer.ai/api/v1/hot-topics").strip()
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.get(url, params={"country": "worldwide", "limit": max(1, min(50, int(limit)))}, headers={"X-API-Key": key, "Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise MCPOutlineError(f"V3 topics API request failed: {exc}") from exc
    if response.status_code != 200:
        raise MCPOutlineError(f"V3 topics API returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise MCPOutlineError("V3 topics API returned invalid JSON.") from exc
    rows = payload.get("topics") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise MCPOutlineError("V3 topics API returned no topics.")
    topics: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row); item["topic"] = str(item.get("topic") or item.get("title") or "").strip()
        if item.get("viral_rank") in (None, "") and item.get("viral_score") not in (None, ""):
            item["viral_rank"] = item["viral_score"]
        if item["topic"]:
            topics.append(item)
    if not topics:
        raise MCPOutlineError("V3 topics API returned no usable topics.")
    return topics, str(payload.get("source") or "Viralizer V3")
