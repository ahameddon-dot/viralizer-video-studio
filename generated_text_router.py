from __future__ import annotations

import copy
import re
from typing import Any


SOURCE_UI_TEXT = "SOURCE_UI_TEXT"
CONTROLLED_OVERLAY_TEXT = "CONTROLLED_OVERLAY_TEXT"


def _clean(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _verified_source_text(source_media: list[dict[str, Any]]) -> str:
    return " ".join(
        _clean(item.get("description"), 1200)
        for item in source_media
        if isinstance(item, dict) and item.get("context_verified") and item.get("url")
    ).lower()


def _candidates(text: str) -> list[str]:
    found = re.findall(r"[\"'“”]([^\"'“”]{2,80})[\"'“”]", text)
    found += re.findall(r"\b(?:19|20)\d{2}\b", text)
    found += re.findall(r"\b\d+(?:\.\d+)?%\b", text)
    trigger = re.compile(r"\b(?:headline|timeline|date|label|annotation|caption|statistic|number|readable text|interface text|screen text)\b", re.I)
    if trigger.search(text):
        for clause in re.split(r"[.;]", text):
            if trigger.search(clause):
                found.append(_clean(clause, 160))
    if re.search(r"\b(?:interface|screen|display|app|icon|label|dashboard|infotainment)\b", text, re.I):
        found += re.findall(r"\b[A-Z][A-Za-z0-9+.-]+(?:\s+[A-Z][A-Za-z0-9+.-]+){1,2}\b", text)
    if re.search(r"\b(?:logo|brand mark|badge|interface|screen|display|app|infotainment)\b", text, re.I):
        found += re.findall(r"\b[A-Z][A-Z0-9]{1,7}\b", text)
    return list(dict.fromkeys(_clean(item, 160) for item in found if _clean(item)))


def _remove_generated_text_request(text: str, candidates: list[str]) -> str:
    revised = text
    for value in sorted(candidates, key=len, reverse=True):
        replacement = (
            "a reserved timeline overlay position"
            if re.fullmatch(r"(?:19|20)\d{2}|\d+(?:\.\d+)?%", value)
            else "a supported product or interface region with a reserved deterministic label area"
        )
        revised = re.sub(rf"[\"'“”]?{re.escape(value)}[\"'“”]?", replacement, revised, flags=re.I)
    revised = re.sub(r"\b(?:readable|prominent|visible)\s+(?:headline|timeline label|date|label|annotation|caption|statistic|number|interface text|screen text)\b", "clean overlay-safe negative space", revised, flags=re.I)
    revised = re.sub(r"\b(?:dynamically\s+)?morphs?\b", "transitions cleanly", revised, flags=re.I)
    revised = re.sub(r"(?:a supported product or interface region with a reserved deterministic label area\s+(?:or|and)\s+){1,3}a supported product or interface region with a reserved deterministic label area", "two supported interface regions with reserved deterministic label areas", revised, flags=re.I)
    revised = re.sub(r"(?:a reserved timeline overlay position\s+){2,}", "a reserved timeline overlay position ", revised, flags=re.I)
    revised = re.sub(r"\s+([,.;:])", r"\1", revised)
    revised = re.sub(r"\s{2,}", " ", revised).strip(" ,;:-")
    return revised


def route_generated_text(storyboard: list[dict[str, Any]], source_media: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Keep character generation out of image/video models unless verified source UI supplies it."""
    source_media = source_media or []
    verified = _verified_source_text(source_media)
    shots = copy.deepcopy(storyboard)
    routes: list[dict[str, Any]] = []
    for shot in shots:
        shot_id = str(shot.get("shot_id") or "")
        shot_candidates: list[str] = []
        for field in ("visual_description", "action", "environment", "composition", "foreground", "background"):
            shot_candidates.extend(_candidates(str(shot.get(field) or "")))
        shot_candidates = list(dict.fromkeys(shot_candidates))
        for value in shot_candidates:
            source_ui = bool(value.lower() in verified)
            route = SOURCE_UI_TEXT if source_ui else CONTROLLED_OVERLAY_TEXT
            routes.append({
                "shot_id": shot_id,
                "text": value,
                "route": route,
                "source_media_verified": source_ui,
                "rendering": "preserve exact pixels from the verified reference" if source_ui else "deterministic compositor after video generation",
            })
        overlay_values = [item["text"] for item in routes if item["shot_id"] == shot_id and item["route"] == CONTROLLED_OVERLAY_TEXT]
        if overlay_values:
            for field in ("visual_description", "action", "environment", "composition", "foreground", "background"):
                shot[field] = _remove_generated_text_request(str(shot.get(field) or ""), overlay_values)
            shot["controlled_overlay_safe_region"] = "Reserve a clean, stable region with low visual activity for deterministic text compositing."
            shot["controlled_overlay_text"] = overlay_values
            shot["must_avoid"] = list(dict.fromkeys((shot.get("must_avoid") or []) + ["AI-generated letters, words, dates, numbers, captions, or logos"]))
    return {
        "storyboard": shots,
        "routes": routes,
        "source_ui_text": [item for item in routes if item["route"] == SOURCE_UI_TEXT],
        "controlled_overlay_text": [item for item in routes if item["route"] == CONTROLLED_OVERLAY_TEXT],
        "status": "PASS",
    }
