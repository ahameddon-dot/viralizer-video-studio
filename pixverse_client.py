import os
import re
import uuid
from typing import Any

import httpx


PIXVERSE_BASE_URL = "https://app-api.pixverse.ai/openapi/v2"


class PixVerseError(RuntimeError):
    pass


def build_video_prompt(content: dict[str, Any], duration: int = 5) -> str:
    """Turn the outline returned by the topic MCP into one PixVerse prompt."""
    def clip(value: Any, word_limit: int) -> str:
        return " ".join(str(value or "").strip().split()[:word_limit])

    topic = clip(content.get("topic"), 18)
    suggested_title = clip(content.get("suggested_title"), 18)
    raw_idea = str(content.get("video_idea", "")).strip()
    idea = clip(raw_idea, 42)
    hook = clip(content.get("hook"), 18)
    angle = clip(content.get("creator_angle"), 16)
    why = clip(content.get("why_it_matters"), 24)
    keywords = clip(", ".join(content.get("hashtags", [])), 12)

    outline_points: list[str] = []
    for line in raw_idea.splitlines():
        cleaned = re.sub(r"^\s*(?:\d+(?:\.\d+)*[.)]?|[-*•])\s*", "", line).strip()
        if cleaned and cleaned.lower() != idea.lower() and len(cleaned.split()) >= 2:
            outline_points.append(clip(cleaned, 9))
    key_points = "; ".join(outline_points[:4])

    topic_lower = topic.lower()
    visual_anchors = ""
    brand_direction = "Use accurate subject identity; an explicitly named brand may use its authentic emblem, never fake lettering."
    if "nvidia" in topic_lower:
        visual_anchors = (
            "Use the authentic NVIDIA green eye emblem and black-green identity, then show GPU chips, "
            "AI accelerators, engineers, server racks, and a large AI data center."
        )

    parts = [
        f"Create a coherent {duration}-second vertical explanatory video, not a random montage or generic reel.",
        f"Topic: {topic}." if topic else "",
        f"Editorial title direction: {suggested_title}." if suggested_title else "",
        f"Content to explain: {idea}." if idea else "",
        f"Key explanation points: {key_points}." if key_points else "",
        f"Relevant concepts: {keywords}." if keywords else "",
        f"Visual storyboard: Begin with a literal attention-grabbing image for this hook: {hook}." if hook else "",
        f"Then establish the context: {why}." if why else "",
        f"Next clearly demonstrate the cause, process, and real-world consequence from this angle: {angle}." if angle else "",
        "End with a decisive visual outcome that makes the topic's importance immediately understandable.",
        visual_anchors,
        brand_direction,
        "Every shot must directly explain the supplied content through specific actions, objects, locations, and cause-and-effect transitions.",
        "Use realistic continuity and stable subjects. Except for an authentic requested emblem, show no readable words, captions, subtitles, fake labels, random symbols, or watermarks.",
    ]
    prompt = " ".join(part for part in parts if part)
    words = prompt.split()
    return " ".join(words[:200])


def build_image_prompt(content: dict[str, Any]) -> str:
    """Turn the hidden MCP outline into a detailed square social-image prompt."""
    def clip(value: Any, limit: int) -> str:
        return " ".join(str(value or "").strip().split()[:limit])

    topic = clip(content.get("topic"), 24)
    title = clip(content.get("suggested_title") or content.get("hook"), 18)
    hook = clip(content.get("hook"), 24)
    idea = clip(content.get("video_idea"), 75)
    angle = clip(content.get("creator_angle"), 35)
    why = clip(content.get("why_it_matters"), 45)
    return " ".join(filter(None, [
        "Create a polished square 1:1 Instagram editorial post image that visually explains the supplied story.",
        f"Topic: {topic}." if topic else "",
        f"Main message: {title}." if title else "",
        f"Attention hook: {hook}." if hook else "",
        f"Content that the image must communicate: {idea}." if idea else "",
        f"Creator angle: {angle}." if angle else "",
        f"Why it matters: {why}." if why else "",
        "Use one strong focal subject, specific supporting objects and a clear visual hierarchy. Make the subject immediately understandable on a phone screen. Use premium newsroom-meets-social-media art direction, realistic details, strong contrast and safe margins for Instagram cropping.",
        "Do not invent facts, people, brands, flags, statistics, or events that are not in the supplied content. Avoid gibberish, illegible typography, random symbols, watermarks and fake logos. Prefer visual storytelling instead of paragraphs of text.",
    ]))[:3500]


class PixVerseClient:
    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.getenv("PIXVERSE_API_KEY", "")
        self.timeout = timeout
        if not self.api_key:
            raise PixVerseError("PIXVERSE_API_KEY is not configured on the server.")

    def _headers(self, *, unique_request: bool = False) -> dict[str, str]:
        headers = {"API-KEY": self.api_key}
        if unique_request:
            headers["Ai-trace-id"] = str(uuid.uuid4())
        return headers

    @staticmethod
    def _unwrap(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise PixVerseError("PixVerse returned an invalid response.") from exc
        if response.is_error or payload.get("ErrCode") != 0:
            message = payload.get("ErrMsg") or f"PixVerse request failed ({response.status_code})."
            raise PixVerseError(str(message))
        return payload.get("Resp") or {}

    async def generate(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "9:16",
        duration: int = 5,
        quality: str = "720p",
        model: str = "v6",
        negative_prompt: str | None = None,
    ) -> int:
        payload = {
            "aspect_ratio": aspect_ratio,
            "duration": duration,
            "model": model,
            "prompt": prompt,
            "negative_prompt": negative_prompt or (
                "text, words, letters, typography, captions, subtitles, title cards, headlines, "
                "numbers, random symbols, malformed glyphs, signs, labels, fake logos, misspelled brands, "
                "watermarks, readable UI text, documents, newspapers, posters, banners, "
                "speech bubbles, distorted writing, gibberish text, pseudo-text, foreign characters"
            ),
            "quality": quality,
            "seed": 0,
            "water_mark": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{PIXVERSE_BASE_URL}/video/text/generate",
                    headers=self._headers(unique_request=True),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise PixVerseError(f"Could not connect to PixVerse: {exc}") from exc
        result = self._unwrap(response)
        video_id = result.get("video_id")
        if video_id is None:
            raise PixVerseError("PixVerse did not return a video id.")
        return int(video_id)

    async def status(self, video_id: int) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{PIXVERSE_BASE_URL}/video/result/{video_id}",
                    headers=self._headers(unique_request=True),
                )
        except httpx.HTTPError as exc:
            raise PixVerseError(f"Could not check the PixVerse video: {exc}") from exc
        return self._unwrap(response)

    async def upload_image(
        self,
        *,
        image_url: str = "",
        image_bytes: bytes | None = None,
        filename: str = "thumbnail.png",
        content_type: str = "image/png",
    ) -> int:
        files: dict[str, tuple[Any, ...]]
        if image_bytes is not None:
            files = {"image": (filename, image_bytes, content_type)}
        else:
            files = {"image_url": (None, image_url)}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{PIXVERSE_BASE_URL}/image/upload",
                    headers=self._headers(unique_request=True),
                    files=files,
                )
        except httpx.HTTPError as exc:
            raise PixVerseError(f"Could not upload the thumbnail to PixVerse: {exc}") from exc
        result = self._unwrap(response)
        image_id = result.get("img_id")
        if image_id is None:
            raise PixVerseError("PixVerse did not return an image id after uploading the thumbnail.")
        return int(image_id)

    async def generate_from_image(
        self,
        image_id: int,
        prompt: str,
        *,
        duration: int = 5,
        quality: str = "720p",
        model: str = "v6",
    ) -> int:
        payload = {
            "duration": duration,
            "img_id": image_id,
            "model": model,
            "motion_mode": "normal",
            "prompt": prompt,
            "quality": quality,
            "seed": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{PIXVERSE_BASE_URL}/video/img/generate",
                    headers=self._headers(unique_request=True),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise PixVerseError(f"Could not start PixVerse image-to-video generation: {exc}") from exc
        result = self._unwrap(response)
        video_id = result.get("video_id")
        if video_id is None:
            raise PixVerseError("PixVerse did not return a video id.")
        return int(video_id)
