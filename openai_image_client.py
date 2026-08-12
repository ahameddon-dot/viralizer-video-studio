import asyncio
import base64
import os
from typing import Any

import httpx

from pixverse_client import build_image_prompt


class OpenAIImageError(RuntimeError):
    pass


async def _generate_image(image_prompt: str) -> bytes:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise OpenAIImageError("ChatGPT image generation is not configured. Add OPENAI_API_KEY to the server.")
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


async def generate_instagram_image(content: dict[str, Any], prompt: str | None = None) -> bytes:
    return await _generate_image((prompt or build_image_prompt(content)).strip())


async def generate_instagram_album(content: dict[str, Any], count: int = 5) -> list[bytes]:
    base = build_image_prompt(content)
    topic = " ".join(str(content.get("topic") or "the topic").split()[:24])
    story_beats = [
        "Cover slide: introduce the topic with the strongest single visual and an immediate curiosity gap.",
        "Context slide: clearly establish the people, place, organization, product, or event involved.",
        "Explanation slide: visualize the central cause, process, or development using concrete details.",
        "Impact slide: show why this matters to the audience and the practical real-world consequence.",
        "Closing slide: show what viewers should watch next, with a memorable concluding visual.",
    ][:max(1, min(5, count))]
    prompts = [
        f"{base} This is image {index + 1} of {len(story_beats)} in one cohesive Instagram carousel about {topic}. {beat} Keep the same color palette, art direction, visual identity, and subject continuity across every carousel image. Create this slide as a complete standalone square image."
        for index, beat in enumerate(story_beats)
    ]
    return list(await asyncio.gather(*(_generate_image(prompt) for prompt in prompts)))
