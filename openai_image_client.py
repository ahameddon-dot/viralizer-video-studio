import asyncio
import base64
import html
import io
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont


class OpenAIImageError(RuntimeError):
    pass


def _selected_source_url(content: dict[str, Any]) -> str:
    candidates = [content.get("source_url"), content.get("url"), content.get("link")]
    candidates.extend(content.get("source_urls") or [])
    for value in candidates:
        url = str(value or "").strip()
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return url
    return ""


async def _source_excerpt(url: str) -> str:
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 ViralizerVideoStudio/1.0"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError:
        return ""
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        return ""
    page = response.text[:500_000]
    page = re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html.unescape(page)
    return " ".join(page.split())[:5000]


async def prepare_image_prompt(content: dict[str, Any], purpose: str = "instagram") -> str:
    def clip(value: Any, limit: int) -> str:
        return " ".join(str(value or "").strip().split()[:limit])

    topic = clip(content.get("topic"), 28)
    message = clip(content.get("suggested_title") or content.get("hook"), 24)
    angle = clip(content.get("creator_angle"), 35)
    why = clip(content.get("why_it_matters"), 55)
    idea = clip(content.get("video_idea"), 75)
    prompt = " ".join(filter(None, [
        "Create one static editorial image, not a video frame sequence, storyboard, montage, reel, or collage.",
        f"Subject: {topic}." if topic else "",
        f"Central message to communicate visually: {message}." if message else "",
        f"Factual story context: {idea}." if idea else "",
        f"Editorial angle: {angle}." if angle else "",
        f"Why the story matters: {why}." if why else "",
        "Choose the single most meaningful real-world moment, person, product, place, or consequence as the focal subject. Use only a few concrete supporting objects that clarify the story. Make the relationship between the focal subject and the supporting details immediately understandable on a phone screen.",
        "Use realistic premium editorial photography, strong visual hierarchy, natural depth, accurate identities, and high contrast. Compose vertically in a 4:5 Instagram-post layout with clear negative space near the top for a headline that will be added later by the application.",
        "Do not render any words, letters, numbers, captions, headlines, logos made from fake lettering, interface elements, random symbols, watermarks, borders, or decorative typography. Do not include camera movement, transitions, multiple scenes, a timeline, narration, or video instructions. Do not invent facts absent from the supplied content.",
    ]))
    if purpose == "pixverse":
        prompt = prompt.replace(
            "Compose vertically in a 4:5 Instagram-post layout with clear negative space near the top for a headline that will be added later by the application.",
            "Compose vertically in a 2:3 layout suitable as a clean PixVerse source image. Keep the main subject centered with safe space around it for later animation."
        )
    source_url = _selected_source_url(content)
    excerpt = await _source_excerpt(source_url)
    if excerpt:
        prompt += (
            f" Selected-topic source: {source_url}. Source-page context: {excerpt}. "
            "Base all concrete visual details on this source context and the MCP outline."
        )
    elif source_url:
        prompt += f" Selected-topic source URL: {source_url}. Use the MCP outline as the factual basis."
    return prompt[:9000]


def _headline(content: dict[str, Any], fallback: str = "") -> str:
    value = content.get("suggested_title") or content.get("hook") or content.get("topic") or fallback
    return " ".join(str(value).strip().split()[:12])


def _add_instagram_headline(image_bytes: bytes, headline: str, *, portrait: bool = True) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
    if portrait:
        target_ratio = 4 / 5
        current_ratio = image.width / image.height
        if current_ratio > target_ratio:
            width = round(image.height * target_ratio)
            left = (image.width - width) // 2
            image = image.crop((left, 0, left + width, image.height))
        elif current_ratio < target_ratio:
            height = round(image.width / target_ratio)
            top = (image.height - height) // 2
            image = image.crop((0, top, image.width, top + height))

    headline = " ".join(headline.split())
    if headline:
        draw = ImageDraw.Draw(image, "RGBA")
        font_size = max(34, image.width // 15)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
        except OSError:
            font = ImageFont.load_default(size=font_size)
        max_width = image.width - image.width // 8
        words, lines, current = headline.split(), [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        lines = lines[:3]
        line_height = font_size + font_size // 4
        box_top = image.height // 18
        box_height = line_height * len(lines) + font_size
        margin = image.width // 16
        draw.rounded_rectangle(
            (margin // 2, box_top - font_size // 2, image.width - margin // 2, box_top + box_height),
            radius=font_size // 3,
            fill=(5, 7, 12, 190),
        )
        y = box_top
        for line in lines:
            draw.text((margin, y), line, font=font, fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0, 180))
            y += line_height
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def _generate_image(image_prompt: str, size: str = "1024x1024") -> bytes:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise OpenAIImageError("ChatGPT image generation is not configured. Add OPENAI_API_KEY to the server.")
    payload = {
        "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        "prompt": image_prompt,
        "size": size,
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


async def generate_instagram_image(
    content: dict[str, Any], prompt: str | None = None, purpose: str = "instagram"
) -> bytes:
    prepared = (prompt or await prepare_image_prompt(content, purpose)).strip()
    size = "1024x1536"
    generated = await _generate_image(prepared, size)
    if purpose == "pixverse":
        return generated
    return _add_instagram_headline(generated, _headline(content))


async def generate_instagram_album(
    content: dict[str, Any], count: int = 5, prompt: str | None = None
) -> list[bytes]:
    base = prompt or await prepare_image_prompt(content)
    topic = " ".join(str(content.get("topic") or "the topic").split()[:24])
    story_beats = [
        "Cover slide: introduce the topic with the strongest single visual and an immediate curiosity gap.",
        "Context slide: clearly establish the people, place, organization, product, or event involved.",
        "Explanation slide: visualize the central cause, process, or development using concrete details.",
        "Impact slide: show why this matters to the audience and the practical real-world consequence.",
        "Closing slide: show what viewers should watch next, with a memorable concluding visual.",
    ][:max(1, min(5, count))]
    prompts = [
        f"{base} This is artwork {index + 1} of {len(story_beats)} in one cohesive Instagram carousel about {topic}. {beat} Keep the same color palette, art direction, visual identity, and subject continuity. Create one static square artwork without any rendered text; the application will add the slide headline afterward."
        for index, beat in enumerate(story_beats)
    ]
    generated = list(await asyncio.gather(*(_generate_image(item) for item in prompts)))
    slide_titles = [
        _headline(content),
        f"What is happening with {topic}",
        "The development explained",
        "Why this matters",
        "What happens next",
    ][:len(generated)]
    return [_add_instagram_headline(image, title, portrait=False) for image, title in zip(generated, slide_titles)]
