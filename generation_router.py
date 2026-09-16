from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GenerationRoute:
    mode: str
    confidence: float
    reason: str
    scores: dict[str, int]

    def public(self) -> dict[str, Any]:
        return asdict(self)


def choose_generation_route(content: dict[str, Any], *, reference_available: bool = False, production_style: str = "premium") -> GenerationRoute:
    text = " ".join(str(content.get(key) or "") for key in ("topic", "category", "entity_type_label", "brand", "company", "product", "video_idea")).lower()
    identity = 90 if any(word in text for word in ("person", "celebrity", "athlete", "player", "wrestler", "wrestling", "founder")) else 25
    brand = 92 if any(content.get(key) for key in ("brand", "company", "product")) else 65 if any(word in text for word in ("iphone", "sony", "playstation", "nvidia", "liverpool")) else 20
    product = 90 if any(word in text for word in ("iphone", "phone", "product", "console", "camera", "car", "device")) else 25
    composition = 82 if production_style in {"premium", "epic"} else 55
    complexity = 78 if any(word in text for word in ("crowd", "stadium", "city", "factory", "multiple", "team")) else 45
    continuity = 85 if any(word in text for word in ("same", "series", "story", "person", "product")) else 45
    scores = {"identity_importance": identity, "brand_importance": brand, "product_accuracy": product, "composition_importance": composition, "scene_complexity": complexity, "continuity_importance": continuity, "reference_availability": 100 if reference_available else 0}
    need_reference = max(identity, brand, product, continuity) >= 80 and (reference_available or production_style in {"premium", "epic"})
    if need_reference:
        return GenerationRoute("image_to_video", .91, "Specific subject or product consistency benefits from a generated or supplied reference.", scores)
    confidence = .86 if not reference_available else .76
    reason = "No suitable reference is available; use tightly directed text-to-video." if not reference_available else "The shot is generic enough for text-to-video."
    return GenerationRoute("text_to_video", confidence, reason, scores)