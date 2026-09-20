from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from visual_specificity_analyzer import analyze_visual_specificity


STORY_TYPES = {
    "PERSON_ACTION", "OBJECT_SIGNIFICANCE", "EVENT", "PROCESS", "TRANSFORMATION",
    "PRODUCT", "PLACE", "COMPARISON", "RELATIONSHIP", "EXPLANATION", "OTHER",
}

PROGRESSION_MECHANISMS = {
    "PHYSICAL_ACTION", "STATE_CHANGE", "CONTEXT_REVEAL", "RELATIONAL_REVEAL",
    "ENVIRONMENTAL_RECONTEXTUALIZATION", "PROCESS_PROGRESSION", "TEMPORAL_CONTRAST",
    "SCALE_REVEAL", "CAUSE_EFFECT", "OBJECT_STATE_TRANSITION",
}


def _clean(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def classify_story_type(story: dict[str, Any]) -> str:
    text = " ".join(_clean(story.get(key), 2500) for key in ("what_happened", "new_development", "core_message", "viewer_takeaway")).lower()
    if re.search(r"\b(?:space mission|scientific mission|orbital mission|lunar mission|mission to)\b", text):
        return "EVENT"
    if re.search(r"\b(?:walks?|lifts?|opens?|closes?|enters?|leaves?|speaks?|wins?|won|scores?|"
                 r"performs?|demonstrates?|achieves?|completes?|breaks? (?:a |the )?record|sets? (?:a |the )?record|signs?)\b", text):
        return "PERSON_ACTION"
    if re.search(r"\b(?:process|how |steps?|manufactur|assemble|cook|produce|workflow)\b", text):
        return "PROCESS"
    if re.search(r"\b(?:before and after|compared?|versus|difference|contrast)\b", text):
        return "COMPARISON"
    if re.search(r"\b(?:transform|becomes?|turned into|converted|renovat|restor)\w*\b", text):
        return "TRANSFORMATION"
    if re.search(r"\b(?:relationship|partnership|between|connects?|linked?)\b", text):
        return "RELATIONSHIP"
    if re.search(r"\b(?:dress|gown|artifact|painting|statue|document|building|vehicle|object)\b", text) and re.search(r"\b(?:symbol|significan|legacy|historic|cultural|important|exhibit|auction|display)\w*\b", text):
        return "OBJECT_SIGNIFICANCE"
    if re.search(r"\b(?:event|ceremony|match|election|festival|conference|meeting|space mission|scientific mission|mission)\b", text):
        return "EVENT"
    if re.search(r"\b(?:launch|product|device|app|service|brand|robot|interface|hardware|processor|"
                 r"chip|platform|machine|technology|console)\b", text):
        return "PRODUCT"
    if re.search(r"\b(?:city|country|location|place|destination|site)\b", text):
        return "PLACE"
    if re.search(r"\b(?:why|explains?|means?|analysis|idea|concept)\b", text):
        return "EXPLANATION"
    return "OTHER"


def analyze_visualizability(story: dict[str, Any]) -> dict[str, Any]:
    story_type = classify_story_type(story)
    raw_facts = [_clean(item, 700) for item in story.get("key_visual_facts") or [] if _clean(item)]
    facts: list[str] = []
    factual_narration: list[str] = []
    for item in raw_facts:
        auction_split = re.split(r"\b(?:before|ahead of|prior to)\s+(?:an?\s+)?auction\b", item, maxsplit=1, flags=re.I)
        if len(auction_split) > 1:
            visible_part = auction_split[0].strip(" ,;:-")
            if visible_part:
                facts.append(visible_part)
            factual_narration.append("The public presentation is connected to an upcoming auction.")
        else:
            facts.append(item)
    abstract = re.compile(r"\b(?:empowerment|resilience|reputation|controversy|criticism|decision|policy|"
                          r"influence|importance|legacy|confidence|agency|identity|meaning|impact)\b", re.I)
    partial = [item for item in facts if abstract.search(item)]
    visual = [item for item in facts if item not in partial]
    core = _clean(story.get("core_message"), 1200)
    takeaway = _clean(story.get("viewer_takeaway"), 1200)
    narration = list(factual_narration)
    for item in (core, takeaway):
        if item and abstract.search(item) and item not in narration:
            narration.append(item)
    if re.search(r"\b(?:historical|cultural|legacy|significance|important)\w*\b", f"{core} {takeaway}", re.I):
        partial.append("The subject has historical or cultural significance beyond its visible appearance.")
    unsafe = list(dict.fromkeys([_clean(item, 700) for item in story.get("unsupported_visuals") or [] if _clean(item)]))
    if not visual:
        visual = [_clean(story.get("new_development") or story.get("what_happened") or core, 900)]
    primary = _clean("; ".join(visual[:3]) if visual else story.get("new_development") or core, 1200)
    target = 70 if visual else 50
    result = {
        "story_type": story_type,
        "visualizable_facts": visual,
        "partially_visualizable_meanings": partial,
        "narration_dependent_meanings": narration,
        "unsafe_to_visualize_without_source_media": unsafe,
        "primary_visual_story": primary,
        "supporting_narration_story": " ".join(narration) or _clean(takeaway, 1200),
        "narration_gap": {
            "visual_story_target": primary,
            "viewer_should_understand_visually": visual,
            "narration_must_explain": narration,
            "visual_semantic_coverage_target": target,
            "narration_gap_acceptable": True,
        },
        "analysis_mode": "deterministic-evidence-classification",
    }
    specificity = analyze_visual_specificity(story, result, story.get("source_visual_evidence") or [])
    result["visual_specificity_analysis"] = specificity
    result["narration_gap"].update(
        identity_narration_required=specificity["identity_narration_required"],
        identity_details_for_narration=specificity["identity_details_for_narration"],
        abstract_meanings_for_narration=specificity["abstract_meanings_for_narration"],
        factual_details_for_narration=specificity["factual_details_for_narration"],
    )
    return result


def normalize_visualizability(candidate: Any, story: dict[str, Any]) -> dict[str, Any]:
    fallback = analyze_visualizability(story)
    if not isinstance(candidate, dict):
        return fallback
    result = dict(fallback)
    story_type = str(candidate.get("story_type") or fallback["story_type"]).upper()
    story_type = story_type if story_type in STORY_TYPES else fallback["story_type"]
    # Prefer a high-confidence evidence-based action/event/product route when an
    # LLM returns a weaker PLACE/OTHER label or mistakes a person's achievement
    # for an abstract transformation.
    deterministic_type = fallback["story_type"]
    if deterministic_type in {"PERSON_ACTION", "EVENT", "PROCESS", "PRODUCT"} and (
        story_type in {"PLACE", "OTHER", "EXPLANATION"}
        or (deterministic_type == "PERSON_ACTION" and story_type == "TRANSFORMATION")
    ):
        story_type = deterministic_type
    result["story_type"] = story_type
    for key in ("visualizable_facts", "partially_visualizable_meanings", "narration_dependent_meanings", "unsafe_to_visualize_without_source_media"):
        value = candidate.get(key)
        if isinstance(value, list):
            result[key] = [_clean(item, 800) for item in value if _clean(item)]
    for key in ("primary_visual_story", "supporting_narration_story"):
        if _clean(candidate.get(key)):
            result[key] = _clean(candidate.get(key), 1600)
    gap = candidate.get("narration_gap") if isinstance(candidate.get("narration_gap"), dict) else {}
    result["narration_gap"] = {
        "visual_story_target": _clean(gap.get("visual_story_target") or result["primary_visual_story"], 1600),
        "viewer_should_understand_visually": gap.get("viewer_should_understand_visually") if isinstance(gap.get("viewer_should_understand_visually"), list) else result["visualizable_facts"],
        "narration_must_explain": gap.get("narration_must_explain") if isinstance(gap.get("narration_must_explain"), list) else result["narration_dependent_meanings"],
        "visual_semantic_coverage_target": max(0, min(100, int(gap.get("visual_semantic_coverage_target") or fallback["narration_gap"]["visual_semantic_coverage_target"]))),
        "narration_gap_acceptable": bool(gap.get("narration_gap_acceptable", True)),
    }
    specificity = analyze_visual_specificity(story, result, story.get("source_visual_evidence") or [])
    result["visual_specificity_analysis"] = specificity
    result["narration_gap"].update(
        identity_narration_required=specificity["identity_narration_required"],
        identity_details_for_narration=specificity["identity_details_for_narration"],
        abstract_meanings_for_narration=specificity["abstract_meanings_for_narration"],
        factual_details_for_narration=specificity["factual_details_for_narration"],
    )
    result["analysis_mode"] = "llm"
    return result


def symbolism_is_supported(text: str, visualizability: dict[str, Any]) -> bool:
    value = _clean(text, 10000).lower()
    unsafe_symbols = ("crown-shaped shadow", "broken chains", "phoenix", "shattering glass", "storm clearing", "spotlight as empowerment", "heartbeat spotlight")
    if any(symbol in value for symbol in unsafe_symbols):
        return False
    return not any(_clean(item, 500).lower() in value for item in visualizability.get("unsafe_to_visualize_without_source_media") or [] if _clean(item))


def focus_qc_on_visual_story(qc: dict[str, Any], visualizability: dict[str, Any]) -> dict[str, Any]:
    """Preserve observed QC evidence while removing demands assigned to narration."""
    focused = deepcopy(qc)
    gap = visualizability.get("narration_gap") or {}
    narration_text = " ".join(str(item) for item in gap.get("narration_must_explain") or []).lower()
    abstract_terms = {term for term in ("empowerment", "resilience", "identity", "confidence", "agency", "legacy", "taking back the narrative") if term in narration_text}
    coverage = focused.get("visual_semantic_coverage") if isinstance(focused.get("visual_semantic_coverage"), dict) else {}
    coverage["weak_or_missing"] = [item for item in coverage.get("weak_or_missing", []) if not any(term in str(item).lower() for term in abstract_terms)]
    focused["visual_semantic_coverage"] = coverage
    narration_terms = {term for term in re.findall(r"[a-z]{6,}", narration_text) if term not in {"public", "visual", "subject", "meaning", "through"}}
    focused["failure_reasons"] = [item for item in focused.get("failure_reasons", []) if not any(term in str(item).lower() for term in abstract_terms | narration_terms)]
    focused["primary_visual_story"] = visualizability.get("primary_visual_story")
    focused["viewer_should_understand_visually"] = gap.get("viewer_should_understand_visually") or []
    focused["narration_must_explain"] = gap.get("narration_must_explain") or []
    focused["visual_semantic_coverage_target"] = gap.get("visual_semantic_coverage_target", 70)
    focused["narration_gap_acceptable"] = bool(gap.get("narration_gap_acceptable", True))
    focused["revision_objective"] = "Repair progression, article specificity, and truthful context only for the primary visual story. Do not attempt narration-dependent meanings."
    return focused
