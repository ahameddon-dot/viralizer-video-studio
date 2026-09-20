from __future__ import annotations

import re
from typing import Any


SOURCE_ASSERTED = "SOURCE_ASSERTED"
SAFE_CONTEXTUAL_COMPLETION = "SAFE_CONTEXTUAL_COMPLETION"
MEANING_BEARING_REQUIRES_EVIDENCE = "MEANING_BEARING_REQUIRES_EVIDENCE"
REJECTED = "REJECTED"
SYMBOLIC_EDITORIAL_ELEMENT = "SYMBOLIC_EDITORIAL_ELEMENT"

TEMPORAL_STATUSES = {"PAST_CONFIRMED", "CURRENT_CONFIRMED", "PLANNED_FUTURE", "PROPOSED", "EXPECTED", "UNKNOWN"}


def _clean(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def collect_source_visual_evidence(article: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for item in article.get("source_visual_evidence") or []:
        if isinstance(item, dict) and (item.get("url") or item.get("description")):
            evidence.append(dict(item))
    for caption in article.get("image_captions") or []:
        if _clean(caption):
            evidence.append({"type": "article_image_caption", "description": _clean(caption, 1000), "context_verified": False})
    data = article.get("json_ld") if isinstance(article.get("json_ld"), dict) else {}
    images = data.get("image") or data.get("thumbnailUrl") or []
    if not isinstance(images, list):
        images = [images]
    for image in images:
        url = image.get("url") if isinstance(image, dict) else image
        caption = image.get("caption") if isinstance(image, dict) else ""
        if _clean(url):
            evidence.append({"type": "publisher_metadata_image", "url": _clean(url, 2000), "description": _clean(caption, 1000), "context_verified": bool(caption)})
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        key = (_clean(item.get("url"), 2000), _clean(item.get("description"), 1000))
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique[:20]


def _source_text(story: dict[str, Any], visual_plan: dict[str, Any], source_media: list[dict[str, Any]]) -> str:
    values = [
        story.get("what_happened"),
        story.get("core_message"),
        story.get("viewer_takeaway"),
        visual_plan.get("core_visual_subject"),
        visual_plan.get("visual_message"),
    ]
    values += list(story.get("key_visual_facts") or []) + list(visual_plan.get("must_show") or [])
    values += [_clean(item.get("description"), 1000) for item in source_media]
    return " ".join(str(item) for item in values).lower()


def infer_temporal_status(value: str) -> str:
    text = _clean(value, 2000).lower()
    if re.search(r"\b(?:planned|upcoming|will|to be|future|next phase|scheduled|intends? to|aims? to)\b", text):
        return "PLANNED_FUTURE"
    if re.search(r"\b(?:proposed|proposal|could|would)\b", text):
        return "PROPOSED"
    if re.search(r"\b(?:expected|anticipated|forecast|projected)\b", text):
        return "EXPECTED"
    if re.search(r"\b(?:launched|completed|finished|deployed|built|achieved|was|were|previously|original)\b", text):
        return "PAST_CONFIRMED"
    if re.search(r"\b(?:current|currently|now|today|existing|remains?|stays?)\b", text):
        return "CURRENT_CONFIRMED"
    return "UNKNOWN"


def infer_semantic_role(value: str) -> str:
    text = _clean(value, 2000).lower()
    technical_object = bool(re.search(r"\b(?:satellite|device|vehicle|machine|prototype|module|unit|system|interface|product)\b", text))
    if technical_object and re.search(r"\b(?:original|first|earlier|previous|existing|1u)\b", text):
        return "ORIGINAL_SATELLITE"
    if technical_object and re.search(r"\b(?:new|next|planned|upcoming|3u|second)\b", text):
        return "NEW_SATELLITE"
    if re.search(r"\b(?:component|assembly|assemble|part|panel|circuit|frame)\b", text):
        return "ASSEMBLY_COMPONENT"
    if re.search(r"\bpayload\b", text):
        return "PAYLOAD"
    if re.search(r"\b(?:launch|rocket|orbit|deployment)\b", text):
        return "LAUNCH_CONTEXT"
    if re.search(r"\b(?:laboratory|lab|workbench|clean room|research room)\b", text):
        return "LAB_CONTEXT"
    if re.search(r"\b(?:collaboration|partner|university|team|joint)\b", text):
        return "COLLABORATION_ELEMENT"
    if re.search(r"\b(?:scale|size|dimension|larger|smaller|comparison)\b", text):
        return "SCALE_REFERENCE"
    return "UNSPECIFIED"


def build_source_evidence_locks(story: dict[str, Any], visual_plan: dict[str, Any]) -> list[dict[str, Any]]:
    values = list(story.get("key_visual_facts") or []) + list(visual_plan.get("must_show") or [])
    locks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        element = _clean(value, 1000)
        key = element.lower()
        if not element or key in seen:
            continue
        seen.add(key)
        locks.append({
            "element": element,
            "classification": SOURCE_ASSERTED,
            "evidence_lock": True,
            "semantic_role": infer_semantic_role(element),
            "temporal_status": infer_temporal_status(element),
        })
    return locks


def classify_scene_element(element: str, story: dict[str, Any], visual_plan: dict[str, Any], source_media: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    source_media = source_media or []
    raw = _clean(element, 1200)
    value = raw.lower()
    source = _source_text(story, visual_plan, source_media)
    source_tokens = {token for token in re.findall(r"[a-z0-9'-]{4,}", source)}
    element_tokens = {token for token in re.findall(r"[a-z0-9'-]{4,}", value)}
    overlap = source_tokens & element_tokens
    exact_support = bool(value and (value in source or any(part.strip() and part.strip() in value for part in re.split(r"[;,]", source) if len(part.strip()) >= 5)))
    semantic_support = exact_support or len(overlap) >= 2
    supported_overlap = semantic_support or (bool(re.match(r"^(?:physical_action|state_change|context_reveal|relational_reveal|environmental_recontextualization|process_progression|temporal_contrast|scale_reveal|cause_effect|object_state_transition):", value)) and bool(overlap))
    cardinality_pattern = r"\b(?:three|3|third|multiple|other|additional|some|empty|generic empty)\s+(?:mannequins?|artifacts?|garments?|displays?|display stands?|objects?|devices?|units?|modules?|vehicles?|machines?|satellites?)\b"
    asserted_value = re.sub(r"\b(?:without|no)\b[^.;]*", "", value)
    fabricated_patterns = (
        r"\b(?:someone|worker|staff|person)\b.*\b(?:removes?|pulls?|opens?|unveils?)\b",
        r"\b(?:cover|cloth|glass cover)\b.*\b(?:removed|lifted|raised|opens?)\b",
        r"\bempty (?:display|case|pedestal)\b.*\b(?:becomes|transforms?|reveals?)\b",
        r"\b(?:fake|fabricated|invented)\b", r"\breenactment\b",
    )
    meaning_patterns = (
        r"\b(?:crowds?|visitors?|photographers?|security|auction staff|workers?)\b",
        r"\b(?:velvet ropes?|barriers?|benches?|auction plinths?|transport(?:ation)? crates?|protective coverings?)\b",
        r"\b(?:signage|plaques?|labels?|documents?|newspapers?|catalogs?|paddles?)\b",
        r"\b(?:doorways?|windows?|daylight|exterior|display stands?)\b",
        r"\b(?:preparing|arriving|viewing|cordoned|auction readiness|before-state)\b",
        r"\b(?:historical stature|cultural significance|iconic status|symbolic importance|prestigious|revered|treasured artifact)\b",
        r"\b(?:multiple|other|additional|some|empty|generic empty)\s+(?:mannequins?|artifacts?|garments?|displays?|display stands?|objects?)\b",
    )
    strict_evidence_patterns = meaning_patterns[:4]
    symbolic_patterns = (r"\b(?:crown-shaped shadow|broken chains?|phoenix|shattering glass|storm clearing|heartbeat spotlight)\b",)
    neutral_patterns = (
        r"\b(?:neutral|plain|minimal|generic)\s+(?:walls?|floors?|surfaces?|background|architecture|space)\b",
        r"\b(?:walls?|floors?|ceiling|empty negative space|ambient gallery lighting|natural shadows?|architectural (?:surface|details)|mounting support|overhead lights?)\b",
        r"\b(?:restrained|neutral|minimal)\s+(?:gallery|exhibition)\s+(?:interior|environment|space)\b",
        r"\b(?:open and )?uncluttered (?:space|environment|background)\b",
        r"\b(?:reflection|subject|dress)\s+(?:foreground|background|central|centered|offset|behind)\b",
        r"\b(?:soft|natural) reflections?\b", r"\breflection edge\b", r"\brestrained gallery depth\b", r"\b(?:dimly lit|mostly shadowed)\b",
        r"^(?:bright|neutral|shadowed|softly lit|well-lit)$",
    )
    meaning_pattern_supported = any(
        re.search(pattern, asserted_value) and re.search(pattern, source)
        for pattern in meaning_patterns
    )
    unsupported_strict_evidence = any(
        re.search(pattern, asserted_value) and not re.search(pattern, source)
        for pattern in strict_evidence_patterns
    )
    if not value or value in {"none", "n/a", "not applicable"}:
        classification, reason = SAFE_CONTEXTUAL_COMPLETION, "No scene element is requested."
    elif any(re.search(pattern, value) for pattern in fabricated_patterns):
        classification, reason = REJECTED, "The element creates an unsupported event or before/after state."
    elif any(re.search(pattern, value) for pattern in symbolic_patterns):
        classification, reason = SYMBOLIC_EDITORIAL_ELEMENT, "The element is symbolic and requires separate symbolism-safety review."
    elif re.search(cardinality_pattern, asserted_value) and not re.search(cardinality_pattern, source):
        classification, reason = MEANING_BEARING_REQUIRES_EVIDENCE, "The scene increases the number of story objects beyond the source evidence."
    elif unsupported_strict_evidence:
        classification, reason = MEANING_BEARING_REQUIRES_EVIDENCE, "The concrete environmental evidence is not established by the source."
    elif any(re.search(pattern, asserted_value) for pattern in meaning_patterns) and not (semantic_support or meaning_pattern_supported):
        classification, reason = MEANING_BEARING_REQUIRES_EVIDENCE, "Removing this element would change what the viewer believes about the article."
    elif supported_overlap or meaning_pattern_supported:
        classification, reason = SOURCE_ASSERTED, "The element is grounded by article facts or recorded source visual evidence."
    elif any(re.search(pattern, value) for pattern in neutral_patterns):
        classification, reason = SAFE_CONTEXTUAL_COMPLETION, "The element minimally completes a believable scene without adding story meaning."
    else:
        classification, reason = MEANING_BEARING_REQUIRES_EVIDENCE, "The element is not demonstrated to be source-backed or semantically neutral."
    return {
        "element": raw,
        "classification": classification,
        "reason": reason,
        "evidence_lock": classification == SOURCE_ASSERTED,
        "semantic_role": infer_semantic_role(raw),
        "temporal_status": infer_temporal_status(raw),
    }


def _shot_elements(shot: dict[str, Any]) -> list[str]:
    explicit = shot.get("scene_elements")
    if isinstance(explicit, list) and explicit:
        return [_clean(item, 1000) for item in explicit if _clean(item)]
    elements: list[str] = []
    elements.extend(str(item) for item in shot.get("must_show") or [])
    elements.extend(str(item) for item in shot.get("important_objects") or [])
    for key in ("visual_description", "environment", "composition", "foreground", "background"):
        value = _clean(shot.get(key), 1400)
        if value:
            elements.extend(
                part.strip()
                for part in re.split(r"[,;]|(?<=[.!?])\s+", value)
                if part.strip() and not re.match(r"^(?:without|no)\s+", part.strip(), re.I)
            )
    action = _clean(shot.get("action"), 1400)
    if action:
        elements.append(action)
    return list(dict.fromkeys(elements))[:24]


def build_scene_evidence_preflight(story: dict[str, Any], visual_plan: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, Any]:
    source_media = visual_plan.get("source_visual_evidence") if isinstance(visual_plan.get("source_visual_evidence"), list) else []
    per_shot = []
    all_items: list[dict[str, Any]] = []
    for shot in shots:
        items = [classify_scene_element(item, story, visual_plan, source_media) for item in _shot_elements(shot)]
        per_shot.append({"shot_id": shot.get("shot_id"), "elements": items})
        all_items.extend(items)
    def selected(kind: str) -> list[str]:
        return list(dict.fromkeys(item["element"] for item in all_items if item["classification"] == kind))
    meaning = selected(MEANING_BEARING_REQUIRES_EVIDENCE)
    rejected = selected(REJECTED)
    result = {
        "source_asserted_elements": selected(SOURCE_ASSERTED),
        "safe_contextual_completion": selected(SAFE_CONTEXTUAL_COMPLETION),
        "meaning_bearing_unsupported_elements": meaning,
        "fabricated_event_elements": rejected,
        "symbolic_elements": selected(SYMBOLIC_EDITORIAL_ELEMENT),
        "per_shot": per_shot,
        "source_evidence_locks": [item for item in all_items if item.get("evidence_lock")],
        "semantic_roles": list(dict.fromkeys(item.get("semantic_role") for item in all_items if item.get("semantic_role") != "UNSPECIFIED")),
        "temporal_statuses": list(dict.fromkeys(item.get("temporal_status") for item in all_items if item.get("temporal_status") != "UNKNOWN")),
    }
    result["scene_evidence_status"] = "PASS" if not meaning and not rejected else "FAIL"
    return result
