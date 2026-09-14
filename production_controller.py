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


def prepare_production(content: dict[str, Any], duration: int, user_prompt: str, *, quality_mode: bool, reference_available: bool = False, aspect_ratio: str = "9:16", quality: str = "720p") -> dict[str, Any]:
    route = choose_generation_route(content, reference_available=reference_available)
    base = (user_prompt or build_video_prompt(content, duration)).strip()
    category = str(content.get("category") or content.get("entity_type_label") or "General")
    if quality_mode:
        prompt = (
            f"{base}\n\nProduction constraints: Create {shot_count(duration)} intentional visual beat(s) at most. "
            "Include one clean hero composition suitable for a social preview and keep useful negative space for later graphics. "
            "Use one controlled camera move per beat, physically believable motion, stable subject identity and stable object geometry. "
            "Do not render important text, numbers, interfaces, captions, or logos inside the footage; Viralizer adds exact graphics afterward."
        )
        style = "premium"
    else:
        prompt, style = base, "fast"
    return {
        "quality_mode": quality_mode,
        "generation_mode": route.mode if quality_mode else "text_to_video",
        "production_style": style,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "category": category,
        "creative_direction": "hero-led, concrete visual storytelling" if quality_mode else "basic creative direction",
        "shot_count": shot_count(duration) if quality_mode else (1 if duration <= 15 else 0),
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