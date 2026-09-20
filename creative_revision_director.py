from __future__ import annotations

import json
import os
from typing import Any

import httpx


FAILURE_CLASSES = {
    "TECHNICAL_GENERATION_FAILURE",
    "CONTINUITY_FAILURE",
    "SHOT_EXECUTION_FAILURE",
    "STORYBOARD_FAILURE",
    "VISUAL_CONCEPT_FAILURE",
    "SEMANTIC_COVERAGE_FAILURE",
    "GENERIC_VIDEO_FAILURE",
}


def _clean(value: Any, limit: int = 5000) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def classify_creative_failure(qc: dict[str, Any]) -> list[str]:
    if not qc.get("available", True):
        return ["TECHNICAL_GENERATION_FAILURE"]
    failures: list[str] = []
    if _number(qc.get("visual_continuity")) < 65:
        failures.append("CONTINUITY_FAILURE")
    if _number(qc.get("story_progression")) < 70 or _number(qc.get("narrative_progression")) < 70:
        failures.append("STORYBOARD_FAILURE")
    coverage = qc.get("visual_semantic_coverage") if isinstance(qc.get("visual_semantic_coverage"), dict) else {}
    if _number(coverage.get("overall_score")) < 70:
        failures.append("SEMANTIC_COVERAGE_FAILURE")
    if _number(qc.get("environmental_storytelling")) < 60:
        failures.append("VISUAL_CONCEPT_FAILURE")
    if _number(qc.get("article_specificity")) < 65 or _number(qc.get("generic_ad_risk")) > 40:
        failures.append("GENERIC_VIDEO_FAILURE")
    if qc.get("fake_information_panel_detected"):
        failures.append("SHOT_EXECUTION_FAILURE")
    return list(dict.fromkeys(failures or ["VISUAL_CONCEPT_FAILURE"]))


def route_revision(failure_classes: list[str]) -> dict[str, Any]:
    classes = [item for item in failure_classes if item in FAILURE_CLASSES]
    creative = any(item in classes for item in ("STORYBOARD_FAILURE", "VISUAL_CONCEPT_FAILURE", "SEMANTIC_COVERAGE_FAILURE", "GENERIC_VIDEO_FAILURE"))
    if creative:
        return {"repair_layer": "CREATIVE_REVISION_DIRECTOR", "regenerate": "REVISED_STORYBOARD_AND_AFFECTED_SHOTS", "reuse_prior_references": False, "reason": "The viewer-inferred story or semantic progression is wrong; another PixVerse attempt cannot repair the underlying visual story."}
    if "CONTINUITY_FAILURE" in classes:
        return {"repair_layer": "CONTINUITY", "regenerate": "ADJACENT_AFFECTED_SHOTS", "reuse_prior_references": True, "reason": "Repair the boundary between affected shots."}
    if any(item in classes for item in ("SHOT_EXECUTION_FAILURE", "TECHNICAL_GENERATION_FAILURE")):
        return {"repair_layer": "SHOT_GENERATION", "regenerate": "FAILED_SHOTS_ONLY", "reuse_prior_references": True, "reason": "The approved creative plan remains authoritative; retry only failed execution."}
    return {"repair_layer": "NONE", "regenerate": "NONE", "reuse_prior_references": True, "reason": "No recognized failure requires revision."}


def revision_limit(value: Any = None) -> int:
    raw = value if value is not None else os.getenv("CREATIVE_REVISION_LIMIT", "2")
    try:
        return max(0, min(2, int(raw)))
    except (TypeError, ValueError):
        return 2


def validate_revision(revision: dict[str, Any], unsupported_visuals: list[str] | None = None) -> dict[str, Any]:
    required = ("failure_diagnosis", "preserve", "remove", "change", "missing_meanings", "new_visual_mechanism", "revised_hook", "revised_story_beats", "revised_continuity_strategy", "revised_hero_payoff", "expected_viewer_inference")
    structure = all(key in revision for key in required)
    arrays = structure and all(isinstance(revision.get(key), list) for key in ("failure_diagnosis", "preserve", "remove", "change", "missing_meanings", "revised_story_beats"))
    beats = revision.get("revised_story_beats") if isinstance(revision.get("revised_story_beats"), list) else []
    beat_fields = bool(beats) and all(isinstance(beat, dict) and all(_clean(beat.get(key)) for key in ("purpose", "visual", "before_viewer_understands", "after_viewer_understands")) for beat in beats)
    progression = beat_fields and all(_clean(beat.get("before_viewer_understands")).lower() != _clean(beat.get("after_viewer_understands")).lower() for beat in beats)
    mechanism = bool(_clean(revision.get("new_visual_mechanism")) and _clean(revision.get("revised_hook")) and _clean(revision.get("revised_hero_payoff")) and _clean(revision.get("expected_viewer_inference")))
    positive = " ".join(_clean(revision.get(key), 8000) for key in ("new_visual_mechanism", "revised_hook", "revised_story_beats", "revised_hero_payoff")).lower()
    unsupported = [str(item).lower() for item in (unsupported_visuals or []) if str(item).strip()]
    factual = not any(item in positive for item in unsupported)
    checks = {"structure": structure and arrays, "meaning_added_per_beat": progression, "complete_visual_mechanism": mechanism, "factual_boundaries_respected": factual}
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "beat_count": len(beats)}


def apply_revision_to_visual_plan(visual_plan: dict[str, Any], revision: dict[str, Any]) -> dict[str, Any]:
    revised = dict(visual_plan)
    revised.update(
        selected_creative_concept=_clean(revision.get("new_visual_mechanism"), 1600),
        creative_concept_selection_reason="Creative Revision Director response to failed human-like story comprehension QC.",
        visual_hook=_clean(revision.get("revised_hook"), 1200),
        story_beats=revision.get("revised_story_beats") or [],
        continuity_strategy=_clean(revision.get("revised_continuity_strategy"), 1200),
        hero_payoff=_clean(revision.get("revised_hero_payoff"), 1200),
        expected_viewer_inference=_clean(revision.get("expected_viewer_inference"), 1600),
        creative_revision_decisions=revision,
    )
    return revised


def _response_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    return "".join(str(part.get("text") or "") for item in data.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text")


async def direct_creative_revision(
    *,
    article: dict[str, Any],
    story: dict[str, Any],
    visual_plan: dict[str, Any],
    storyboard: list[dict[str, Any]],
    creative_qc: dict[str, Any],
    duration: int,
    prior_revisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    failure_classes = classify_creative_failure(creative_qc)
    authority = {
        "article_evidence": {"headline": article.get("headline") or article.get("topic"), "standfirst": article.get("standfirst") or article.get("summary"), "article_body": _clean(article.get("article_body"), 30000), "key_visual_facts": story.get("key_visual_facts") or []},
        "core_message": story.get("core_message"),
        "viewer_takeaway": story.get("viewer_takeaway"),
        "visualizability_analysis": visual_plan.get("visualizability_analysis") or story.get("visualizability_analysis") or {},
        "narration_gap": visual_plan.get("narration_gap") or {},
        "core_visual_subject": visual_plan.get("core_visual_subject"),
        "factual_boundaries": story.get("factual_boundaries") or [],
        "unsupported_visuals": story.get("unsupported_visuals") or [],
        "existing_creative_concept": visual_plan.get("selected_creative_concept"),
        "existing_storyboard": storyboard,
        "creative_qc": creative_qc,
        "failure_classes": failure_classes,
        "duration_seconds": duration,
        "prior_revision_attempts": prior_revisions or [],
    }
    instruction = """You are Viralizer's Creative Revision Director. Redesign only the weak visual storytelling layer after human-like Creative Story QC failure. Story Understanding, Visualizability Analysis, the exact core visual subject, factual boundaries, and semantic authority are immutable. Answer: what must visually CHANGE so that a muted viewer understands the primary visualizable story? narration_must_explain is explicitly OUT OF SCOPE for visuals: do not include those meanings in missing_meanings, revised beats, hero payoff, or expected viewer inference. Do not force narration-dependent meanings into imagery. Do not optimize mechanically for scores. Missing history does not automatically mean an old photograph; missing public attention does not automatically mean a crowd; missing empowerment does not automatically mean dramatic light. Do not decorate the same close-medium-wide sequence. Match progression to story_type: physical action is optional, while factual context reveal, relational reveal, environmental recontextualization, process progression, temporal contrast, scale reveal, cause/effect, state change, or object-state transition may be correct. Camera or lighting alone is not progression. You may use minimal SAFE_CONTEXTUAL_COMPLETION such as neutral walls, floors, empty negative space, ambient light, natural shadows, generic surfaces, and necessary supports. These details must carry no article meaning and may not create a story beat. You may not create new beats from unsupported contextual details. Crowds, visitors, staff, photographers, ropes, benches, crates, covered objects, preparation activity, signage, furniture, additional mannequins, other displayed artifacts, or before-states require evidence. Do not assume a glass case, pedestal, platform, ropes, furniture, or any specific display method unless article facts or source_visual_evidence establish it. Never invent cover removal, empty-to-occupied display transitions, or other events. Use only as many beats as source-supported meanings; a two-beat detail-to-complete-subject-and-neutral-context progression is valid when the evidence supports no third meaning. Create genuine progression where each beat reveals a different verified level of context. Controlled metaphor is a last resort: it must be necessary, clearly editorial, subject-connected, non-deceptive, and materially improve comprehension. Never present metaphor as historical evidence. Reject crown shadows, broken chains, phoenix imagery, shattering glass, storms clearing, and spotlights used as empowerment unless directly source-supported. Do not use any signage, catalog, placard, label, document, pseudo-text, logo, or unsupported person/event even if text would be unreadable or blurred. Preserve what already works. Use a small number of beats feasible within the supplied duration. If prior attempts were rejected, materially replace their failed mechanism and forbidden elements rather than paraphrasing them.

Return only structured JSON with exactly:
failure_diagnosis (array), preserve (array), remove (array), change (array), missing_meanings (array), new_visual_mechanism (string), revised_hook (string), revised_story_beats (array of objects with purpose, visual, before_viewer_understands, after_viewer_understands, source_support, environmental_change, controlled_metaphor, duration_seconds), revised_continuity_strategy (string), revised_hero_payoff (string), expected_viewer_inference (string).

Durations must be positive integers summing exactly to the requested duration. Before/after understanding must be meaningfully different for every beat. Output decisions only, never hidden reasoning."""
    payload = {"model": os.getenv("OPENAI_STORY_MODEL", "gpt-4.1-mini"), "input": [{"role": "system", "content": [{"type": "input_text", "text": instruction}]}, {"role": "user", "content": [{"type": "input_text", "text": json.dumps(authority, ensure_ascii=False)}]}], "text": {"format": {"type": "json_object"}}}
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"}, json=payload)
    response.raise_for_status()
    result = json.loads(_response_text(response.json()))
    result["failure_classification"] = failure_classes
    result["revision_route"] = route_revision(failure_classes)
    result["validation"] = validate_revision(result, story.get("unsupported_visuals") or [])
    result["model"] = payload["model"]
    return result
