import os
import re
import uuid
from typing import Any

import httpx

from motion_director import build_motion_directed_prompt


PIXVERSE_BASE_URL = "https://app-api.pixverse.ai/openapi/v2"


class PixVerseError(RuntimeError):
    pass


def _clean_content(value: Any, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" .:-")
    text = re.sub(r"\b(?:Categories?|Viral Topic Rank|Total Audience|Estimated Remaining Views)\s*:[^.!?]*", "", text, flags=re.I)
    return " ".join(text.split()[:limit]).strip(" ,;:-")


def _visual_treatment(content: dict[str, Any]) -> tuple[str, str, str, str]:
    text = " ".join(str(content.get(key) or "") for key in ("topic", "category", "entity_type_label", "video_idea", "why_it_matters")).lower()
    if any(word in text for word in ("match", "football", "soccer", "liverpool", "league", "tournament", "sport")):
        return ("cinematic sports documentary", "a focused football player in a modern stadium tunnel leading toward the pitch", "the player tightens his boots, rises, and walks decisively toward the floodlit field as teammates move naturally behind him", "cool tunnel light transitioning into powerful white stadium floodlights with soft haze")
    if any(word in text for word in ("iphone", "smartphone photography", "mobile photography", "camera tips", "photography")):
        return ("premium mobile-photography commercial", "a skilled photographer holding an unbranded triple-lens smartphone with its rear cameras facing the viewer and its screen turned away", "the photographer changes position, steadies the phone with both hands, and frames a real subject while the phone screen remains completely hidden", "warm golden-hour side light with soft reflections across the camera lenses and natural city bokeh")
    if any(word in text for word in ("game", "gaming", "playstation", "xbox", "console")):
        return ("premium gaming-culture documentary", "a passionate gamer in a premium modern gaming room with a console and physical game cases", "the gamer places a game case beside the console, grips the controller, and leans toward the screen while fingers move naturally", "cool television light across the face with warm amber practical lights behind")
    if any(word in text for word in ("ai", "software", "technology", "device", "platform", "chip")):
        return ("factual technical editorial", "the exact system, process, interface, product, or infrastructure explicitly supported by the supplied content", "the supported technical state changes through one observable article-specific process without invented devices or unnecessary people", "stable realistic light appropriate to the supported environment")
    if any(word in text for word in ("fashion", "silk", "beauty", "luxury", "style")):
        return ("luxury fashion editorial", "a poised model wearing the featured material in an elegant minimal interior", "the model turns slowly as fabric folds and edges move naturally with the motion", "large diffused key light with a warm rim light revealing texture")
    if any(word in text for word in ("business", "company", "market", "finance", "brand")):
        return ("factual business-change editorial", "the exact operational relationship, product, market state, or infrastructure change supported by the supplied content", "the supported before-state visibly progresses into the reported business result without a generic meeting scene", "stable realistic light appropriate to the supported environment")
    return ("cinematic editorial documentary", "the main subject in a specific real-world environment connected to the story", "the subject performs one clear physical action that reveals the central change while background activity continues naturally", "directional natural light with practical sources creating depth and separation")


def _legacy_build_video_prompt(content: dict[str, Any], duration: int = 5) -> str:
    """Compile research into duration-aware, filmable PixVerse direction."""
    duration = max(5, min(60, int(duration or 5)))
    topic = _clean_content(content.get("topic") or content.get("suggested_title") or content.get("hook"), 18)
    style, subject, action, lighting = _visual_treatment(content)
    mood = "urgent and competitive" if any(word in topic.lower() for word in ("match", "race", "battle", "launch")) else "confident, immersive, and emotionally engaging"
    if duration > 15:
        beat_count = {20: 4, 30: 5, 45: 7, 60: 9}.get(duration, max(4, round(duration / 7)))
        purposes = ("visual hook", "story context", "main development", "important detail", "human impact", "wider consequence", "future implication", "emotional resolution", "strong closing image")
        beat_actions = (
            f"Establish {subject} with one immediate physical action that creates curiosity",
            f"Reveal the wider environment while {action}",
            "Show a second observable action that makes the central development visually clear",
            "Move closer to one meaningful physical detail while surrounding activity continues naturally",
            "Show a believable human reaction through posture, movement, and interaction rather than text",
            "Widen the scene to reveal how the development affects the surrounding people or environment",
            "Suggest the next consequence through a motivated change in action, activity, or atmosphere",
            "Let the main subject pause within the changed environment for an emotional beat",
            "End on one memorable physical image with clean composition and natural continuing motion",
        )
        scene_length = duration / beat_count
        scenes = []
        for index in range(beat_count):
            camera = "slow controlled push-in" if index % 3 == 0 else "gentle lateral tracking" if index % 3 == 1 else "locked camera with purposeful subject motion"
            scenes.append(
                f"Scene {index + 1} - about {scene_length:.1f} seconds, {purposes[index]}: {beat_actions[index]}. "
                f"Camera: {camera}. Lighting: {lighting}. Include restrained secondary and environmental motion."
            )
        continuity = f"Continuity: maintain the same subject identity, clothing, environment design, time of day, {lighting}, and {style} color language across connected scenes."
        restrictions = "Do not generate readable text, numbers, statistics, rankings, captions, subtitles, charts, dashboards, interfaces, watermarks, or logos."
        return f"Create a {duration}-second vertical {style} visual narrative about {topic}. {continuity}\n\n" + "\n\n".join(scenes) + f"\n\n{restrictions}"
    if duration <= 5:
        return (
            f"Create one uninterrupted {duration}-second vertical {style} moment about {topic}. "
            f"Show {subject}. {action.capitalize()}. Use one slow controlled push-in as the dominant camera movement. "
            "Include subtle breathing, realistic fabric movement, shifting reflections, and restrained background activity. "
            f"Lighting: {lighting}. The mood is {mood}. Keep anatomy, clothing, objects, environment, and subject identity stable throughout. "
            "No cuts, transformations, readable text, numbers, charts, interfaces, captions, watermarks, or generated logos."
        )
    if duration <= 10:
        return (
            f"Create a continuous {duration}-second vertical {style} sequence about {topic}. Begin close on {subject}, then reveal the wider environment without a hard cut. "
            f"First, {action}. Then let the subject respond with a second small, believable action that shows growing momentum. "
            "Use a slow lateral track that settles into a gentle push-in; do not combine additional camera moves. Add natural body movement, restrained background motion, and changing reflections. "
            f"Lighting: {lighting}. Maintain the same subject, clothing, location, color language, and light direction. No readable text, numbers, charts, captions, watermarks, or logos."
        )
    return (
        f"Create a coherent {duration}-second vertical {style} story about {topic} in three connected visual beats. "
        f"Open with {subject} already in motion. Core development: {action}. Conclude on a strong physical consequence in the same world, showing the subject pause and take in the changed environment. "
        "Use motivated cuts only between the three beats, with one dominant slow push-in or tracking move per beat. Include realistic body mechanics, subtle environmental movement, and stable object placement. "
        f"Lighting: {lighting}. Preserve subject identity, wardrobe, location details, and color palette across every beat. No readable text, numbers, rankings, charts, dashboards, captions, watermarks, or generated logos."
    )


def build_video_prompt(
    content: dict[str, Any],
    duration: int = 5,
    *,
    generation_type: str = "text_to_video",
    quality_mode: bool = True,
    user_prompt: str = "",
    include_debug: bool = False,
    aspect_ratio: str = "9:16",
) -> str | tuple[str, dict[str, Any]]:
    """Build the editable PixVerse prompt through the shared Motion Director."""
    prompt, debug = build_motion_directed_prompt(
        content,
        duration,
        generation_type=generation_type,
        quality_mode=quality_mode,
        user_prompt=user_prompt,
    )
    aspect_labels = {
        "9:16": "vertical 9:16",
        "16:9": "landscape 16:9",
        "3:4": "portrait 3:4",
        "1:1": "square 1:1",
    }
    selected_aspect = aspect_labels.get(aspect_ratio, aspect_labels["9:16"])
    prompt = re.sub(r"\bvertical\s+9:16\b", selected_aspect, prompt, count=1, flags=re.I)
    return (prompt, debug) if include_debug else prompt
def build_narration_script(content: dict[str, Any], duration: int = 5) -> str:
    """Write a spoken social-video hook instead of copying raw research fields."""
    duration = max(5, min(60, int(duration or 5)))
    topic = _clean_content(content.get("topic") or content.get("suggested_title"), 14)
    hook = _clean_content(content.get("hook") or content.get("suggested_title"), 28)
    idea = _clean_content(content.get("creator_angle") or content.get("video_idea"), 45)
    why = _clean_content(content.get("why_it_matters"), 45)
    category_text = " ".join(str(content.get(key) or "") for key in ("topic", "category", "entity_type_label")).lower()
    subject = _clean_content(str(content.get("topic") or topic).split(":", 1)[0], 5)
    if any(word in category_text for word in ("match", "football", "soccer", "liverpool", "league", "sport")):
        known_clubs = ("Liverpool", "Manchester United", "Manchester City", "Arsenal", "Chelsea", "Real Madrid", "Barcelona", "Bayern Munich", "Paris Saint-Germain", "Juventus", "Inter Miami")
        subject = next((club for club in known_clubs if club.casefold() in category_text), subject.title())
        possessive = f"{subject}'" if subject.lower().endswith("s") else f"{subject}'s"
        short = f"{possessive} tactical edge: sharp movement, relentless pressure, and match-defining moments."
        if duration <= 5:
            return short
        development = idea or why
        text = " ".join(value for value in (short, development, why, _clean_content(content.get("cta"), 24)) if value)
    elif any(word in category_text for word in ("iphone", "smartphone photography", "mobile photography", "camera tips", "photography")):
        opening = "Your best camera may already be in your hand."
        technique = "Step into clean natural light, lock your focus, and steady the phone before you press the shutter."
        payoff = "Then simplify the frame, shift your angle, and let one clear subject tell the story."
        close = "Small changes in light, composition, and timing can turn an everyday iPhone shot into an image people stop to see."
        if duration <= 5:
            text = "Better iPhone photos start with light, focus, and one steady frame."
        elif duration <= 10:
            text = f"{opening} Find clean light, steady your frame, and make one subject impossible to miss."
        elif duration <= 20:
            text = f"{opening} {technique} {payoff}"
        else:
            text = f"{opening} {technique} {payoff} {close}"
    elif any(word in category_text for word in ("game", "gaming", "playstation", "xbox")):
        text = " ".join(value for value in (f"{subject} is changing the game. Look closer at the move players will be talking about next.", idea, why, _clean_content(content.get("cta"), 24)) if value)
    elif any(word in category_text for word in ("ai", "technology", "software", "platform", "device")):
        text = " ".join(value for value in (f"{subject} is shifting the conversation. Here is the move that could change what happens next.", idea, why, _clean_content(content.get("cta"), 24)) if value)
    else:
        text = " ".join(value for value in (hook or topic, idea, why, _clean_content(content.get("cta"), 24)) if value).strip()
    text = re.sub(r"\b(?:Introduction|Conclusion|Call to action)\b\s*\d*\.?", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .")
    max_words = max(11, round(duration * 2.25))
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip(" ,;:-")
    if text and text[-1] not in ".!?":
        text += "."
    return text

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
        self.api_key = (
            api_key
            or os.getenv("PIXVERSE_API_KEY_RUNTIME", "")
            or os.getenv("PIXVERSE_API_KEY", "")
        ).strip()
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

    async def balance(self) -> dict[str, Any]:
        """Validate authentication without starting a billable generation."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{PIXVERSE_BASE_URL}/account/balance",
                    headers=self._headers(unique_request=True),
                )
        except httpx.HTTPError as exc:
            raise PixVerseError(f"Could not connect to PixVerse: {exc}") from exc
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
        negative_prompt: str = "",
        motion_mode: str = "normal",
        seed: int = 0,
    ) -> int:
        payload = {
            "duration": duration,
            "img_id": image_id,
            "model": model,
            "motion_mode": motion_mode,
            "prompt": prompt,
            "quality": quality,
            "seed": seed,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
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

    async def generate_fusion(
        self,
        image_references: list[dict[str, Any]],
        prompt: str,
        *,
        aspect_ratio: str = "9:16",
        duration: int = 8,
        quality: str = "720p",
        model: str = "v6",
        seed: int = 0,
    ) -> int:
        if not image_references:
            raise PixVerseError("PixVerse Fusion requires at least one image reference.")
        payload = {
            "image_references": image_references,
            "prompt": prompt,
            "model": model,
            "duration": duration,
            "quality": quality,
            "aspect_ratio": aspect_ratio,
            "seed": seed,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{PIXVERSE_BASE_URL}/video/fusion/generate",
                    headers={**self._headers(unique_request=True), "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise PixVerseError(f"Could not start PixVerse Fusion generation: {exc}") from exc
        result = self._unwrap(response)
        video_id = result.get("video_id")
        if video_id is None:
            raise PixVerseError("PixVerse Fusion did not return a video id.")
        return int(video_id)
