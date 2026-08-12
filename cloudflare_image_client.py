import asyncio
import base64
import os
from typing import Any

import httpx

from openai_image_client import _add_instagram_headline, _headline, prepare_image_prompt


class CloudflareImageError(RuntimeError):
    pass


async def _generate(prompt: str) -> bytes:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id or not token:
        raise CloudflareImageError("Cloudflare Workers AI is not configured on the server.")
    model = os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"prompt": prompt[:2048], "steps": 8},
            )
    except httpx.HTTPError as exc:
        raise CloudflareImageError(f"Could not connect to Cloudflare Workers AI: {exc}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise CloudflareImageError("Cloudflare Workers AI returned an invalid response.") from exc
    if response.is_error or not data.get("success"):
        errors = data.get("errors") or []
        message = (errors[0] or {}).get("message") if errors else None
        raise CloudflareImageError(message or f"Cloudflare image request failed ({response.status_code}).")
    encoded = (data.get("result") or {}).get("image")
    if not encoded:
        raise CloudflareImageError("Cloudflare Workers AI did not return an image.")
    try:
        return base64.b64decode(encoded)
    except (ValueError, TypeError) as exc:
        raise CloudflareImageError("Cloudflare Workers AI returned invalid image data.") from exc


async def generate_cloudflare_image(
    content: dict[str, Any], prompt: str | None = None, purpose: str = "instagram"
) -> bytes:
    prepared = (prompt or await prepare_image_prompt(content, purpose)).strip()
    generated = await _generate(prepared)
    if purpose == "pixverse":
        return generated
    return _add_instagram_headline(generated, _headline(content))


async def generate_cloudflare_album(
    content: dict[str, Any], count: int = 5, prompt: str | None = None
) -> list[bytes]:
    base = prompt or await prepare_image_prompt(content)
    topic = " ".join(str(content.get("topic") or "the topic").split()[:18])
    beats = [
        ("Cover", "Show the strongest single visual that introduces the topic."),
        (f"What is happening with {topic}", "Establish the specific people, organization, product, place, or event involved."),
        ("The development explained", "Visualize the central cause or development with concrete, factual details."),
        ("Why this matters", "Show the practical consequence for the affected audience."),
        ("What happens next", "Show the most likely next development viewers should watch."),
    ][:max(1, min(5, count))]
    prompts = [
        f"{base} Carousel artwork {index + 1} of {len(beats)}. {instruction} Keep one static scene, the same visual identity and no rendered text."
        for index, (_, instruction) in enumerate(beats)
    ]
    generated = list(await asyncio.gather(*(_generate(item) for item in prompts)))
    titles = [_headline(content) if index == 0 else title for index, (title, _) in enumerate(beats)]
    return [_add_instagram_headline(image, title, portrait=False) for image, title in zip(generated, titles)]
