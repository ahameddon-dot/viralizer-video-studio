import base64
import os
from typing import Any

import httpx

from pixverse_client import build_image_prompt


class OpenAIImageError(RuntimeError):
    pass


async def generate_instagram_image(content: dict[str, Any], prompt: str | None = None) -> bytes:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise OpenAIImageError("ChatGPT image generation is not configured. Add OPENAI_API_KEY to the server.")
    image_prompt = (prompt or build_image_prompt(content)).strip()
    payload = {
        "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        "prompt": image_prompt,
        "size": "1024x1024",
        "quality": os.getenv("OPENAI_IMAGE_QUALITY", "medium"),
        "output_format": "png",
        "n": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise OpenAIImageError(f"Could not connect to ChatGPT image generation: {exc}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise OpenAIImageError("ChatGPT image generation returned an invalid response.") from exc
    if response.is_error:
        message = (data.get("error") or {}).get("message") or f"Request failed ({response.status_code})."
        raise OpenAIImageError(str(message))
    encoded = ((data.get("data") or [{}])[0]).get("b64_json")
    if not encoded:
        raise OpenAIImageError("ChatGPT image generation did not return an image.")
    try:
        return base64.b64decode(encoded)
    except (ValueError, TypeError) as exc:
        raise OpenAIImageError("ChatGPT image generation returned invalid image data.") from exc
