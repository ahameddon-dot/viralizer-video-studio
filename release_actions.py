import os
from typing import Any
from urllib.parse import quote

import httpx


class ReleaseActionError(RuntimeError):
    pass


def action_status() -> dict[str, Any]:
    configured = bool(os.getenv("GITHUB_DEPLOY_TOKEN", "").strip())
    return {
        "configured": configured,
        "publishing_enabled": configured,
        "rollback_enabled": configured,
        "repository": os.getenv("GITHUB_REPOSITORY", "ahameddon-dot/viralizer-video-studio"),
        "reason": "Ready for administrator-approved production actions." if configured else "Add GITHUB_DEPLOY_TOKEN to the private beta Render service to enable these buttons.",
    }


def _headers() -> dict[str, str]:
    token = os.getenv("GITHUB_DEPLOY_TOKEN", "").strip()
    if not token:
        raise ReleaseActionError("Production actions are locked because GITHUB_DEPLOY_TOKEN is not configured.")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    repository = action_status()["repository"]
    url = f"https://api.github.com/repos/{repository}{path}"
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        response = await client.request(method, url, json=payload)
    if response.status_code >= 400:
        message = response.json().get("message", response.text[:300]) if response.content else "GitHub request failed"
        raise ReleaseActionError(f"GitHub rejected the release action: {message}")
    return response.json()


async def _ref_sha(ref: str) -> tuple[str, str]:
    data = await _request("GET", f"/git/ref/{quote(ref, safe='/')}")
    obj = data.get("object", {})
    sha, kind = obj.get("sha", ""), obj.get("type", "")
    if kind == "tag":
        tag = await _request("GET", f"/git/tags/{sha}")
        obj = tag.get("object", {})
        sha, kind = obj.get("sha", ""), obj.get("type", "")
    if not sha or kind != "commit":
        raise ReleaseActionError(f"{ref} does not resolve to a release commit.")
    return sha, kind


async def publish_beta(expected_version: str) -> dict[str, Any]:
    confirmation = f"PUBLISH {expected_version}"
    sha, _ = await _ref_sha("heads/develop")
    previous_sha, _ = await _ref_sha("heads/main")
    if sha == previous_sha:
        return {"status": "already_current", "version": expected_version, "commit": sha, "previous_commit": previous_sha, "confirmation": confirmation}
    result = await _request("PATCH", "/git/refs/heads/main", {"sha": sha, "force": False})
    return {"status": "published", "version": expected_version, "commit": result["object"]["sha"], "previous_commit": previous_sha, "confirmation": confirmation}


async def rollback_production(target_version: str) -> dict[str, Any]:
    target_sha, _ = await _ref_sha(f"tags/{target_version}")
    previous_sha, _ = await _ref_sha("heads/main")
    result = await _request("PATCH", "/git/refs/heads/main", {"sha": target_sha, "force": True})
    return {"status": "rolled_back", "version": target_version, "commit": result["object"]["sha"], "previous_commit": previous_sha, "warning": "Render will deploy this production commit automatically."}
