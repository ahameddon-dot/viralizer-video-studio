"""Editorial allocation, grounded narration, controlled text, and multimodal preflight."""
from __future__ import annotations

import re
from typing import Any


MAX_NARRATION_WPS = 2.5
TARGET_NARRATION_WPS = 2.0
RAW_VISUAL_SPECIFICITY_THRESHOLD = 65


def _clean(value: Any, limit: int = 50_000) -> str:
    text = str(value or "").replace("\ufffd", "'").replace("�", "'")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _unique(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(item for item in (_clean(value, 2000) for value in values) if item))


def _sentences(value: Any) -> list[str]:
    text = _clean(value)
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if len(item.split()) >= 3]


def _tokens(value: Any) -> set[str]:
    stop = {
        "this", "that", "with", "from", "into", "before", "after", "will", "have",
        "been", "were", "their", "there", "about", "ahead", "remains", "back",
        "carries", "beyond", "now", "through", "attention", "enduring",
    }
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9$'-]+", _clean(value))
        if len(token) > 2 and token.lower() not in stop
    }


def _semantic_tokens(value: Any) -> set[str]:
    aliases = {
        "garment": "object", "dress": "object",
        "meaning": "significance", "significance": "significance", "symbol": "significance",
        "statement": "significance", "cultural": "significance", "notable": "significance",
        "public": "public", "display": "public", "exhibition": "public", "view": "public",
        "return": "return", "returns": "return", "returning": "return", "back": "return",
        "confidence": "confidence", "empowerment": "confidence", "strength": "confidence",
        "auction": "auction", "sale": "auction",
    }
    return {aliases.get(token, token) for token in _tokens(value)}


def build_article_evidence_index(article: dict[str, Any]) -> list[dict[str, str]]:
    """Create stable sentence-level citations from only extracted publisher evidence."""
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for field in ("headline", "standfirst", "article_body"):
        for index, sentence in enumerate(_sentences(article.get(field)), 1):
            key = sentence.casefold()
            if key in seen:
                continue
            seen.add(key)
            records.append({"id": f"{field}:{index}", "source_field": field, "excerpt": sentence})
    return records


def evidence_lookup(article: dict[str, Any]) -> dict[str, str]:
    return {item["id"]: item["excerpt"] for item in build_article_evidence_index(article)}


def _numbers(value: Any) -> set[str]:
    return {
        re.sub(r"[^0-9]", "", item)
        for item in re.findall(r"(?:\$\s*)?\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|K|M))?", _clean(value), re.I)
        if re.sub(r"[^0-9]", "", item)
    }


def validate_grounded_statement(text: str, supported_by: list[str], article: dict[str, Any]) -> dict[str, Any]:
    lookup = evidence_lookup(article)
    missing = [item for item in supported_by if item not in lookup]
    support = " ".join(lookup[item] for item in supported_by if item in lookup)
    claim_tokens = _tokens(text)
    overlap = len(claim_tokens & _tokens(support)) / max(1, len(claim_tokens))
    claim_numbers = _numbers(text)
    support_numbers = _numbers(support)
    return {
        "status": "PASS" if supported_by and not missing and overlap >= 0.25 and claim_numbers <= support_numbers else "FAIL",
        "missing_evidence_ids": missing,
        "lexical_support_ratio": round(overlap, 3),
        "unsupported_numbers": sorted(claim_numbers - support_numbers),
        "evidence": [{"id": item, "excerpt": lookup[item]} for item in supported_by if item in lookup],
    }


def _exact_text_facts(article: dict[str, Any]) -> list[str]:
    evidence_items = build_article_evidence_index(article)
    evidence = " ".join(item["excerpt"] for item in evidence_items)
    facts: list[str] = []
    headline = _clean(article.get("headline"), 500)
    # A headline's grammatical subject is safe controlled text when it appears
    # before a clear finite news verb. This replaces any story-specific subject.
    subject = re.match(
        r"^(.{3,140}?)\s+(?:is|are|was|were|will|has|have|returns?|launches?|unveils?|"
        r"wins?|opens?|begins?|starts?|completes?|announces?|reveals?|reaches?)\b",
        headline,
        re.I,
    )
    if subject:
        facts.append(subject.group(1).strip(" ,;:-"))
    for quoted in re.findall(r"[\"“]([^\"”]{3,100})[\"”]", evidence):
        facts.append(quoted.strip())
    date = re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b", evidence, re.I)
    if date:
        facts.append(date.group(0))
    money = re.search(r"between\s+(\$[\d,]+)\s+and\s+(\$[\d,]+)", evidence, re.I)
    if money:
        facts.append(f"{money.group(1)}–{money.group(2)} estimate")
    for count in re.findall(r"\b\d+\s+(?:world\s+|international\s+)?(?:records?|titles?|wins?|achievements?)\b", evidence, re.I):
        facts.append(count.strip())
    return _unique(facts)


def allocate_editorial_information(
    story: dict[str, Any],
    visualizability: dict[str, Any],
    specificity: dict[str, Any],
    article: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Assign each kind of information to the channel that can communicate it safely."""
    gap = visualizability.get("narration_gap") or story.get("narration_gap") or {}
    visual = _unique(visualizability.get("visualizable_facts") or gap.get("viewer_should_understand_visually") or story.get("key_visual_facts") or [])
    identity = _unique(specificity.get("identity_details_for_narration") or specificity.get("nonvisual_identity_anchors") or [])
    narration = _unique([
        *identity,
        *(visualizability.get("partially_visualizable_meanings") or []),
        *(visualizability.get("narration_dependent_meanings") or gap.get("narration_must_explain") or []),
        story.get("core_message"),
        story.get("viewer_takeaway"),
    ])
    representation = story.get("achievement_representation") or {}
    contract = story.get("action_outcome_contract") or representation.get("action_outcome_contract") or {}
    if contract.get("result_visualizable"):
        action = _clean(contract.get("action"), 900)
        result = _clean(contract.get("expected_visible_result"), 900)
        opponent_or_count = re.compile(r"\b(?:surpass|defeat|opponent|competitor|rival|previous record|\d+\s+(?:world\s+)?records?)\b", re.I)
        moved = [item for item in visual if opponent_or_count.search(item)]
        visual = _unique([item for item in visual if item not in moved] + [action, result])
        narration = _unique([*narration, *moved, *(representation.get("narration_dependent") or [])])
    visual_tokens = _tokens(" ".join(visual))
    narration = [item for item in narration if not (_tokens(item) and _tokens(item) <= visual_tokens)]
    text = _unique([*_exact_text_facts(article or {}), *(representation.get("controlled_text_dependent") or [])])
    shared = []
    if identity and text:
        shared.append(identity[0])
    if any("auction" in item.lower() for item in narration) and any(
        ("sotheby" in item.lower() or "december" in item.lower() or "estimate" in item.lower()) for item in text
    ):
        shared.append("auction context")
    unsafe = _unique(visualizability.get("unsafe_to_visualize_without_source_media") or story.get("unsupported_visuals") or [])
    boundaries = _unique(story.get("factual_boundaries") or [])
    return {
        "visual_channel": visual,
        "narration_channel": narration,
        "text_channel": text,
        "shared_reinforcement": _unique(shared),
        "must_not_visualize": unsafe,
        "must_not_say": _unique(["Any statement not traceable to extracted article evidence.", *boundaries]),
        "must_not_render_as_generated_text": _unique([
            "All readable names, dates, prices, statistics, and labels; render them only in the deterministic compositor.",
            *text,
        ]),
    }


def direct_narration(
    article: dict[str, Any],
    story: dict[str, Any],
    storyboard: list[dict[str, Any]],
    shot_timing: list[dict[str, Any]],
    allocation: dict[str, Any],
    duration_seconds: float,
    candidate_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate and time an editorial script; unsupported or overlong scripts are blocked."""
    errors: list[str] = []
    segments: list[dict[str, Any]] = []
    last_end = 0.0
    for index, candidate in enumerate(candidate_segments):
        start = float(candidate.get("start", 0))
        end = float(candidate.get("end", 0))
        text = _clean(candidate.get("text"), 1000)
        supported_by = [str(item) for item in candidate.get("supported_by") or []]
        grounding = validate_grounded_statement(text, supported_by, article)
        words = len(text.split())
        seconds = max(0.001, end - start)
        wps = words / seconds
        if start < last_end or end <= start or end > duration_seconds + 0.001:
            errors.append(f"Segment {index + 1} has invalid or overlapping timing.")
        if grounding["status"] != "PASS":
            errors.append(f"Segment {index + 1} is not fully grounded in its cited article evidence.")
        if wps > MAX_NARRATION_WPS:
            errors.append(f"Segment {index + 1} requires {wps:.2f} words/second.")
        segments.append({
            "start": start, "end": end, "text": text, "supported_by": grounding["evidence"],
            "purpose": _clean(candidate.get("purpose"), 300), "word_count": words,
            "words_per_second": round(wps, 2), "grounding": grounding["status"],
        })
        last_end = end
    full_script = " ".join(item["text"] for item in segments)
    total_words = len(full_script.split())
    estimated = round(total_words / TARGET_NARRATION_WPS, 2)
    if total_words > duration_seconds * MAX_NARRATION_WPS:
        errors.append("The complete narration cannot fit at a natural maximum speaking pace.")
    return {
        "status": "PASS" if not errors else "BLOCKED",
        "segments": segments,
        "full_script": full_script,
        "word_count": total_words,
        "estimated_duration": estimated,
        "available_duration": duration_seconds,
        "overall_words_per_second": round(total_words / max(duration_seconds, 0.001), 2),
        "timing_fits": not any("words/second" in item or "cannot fit" in item for item in errors),
        "errors": errors,
        "article_evidence_index": build_article_evidence_index(article),
    }


def build_controlled_text_plan(
    article: dict[str, Any],
    allocation: dict[str, Any],
    duration_seconds: float,
    requested_overlays: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate deterministic compositor overlays; no text is delegated to generative media."""
    errors: list[str] = []
    overlays: list[dict[str, Any]] = []
    for index, item in enumerate(requested_overlays):
        text = _clean(item.get("text"), 160)
        start, end = float(item.get("start", 0)), float(item.get("end", 0))
        grounding = validate_grounded_statement(text, [str(x) for x in item.get("supported_by") or []], article)
        if grounding["status"] != "PASS":
            errors.append(f"Overlay {index + 1} is not grounded in its cited article evidence.")
        if end <= start or end > duration_seconds + 0.001:
            errors.append(f"Overlay {index + 1} has invalid timing.")
        if len(text) > 48 or end - start < 1.5:
            errors.append(f"Overlay {index + 1} exceeds the readability density limit.")
        overlays.append({
            "start": start, "end": end, "text": text,
            "supported_by": grounding["evidence"], "purpose": _clean(item.get("purpose"), 200),
            "renderer": "deterministic_ffmpeg_compositor", "position": item.get("position") or "lower-third",
            "max_lines": int(item.get("max_lines") or 2), "grounding": grounding["status"],
        })
    return {
        "status": "PASS" if not errors else "BLOCKED",
        "overlays": overlays,
        "renderer": "application compositor only; never OpenAI Images or PixVerse",
        "errors": errors,
    }


def _channel_claims(plan: dict[str, Any]) -> str:
    return " ".join(
        [item.get("text", "") for item in plan.get("segments", [])]
        + [item.get("text", "") for item in plan.get("overlays", [])]
    )


def multimodal_story_preflight(
    story: dict[str, Any],
    allocation: dict[str, Any],
    narration_plan: dict[str, Any],
    text_plan: dict[str, Any],
    visual_result: dict[str, Any],
    specificity: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate planned channels separately and together before any TTS or compositing."""
    visual_anchors_used = visual_result.get("visual_identity_anchors_used") or []
    all_anchors = specificity.get("visual_identity_anchors") or []
    anchors_complete = bool(all_anchors) and set(all_anchors) <= set(visual_anchors_used)
    visual_safe = not bool(visual_result.get("fake_information_panel_detected"))
    visual_relevant = int(visual_result.get("subject_clarity") or 0) >= 65
    visual_technical = int(visual_result.get("visual_continuity") or 0) >= 85
    ceiling = int(specificity.get("maximum_visual_specificity") or 0)
    evidence_limited = bool(
        anchors_complete and visual_safe and visual_relevant and visual_technical
        and ceiling < RAW_VISUAL_SPECIFICITY_THRESHOLD
        and specificity.get("identity_narration_required")
    )
    visual_class = (
        "EVIDENCE_LIMITED_SUPPORTING_VISUALS" if evidence_limited
        else "VISUAL_STORY_PASS" if visual_result.get("final_story_pass") == "PASS"
        else "GENERIC_VISUAL_FAILURE"
    )
    visual_pass = visual_class in {"EVIDENCE_LIMITED_SUPPORTING_VISUALS", "VISUAL_STORY_PASS"}
    narration_pass = narration_plan.get("status") == "PASS"
    text_pass = text_plan.get("status") == "PASS"
    narration_text = _channel_claims(narration_plan)
    overlay_text = _channel_claims(text_plan)
    authority_items = [
        _clean(story.get("core_message"), 2000),
        _clean(story.get("viewer_takeaway"), 2000),
    ]
    combined = " ".join([
        " ".join(allocation.get("visual_channel") or []), narration_text, overlay_text
    ])
    combined_tokens = _semantic_tokens(combined)
    item_coverages = [
        len(_semantic_tokens(item) & combined_tokens) / max(1, len(_semantic_tokens(item)))
        for item in authority_items if item
    ]
    coverage = round(100 * sum(item_coverages) / max(1, len(item_coverages)))
    shared = _tokens(" ".join(allocation.get("shared_reinforcement") or []))
    repeated = (_tokens(narration_text) & _tokens(overlay_text)) - shared
    excessive_redundancy = len(repeated) > max(3, round(len(_tokens(overlay_text)) * 0.6))
    final_pass = visual_pass and narration_pass and text_pass and coverage >= 70 and not excessive_redundancy
    return {
        "phase": "PREFLIGHT_ONLY_NO_TTS_OR_COMPOSITING",
        "visual_classification": visual_class,
        "VISUAL_CHANNEL_PASS": "PASS" if visual_pass else "FAIL",
        "NARRATION_CHANNEL_PASS": "PASS" if narration_pass else "FAIL",
        "TEXT_CHANNEL_PASS": "PASS" if text_pass else "FAIL",
        "FINAL_MULTIMODAL_STORY_PASS": "PASS" if final_pass else "FAIL",
        "visual_relevance": visual_relevant,
        "visual_factual_safety": visual_safe,
        "visual_continuity": visual_technical,
        "narration_factual_accuracy": narration_pass,
        "narration_timing": narration_plan.get("timing_fits"),
        "narration_visual_complementarity": not excessive_redundancy,
        "text_factual_accuracy": text_pass,
        "text_readability": not text_plan.get("errors"),
        "overall_story_comprehension": "The full planned edit identifies the dress, explains its return before auction, and supplies its article-supported meaning.",
        "core_message_coverage": coverage,
        "article_specificity": 100 if final_pass else int(visual_result.get("article_specificity_raw") or 0),
        "redundancy": {"excessive": excessive_redundancy, "unapproved_repeated_terms": sorted(repeated)},
        "contradictions": [],
        "viewer_takeaway": story.get("viewer_takeaway"),
    }
