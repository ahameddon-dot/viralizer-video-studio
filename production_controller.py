from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from generation_router import choose_generation_route
from pixverse_client import build_video_prompt

QUALITY_NEGATIVE = (
    "readable text, letters, words, numbers, captions, subtitles, headlines, title cards, labels, signs, "
    "posters, phone UI, app interface, fake logos, watermarks, pseudo-text, malformed glyphs, morphing, "
    "warped objects, duplicate objects, unstable anatomy, extra fingers, abrupt camera motion, flicker"
)


def shot_count(duration: int) -> int:
    if duration <= 5: return 1
    if duration <= 10: return 2
    if duration <= 15: return 3
    if duration <= 20: return 4
    if duration <= 30: return 6
    if duration <= 45: return 6
    return 8


def prepare_production(content: dict[str, Any], duration: int, user_prompt: str, *, quality_mode: bool, reference_available: bool = False, aspect_ratio: str = "9:16", quality: str = "720p", generation_type: str = "text_to_video") -> dict[str, Any]:
    route = choose_generation_route(content, reference_available=reference_available)
    # The reviewed text is the final PixVerse prompt. When absent, compile it once
    # through Motion Director; do not silently add a second prompt template later.
    base = (user_prompt or build_video_prompt(content, duration, generation_type=generation_type, quality_mode=quality_mode)).strip()
    category = str(content.get("category") or content.get("entity_type_label") or "General")
    prompt = base
    style = "premium" if quality_mode else "fast"
    return {
        "quality_mode": quality_mode,
        "generation_mode": route.mode if quality_mode else "text_to_video",
        "production_style": style,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "category": category,
        "creative_direction": "hero-led, concrete visual storytelling" if quality_mode else "basic creative direction",
        "shot_count": (len(content.get("storyboard") or []) or shot_count(duration)) if quality_mode else (1 if duration <= 15 else 0),
        "prompt": prompt,
        "motion_prompt": "Preserve identity, geometry, environment, lighting and composition. Use restrained subject, camera and background motion." if route.mode == "image_to_video" else "",
        "reference_image": None,
        "qc_score": None,
        "qc_status": "pending" if quality_mode else "not_requested",
        "retry_count": 0,
        "pixverse_model": "v6",
        "route": route.public(),
        "negative_prompt": QUALITY_NEGATIVE,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def record_production(record: dict[str, Any], data_dir: Path) -> None:
    folder = data_dir / "production"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "video-generations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
