from __future__ import annotations

import re
from typing import Any


RAW_ARTICLE_SPECIFICITY_THRESHOLD = 65


def _clean(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _tokens(value: Any) -> set[str]:
    stop = {"this", "that", "with", "from", "into", "before", "after", "public", "display", "shown"}
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9'-]+", str(value or ""))
        if len(token) > 3 and token.lower() not in stop
    }


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in (_clean(value) for value in values) if item))


def analyze_visual_specificity(
    story: dict[str, Any],
    visualizability: dict[str, Any],
    source_visual_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    visual = _unique([
        str(item)
        for item in visualizability.get("visualizable_facts") or []
        if not re.match(r"^\s*(?:read|see|watch|related|also)\b", str(item), re.I)
    ])
    narration = _unique([str(item) for item in visualizability.get("narration_dependent_meanings") or []])
    source_visual_evidence = source_visual_evidence or story.get("source_visual_evidence") or []

    story_text = " ".join(
        _clean(story.get(key), 2400)
        for key in ("what_happened", "new_development", "core_message", "viewer_takeaway")
    )
    proper_names = _unique([
        item.removesuffix("'s").removesuffix("’s")
        for item in re.findall(r"\b(?:Princess|Prince|King|Queen|President|Dr\.?|Sir)\s+[A-Z][A-Za-z'’-]+", story_text)
    ])
    named_entities = _unique([
        item.removesuffix("'s").removesuffix("’s")
        for item in re.findall(r"\b[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,3}\b", story_text)
    ])
    nonvisual = _unique([*proper_names, *named_entities, *narration])

    media_anchors: list[str] = []
    verified_media = False
    for item in source_visual_evidence:
        if not isinstance(item, dict):
            continue
        description = _clean(item.get("description") or item.get("caption") or item.get("alt"), 800)
        url = _clean(item.get("url"), 1800)
        if description or url:
            media_anchors.append(description or "Legitimate publisher-provided source image")
        if item.get("context_verified") and (description or url):
            verified_media = True
    media_anchors = _unique(media_anchors)

    visual_text = " ".join(visual).lower()
    distinctive_terms = re.findall(
        r"\b(?:black|white|red|blue|green|gold|silver|strapless|silk|leather|prototype|distinctive|"
        r"curved|angular|folding|transparent|landmark|tower|bridge|specific|model|interface)\b",
        visual_text,
    )
    location_anchor = bool(re.search(r"\b(?:eiffel tower|burj khalifa|times square|specific location|landmark)\b", visual_text))
    if verified_media and len(visual) >= 2:
        maximum = 90 if location_anchor or len(distinctive_terms) >= 2 else 80
    elif media_anchors:
        maximum = 70 if len(distinctive_terms) >= 2 else 60
    elif len(distinctive_terms) >= 3 and len(visual) >= 2:
        maximum = 50
    elif len(distinctive_terms) >= 1 or len(visual) >= 2:
        maximum = 45
    else:
        maximum = 35
    if location_anchor:
        maximum = max(maximum, 75)
    maximum = max(20, min(95, maximum))

    identity_narration_required = bool(nonvisual) and maximum < RAW_ARTICLE_SPECIFICITY_THRESHOLD
    if verified_media:
        limiter = "Specificity is bounded by the verified source image and the supported visible characteristics."
    elif nonvisual and maximum < RAW_ARTICLE_SPECIFICITY_THRESHOLD:
        limiter = "The story's unique identity depends on names, history, context, or interpretation that generated visuals cannot safely establish without narration, text, or legitimate source imagery."
    else:
        limiter = "Specificity is bounded by the available supported physical and environmental evidence."

    # Keep identity allocation generic: production behavior must be derived from
    # named evidence, never from an article- or fixture-specific phrase.
    identity_details = proper_names[:]
    abstract = [item for item in narration if re.search(r"\b(?:empowerment|resilience|meaning|legacy|significance|reputation|interpretation)\b", item, re.I)]
    factual = [item for item in narration if item not in abstract]
    return {
        "visual_identity_anchors": visual,
        "nonvisual_identity_anchors": nonvisual,
        "source_media_identity_anchors": media_anchors,
        "maximum_visual_specificity": maximum,
        "specificity_limiter": limiter,
        "identity_narration_required": identity_narration_required,
        "identity_details_for_narration": _unique(identity_details),
        "abstract_meanings_for_narration": abstract,
        "factual_details_for_narration": factual,
        "raw_specificity_threshold_preserved": RAW_ARTICLE_SPECIFICITY_THRESHOLD,
    }


def evaluate_evidence_relative_specificity(
    storyboard: list[dict[str, Any]],
    specificity: dict[str, Any],
    raw_score: int,
    *,
    primary_visual_story_pass: bool,
    generic_ad_risk: int,
) -> dict[str, Any]:
    rendered = " ".join(
        str(shot.get(key) or "")
        for shot in storyboard
        if isinstance(shot, dict)
        for key in ("visual_subject", "visual_description", "action", "environment", "composition", "foreground", "background")
    ).lower()
    rendered_tokens = _tokens(rendered)
    anchors = [
        str(item)
        for item in specificity.get("visual_identity_anchors") or []
        if not re.match(r"^\s*(?:read|see|watch|related|also)\b", str(item), re.I)
    ]
    used: list[str] = []
    missed: list[str] = []
    for anchor in anchors:
        anchor_tokens = _tokens(anchor)
        meaningful = anchor_tokens & rendered_tokens
        required = 1 if len(anchor_tokens) <= 2 else 2
        (used if len(meaningful) >= required else missed).append(anchor)
    fully_used = bool(anchors) and not missed
    ceiling = int(specificity.get("maximum_visual_specificity") or 0)
    identity_narration_required = bool(specificity.get("identity_narration_required"))

    if generic_ad_risk > 40 or not primary_visual_story_pass:
        classification = "GENERIC_STORYBOARD"
        relative = 30 if fully_used else 10
        passed = False
    elif missed:
        classification = "MISSED_VISUAL_SPECIFICITY"
        relative = 40 if used else 10
        passed = False
    elif raw_score >= RAW_ARTICLE_SPECIFICITY_THRESHOLD:
        classification = "FULL_VISUAL_SPECIFICITY"
        relative = 100
        passed = True
    elif ceiling < RAW_ARTICLE_SPECIFICITY_THRESHOLD and fully_used and identity_narration_required:
        classification = "EVIDENCE_LIMITED_SPECIFICITY"
        relative = 100
        passed = True
    else:
        classification = "MISSED_VISUAL_SPECIFICITY"
        relative = 60
        passed = False
    return {
        "article_specificity_raw": max(0, min(100, int(raw_score))),
        "article_specificity_relative_to_available_evidence": relative,
        "specificity_classification": classification,
        "visual_identity_anchors_used": used,
        "visual_identity_anchors_missed": missed,
        "available_visual_anchors_fully_used": fully_used,
        "identity_narration_required": identity_narration_required,
        "specificity_gate_pass": passed,
        "decision": (
            "VISUAL_STORY_APPROVED / IDENTITY_REQUIRES_NARRATION"
            if passed and classification == "EVIDENCE_LIMITED_SPECIFICITY"
            else "VISUAL_STORY_APPROVED"
            if passed
            else "VISUAL_STORY_REQUIRES_REVISION"
        ),
        "raw_specificity_threshold_preserved": RAW_ARTICLE_SPECIFICITY_THRESHOLD,
    }
