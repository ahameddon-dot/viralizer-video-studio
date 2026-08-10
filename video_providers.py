import os
from typing import Any

import httpx

from pixverse_client import PixVerseClient, PixVerseError


class VideoProviderError(RuntimeError):
    pass


PROVIDERS = {
    "pixverse": {
        "name": "PixVerse",
        "description": "Cinematic text-to-video",
        "enabled": True,
        "configured": lambda: bool(os.getenv("PIXVERSE_API_KEY")),
    },
    "runway": {
        "name": "Runway",
        "description": "Gen-4.5 text or thumbnail-to-video",
        "enabled": True,
        "configured": lambda: bool(os.getenv("RUNWAYML_API_SECRET")),
    },
    "heygen": {
        "name": "HeyGen",
        "description": "Video Agent with script, narration, and scenes",
        "enabled": True,
        "configured": lambda: bool(os.getenv("HEYGEN_API_KEY")),
    },
    "kling": {
        "name": "Kling",
        "description": "Awaiting official API endpoint and access credentials",
        "enabled": False,
        "configured": lambda: False,
    },
    "nativeads": {
        "name": "NativeAds.ai",
        "description": "Awaiting public or partner API documentation",
        "enabled": False,
        "configured": lambda: False,
    },
}


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": provider_id,
            "name": info["name"],
            "description": info["description"],
            "enabled": info["enabled"],
            "configured": bool(info["configured"]()),
        }
        for provider_id, info in PROVIDERS.items()
    ]


def _require_provider(provider: str) -> dict[str, Any]:
    info = PROVIDERS.get(provider)
    if not info:
        raise VideoProviderError(f"Unknown video provider: {provider}.")
    if not info["enabled"]:
        raise VideoProviderError(f"{info['name']} integration is awaiting official API access details.")
    if not info["configured"]():
        env_name = {
            "pixverse": "PIXVERSE_API_KEY",
            "runway": "RUNWAYML_API_SECRET",
            "heygen": "HEYGEN_API_KEY",
        }[provider]
        raise VideoProviderError(f"{info['name']} is not configured. Add {env_name} to .env.")
    return info


def _api_error(response: httpx.Response, provider_name: str) -> VideoProviderError:
    try:
        payload = response.json()
        message = (
            payload.get("error")
            or payload.get("message")
            or payload.get("detail")
            or payload.get("error_message")
            or str(payload)
        )
    except ValueError:
        message = response.text or f"HTTP {response.status_code}"
    return VideoProviderError(f"{provider_name} request failed: {message}")


async def generate_video(
    provider: str,
    prompt: str,
    *,
    content: dict[str, Any],
    duration: int,
    quality: str,
) -> str:
    _require_provider(provider)
    if provider == "pixverse":
        try:
            return str(await PixVerseClient().generate(prompt, duration=duration, quality=quality))
        except PixVerseError as exc:
            raise VideoProviderError(str(exc)) from exc

    if provider == "runway":
        key = os.environ["RUNWAYML_API_SECRET"]
        thumbnail = str(content.get("selected_thumbnail", "")).strip()
        endpoint = "image_to_video" if thumbnail.startswith("https://") else "text_to_video"
        payload: dict[str, Any] = {
            "model": "gen4.5",
            "promptText": prompt[:1000],
            "ratio": "720:1280",
            "duration": max(2, min(10, duration)),
        }
        if endpoint == "image_to_video":
            payload["promptImage"] = thumbnail
        headers = {
            "Authorization": f"Bearer {key}",
            "X-Runway-Version": "2024-11-06",
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"https://api.dev.runwayml.com/v1/{endpoint}", headers=headers, json=payload
            )
        if response.is_error:
            raise _api_error(response, "Runway")
        job_id = response.json().get("id")
        if not job_id:
            raise VideoProviderError("Runway did not return a task ID.")
        return str(job_id)

    if provider == "heygen":
        payload = {
            "prompt": prompt,
            "mode": "generate",
            "orientation": "portrait",
            "incognito_mode": False,
        }
        headers = {"x-api-key": os.environ["HEYGEN_API_KEY"]}
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://api.heygen.com/v3/video-agents", headers=headers, json=payload
            )
        if response.is_error:
            raise _api_error(response, "HeyGen")
        data = response.json().get("data") or {}
        job_id = data.get("video_id")
        if not job_id:
            raise VideoProviderError("HeyGen did not return a video ID.")
        return str(job_id)

    raise VideoProviderError(f"Provider {provider} is not implemented.")


async def video_status(provider: str, job_id: str) -> dict[str, Any]:
    _require_provider(provider)
    if provider == "pixverse":
        try:
            result = await PixVerseClient().status(int(job_id))
        except (PixVerseError, ValueError) as exc:
            raise VideoProviderError(str(exc)) from exc
        raw_status = result.get("status")
        state = "complete" if raw_status == 1 else "failed" if raw_status in (7, 8) else "processing"
        return {"status": state, "url": result.get("url"), "result": result}

    if provider == "runway":
        headers = {
            "Authorization": f"Bearer {os.environ['RUNWAYML_API_SECRET']}",
            "X-Runway-Version": "2024-11-06",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"https://api.dev.runwayml.com/v1/tasks/{job_id}", headers=headers
            )
        if response.is_error:
            raise _api_error(response, "Runway")
        result = response.json()
        raw_status = str(result.get("status", "")).upper()
        state = "complete" if raw_status == "SUCCEEDED" else "failed" if raw_status in ("FAILED", "CANCELED") else "processing"
        output = result.get("output") or []
        return {"status": state, "url": output[0] if output else None, "result": result}

    if provider == "heygen":
        headers = {"x-api-key": os.environ["HEYGEN_API_KEY"]}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"https://api.heygen.com/v3/videos/{job_id}", headers=headers
            )
        if response.is_error:
            raise _api_error(response, "HeyGen")
        result = response.json().get("data") or {}
        raw_status = str(result.get("status", "")).lower()
        state = "complete" if raw_status == "completed" else "failed" if raw_status == "failed" else "processing"
        return {"status": state, "url": result.get("video_url"), "result": result}

    raise VideoProviderError(f"Provider {provider} is not implemented.")
