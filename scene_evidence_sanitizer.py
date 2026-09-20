from __future__ import annotations

import copy
import re
from typing import Any

from scene_evidence import build_scene_evidence_preflight


TEXT_FIELDS = ("visual_description", "environment", "composition", "foreground", "background")
LIST_FIELDS = ("important_objects", "must_show")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _replacement_for(element: str) -> str:
    value = element.lower()
    if any(term in value for term in ("plaque", "signage", "label", "document", "velvet rope", "barrier")):
        return ""
    if any(term in value for term in ("mannequin", "display stand", "display stands", "artifact", "garment", "object")):
        return "empty negative space"
    if any(term in value for term in ("doorway", "window", "daylight", "exterior")):
        return "plain wall"
    if "ceiling" in value:
        return "ceiling"
    if any(term in value for term in ("lighting fixture", "institutional lighting")):
        return "ambient gallery lighting"
    if value.strip(" .") in {"empty", "spacious", "empty and spacious"}:
        return "empty negative space"
    return "neutral background"


def _replace(text: Any, element: str, replacement: str) -> str:
    source = str(text or "")
    if not source:
        return source
    updated = re.sub(re.escape(element), replacement, source, flags=re.I)
    updated = re.sub(r"\s+([,.;:])", r"\1", updated)
    updated = re.sub(r"(?:,\s*){2,}", ", ", updated)
    updated = re.sub(r"\s{2,}", " ", updated)
    updated = re.sub(r"^\s*[,;]\s*|\s*[,;]\s*$", "", updated)
    return updated.strip()


def _meaning_signature(shot: dict[str, Any]) -> dict[str, str]:
    return {
        "purpose": _clean(shot.get("purpose")).upper(),
        "meaning_added": _clean(shot.get("after_viewer_understands")),
        "visual_subject": _clean(shot.get("visual_subject")),
        "action_prefix": _clean(shot.get("action")).split(":", 1)[0].upper(),
    }


def _action_survives(action: str, unsupported: list[str]) -> bool:
    if not action:
        return True
    revised = action
    for element in unsupported:
        revised = _replace(revised, element, "")
    body = revised.split(":", 1)[-1].strip(" .,:;-")
    return len(body) >= 12


def sanitize_storyboard(
    story: dict[str, Any],
    visual_plan: dict[str, Any],
    package: dict[str, Any],
) -> dict[str, Any]:
    """Remove non-essential unsupported scene detail without redesigning shots."""
    original_shots = package.get("storyboard") if isinstance(package.get("storyboard"), list) else []
    original_preflight = build_scene_evidence_preflight(story, visual_plan, original_shots)
    sanitized_shots = copy.deepcopy(original_shots)
    audit: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    per_shot = {str(item.get("shot_id")): item for item in original_preflight.get("per_shot") or []}
    for shot in sanitized_shots:
        shot_id = str(shot.get("shot_id") or "")
        original = copy.deepcopy(shot)
        signature_before = _meaning_signature(original)
        evidence = per_shot.get(shot_id) or {}
        unsupported = [
            item.get("element", "")
            for item in evidence.get("elements") or []
            if item.get("classification") in {"MEANING_BEARING_REQUIRES_EVIDENCE", "REJECTED"}
            and not item.get("evidence_lock")
            and _clean(item.get("element"))
        ]
        if not _action_survives(_clean(shot.get("action")), unsupported):
            blocked.append({
                "shot_id": shot_id,
                "reason": "Removing unsupported evidence would destroy the shot's approved action or meaning.",
                "unsupported_elements": unsupported,
            })
            audit.append({
                "shot_id": shot_id,
                "original_shot": original,
                "removed_elements": [],
                "replacement_elements": [],
                "sanitized_shot": original,
                "meaning_preserved": False,
            })
            continue

        removed: list[str] = []
        replacements: list[dict[str, str]] = []
        for element in unsupported:
            replacement = _replacement_for(element)
            touched = False
            for field in TEXT_FIELDS:
                before = str(shot.get(field) or "")
                after = _replace(before, element, replacement)
                if after != before:
                    shot[field] = after
                    touched = True
            for field in LIST_FIELDS:
                values = shot.get(field)
                if not isinstance(values, list):
                    continue
                revised_values = []
                for value in values:
                    revised = _replace(value, element, replacement)
                    if revised != str(value):
                        touched = True
                    if _clean(revised):
                        revised_values.append(revised)
                shot[field] = list(dict.fromkeys(revised_values))
            if touched:
                removed.append(element)
                if replacement:
                    replacements.append({"removed": element, "replacement": replacement})

        signature_after = _meaning_signature(shot)
        meaning_preserved = (
            signature_after["purpose"] == signature_before["purpose"]
            and signature_after["meaning_added"] == signature_before["meaning_added"]
            and signature_after["visual_subject"] == signature_before["visual_subject"]
            and signature_after["action_prefix"] == signature_before["action_prefix"]
        )
        if not meaning_preserved:
            blocked.append({
                "shot_id": shot_id,
                "reason": "Shot purpose, meaning added, core subject, or camera/action intent changed.",
                "unsupported_elements": unsupported,
            })
        audit.append({
            "shot_id": shot_id,
            "original_shot": original,
            "removed_elements": removed,
            "replacement_elements": replacements,
            "sanitized_shot": copy.deepcopy(shot),
            "meaning_preserved": meaning_preserved,
        })

    if blocked:
        return {
            "status": "SANITIZATION_BLOCKED",
            "storyboard": original_shots,
            "shot_audit": audit,
            "blocked_reasons": blocked,
            "original_preflight": original_preflight,
            "sanitized_preflight": original_preflight,
            "creative_revision_consumed": False,
        }

    sanitized_preflight = build_scene_evidence_preflight(story, visual_plan, sanitized_shots)
    status = "PASS" if sanitized_preflight.get("scene_evidence_status") == "PASS" else "FAIL"
    return {
        "status": status,
        "storyboard": sanitized_shots,
        "shot_audit": audit,
        "blocked_reasons": [],
        "original_preflight": original_preflight,
        "sanitized_preflight": sanitized_preflight,
        "source_asserted_elements": sanitized_preflight.get("source_asserted_elements") or [],
        "source_evidence_locks": sanitized_preflight.get("source_evidence_locks") or [],
        "safe_contextual_completion": sanitized_preflight.get("safe_contextual_completion") or [],
        "removed_elements": list(dict.fromkeys(item for record in audit for item in record["removed_elements"])),
        "replacement_elements": [item for record in audit for item in record["replacement_elements"]],
        "meaning_preserved": all(record["meaning_preserved"] for record in audit),
        "scene_evidence_status": sanitized_preflight.get("scene_evidence_status"),
        "creative_revision_consumed": False,
    }


def only_scene_clutter_failed(validation: dict[str, Any]) -> bool:
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    failed = {name for name, passed in checks.items() if not passed}
    return bool(failed) and failed <= {"unsupported_assets_rejected", "scene_evidence_status"}


def sanitize_if_simple_clutter(
    story: dict[str, Any],
    visual_plan: dict[str, Any],
    package: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any] | None:
    if not only_scene_clutter_failed(validation):
        return None
    return sanitize_storyboard(story, visual_plan, package)
