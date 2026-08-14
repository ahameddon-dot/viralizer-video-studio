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


async def analyze_reference_image(
    image_url: str = "", image_bytes: bytes | None = None, content_type: str = "image/png"
) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise OpenAIImageError("OpenAI visual analysis is not configured. Add OPENAI_API_KEY to the server.")
    source = image_url.strip()
    if image_bytes:
        source = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    if not source:
        raise OpenAIImageError("Select or upload a thumbnail first.")
    payload = {
        "model": os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Describe this image in no more than 35 words: main subject, setting, composition, colors, and visible action. Do not guess names or transcribe text."},
                {"type": "input_image", "image_url": source},
            ],
        }],
        "max_output_tokens": 120,
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise OpenAIImageError(detail or "OpenAI could not analyze the selected thumbnail.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise OpenAIImageError("OpenAI could not analyze the selected thumbnail.") from exc
    text = str(data.get("output_text") or "").strip()
    if not text:
        for output in data.get("output") or []:
            for item in output.get("content") or []:
                if item.get("type") == "output_text" and item.get("text"):
                    text += f" {item['text']}"
    if not text.strip():
        raise OpenAIImageError("OpenAI returned no visual description for this thumbnail.")
    return " ".join(text.split())


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
    parsed = urlparse(url)
    if parsed.hostname in {"news.google.com", "www.news.google.com"}:
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
    page = " ".join(page.split())
    script_signals = ("use strict", "function(", "var window", "copyright the closure library", "spdx-license")
    if any(signal in page.lower() for signal in script_signals):
        return ""
    return page[:1800]


async def prepare_image_prompt(content: dict[str, Any], purpose: str = "instagram") -> str:
    def clip(value: Any, limit: int) -> str:
        return " ".join(str(value or "").strip().split()[:limit])

    title = clip(content.get("suggested_title") or content.get("hook") or content.get("topic"), 22)
    reference = clip(content.get("reference_description"), 35)
    if purpose == "pixverse":
        if str(content.get("topic")) == "Reference image" and reference:
            return f"Create a strong vertical image based on this reference: {reference}. Clean composition, realistic detail, no text."
        return " ".join(filter(None, [
            f'Create a strong vertical source image for "{title}."',
            reference,
            "One clear subject, clean composition, realistic detail, no text.",
        ]))
    return " ".join(filter(None, [
        f'Create a premium social-media infographic for "{title}."',
        "Make the idea instantly clear with one strong hero visual and a few concise, readable callouts.",
    ]))


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
    quality = os.getenv("OPENAI_IMAGE_QUALITY", "medium").strip().lower()
    if quality not in {"low", "medium", "high", "auto"}:
        quality = "medium"
    payload = {
        "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        "prompt": image_prompt,
        "size": size,
        "quality": quality,
        "output_format": "png",
        "n": 1,
    }
    subject_match = re.search(r'["“]([^"”]{3,160})["”]', image_prompt)
    safe_subject = subject_match.group(1) if subject_match else " ".join(image_prompt.split()[:20])
    for original, replacement in {
        "mental health": "emotional wellbeing",
        "therapy": "supportive wellbeing services",
        "depression": "wellbeing challenges",
        "anxiety": "stress support",
        "trauma": "recovery support",
    }.items():
        safe_subject = re.sub(original, replacement, safe_subject, flags=re.I)
    safe_prompt = (
        f"Create a clean, hopeful educational infographic about: {safe_subject}. "
        "Use abstract symbols, simple technology icons, calm blue and teal colors, and a clear modern layout. "
        "Keep it non-clinical and non-graphic. No realistic distress, medical procedures, danger, violence, political persuasion, trademarks, or identifiable people."
    )
    response = None
    data: dict[str, Any] = {}
    for attempt_prompt in (image_prompt, safe_prompt):
        payload["prompt"] = attempt_prompt
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
        error_code = str((data.get("error") or {}).get("code") or "").lower()
        if not response.is_error or "moderation" not in error_code or attempt_prompt == safe_prompt:
            break
    if response.is_error:
        error = data.get("error") or {}
        message = error.get("message") or f"Request failed ({response.status_code})."
        details = [
            value
            for value in (
                f"code={error.get('code')}" if error.get("code") else "",
                f"request={response.headers.get('x-request-id')}"
                if response.headers.get("x-request-id")
                else "",
                f"organization={response.headers.get('openai-organization')}"
                if response.headers.get("openai-organization")
                else "",
            )
            if value
        ]
        if details:
            message = f"{message} ({', '.join(details)})"
        if "moderation" in str(error.get("code") or "").lower():
            request_id = response.headers.get("x-request-id") or "not provided"
            raise OpenAIImageError(
                f"OpenAI blocked both the original prompt and a neutral symbolic retry. Edit the title to remove sensitive wording and try again. Request ID: {request_id}."
            )
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
