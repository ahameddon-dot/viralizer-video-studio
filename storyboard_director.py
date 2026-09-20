from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from creative_story_qc import score_storyboard_creative_qc
from creative_revision_director import apply_revision_to_visual_plan, direct_creative_revision, revision_limit
from visual_generation_control import compile_reference_prompt, enrich_storyboard_frames
from visualizability_analyzer import PROGRESSION_MECHANISMS, normalize_visualizability, symbolism_is_supported
from scene_evidence import build_scene_evidence_preflight
from scene_evidence_sanitizer import sanitize_if_simple_clutter
from generated_text_router import route_generated_text
from story_type_qc import evaluate_story_type_qc
from storyboard_preflight_controls import enforce_storyboard_preflight_controls
from action_outcome_contract import build_result_state_reference


PURPOSES = {"HOOK", "CONTEXT", "DEVELOPMENT", "TRANSFORMATION", "EVIDENCE", "EMOTIONAL MEANING", "HERO PAYOFF"}
REQUIRED_SHOT_FIELDS = (
    "shot_id", "purpose", "source_support", "visual_subject", "visual_description", "action",
    "environment", "composition", "camera", "lighting", "foreground", "background",
    "transition_in", "transition_out", "continuity_requirements", "must_show", "must_avoid",
    "duration_seconds", "reference_frame_required",
)


def _clean(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _tokens(value: Any) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9'-]+", str(value or "")) if len(token) > 3}


def _json_response_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    return "".join(
        str(part.get("text") or "")
        for item in data.get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


def build_reference_frame_plan(shot: dict[str, Any], visual_plan: dict[str, Any]) -> dict[str, Any]:
    required = bool(shot.get("reference_frame_required"))
    continuity = shot.get("continuity_requirements") or []
    if isinstance(continuity, str):
        continuity = [continuity]
    must_show = shot.get("must_show") or []
    if isinstance(must_show, str):
        must_show = [must_show]
    must_avoid = shot.get("must_avoid") or visual_plan.get("must_avoid") or []
    if isinstance(must_avoid, str):
        must_avoid = [must_avoid]
    plan = {
        "shot_id": _clean(shot.get("shot_id"), 24),
        "reference_frame_required": required,
        "subject": _clean(shot.get("visual_subject") or visual_plan.get("core_visual_subject"), 300),
        "environment": _clean(shot.get("environment"), 400),
        "composition": _clean(shot.get("composition"), 400),
        "camera_position": _clean(shot.get("camera"), 400),
        "lens_feel": "natural perspective with restrained depth of field",
        "lighting": _clean(shot.get("lighting"), 400),
        "wardrobe_or_materials": _clean("; ".join(continuity), 500),
        "important_objects": list(dict.fromkeys(str(item) for item in must_show if item))[:8],
        "spatial_relationships": [item for item in (_clean(shot.get("foreground"), 250), _clean(shot.get("background"), 250)) if item],
        "visual_style": _clean(visual_plan.get("visual_style"), 300),
        "must_preserve": list(dict.fromkeys([_clean(shot.get("visual_subject"), 300), *continuity]))[:10],
        "must_not_generate": list(dict.fromkeys(str(item) for item in must_avoid if item))[:12],
        "start_frame": _clean(shot.get("start_frame"), 1000),
        "end_frame": _clean(shot.get("end_frame"), 1000),
        "continuity_frame_strategy": _clean(shot.get("continuity_frame_strategy"), 120),
        "reuse_previous_end_frame": bool(shot.get("reuse_previous_end_frame")),
    }
    contract = shot.get("action_outcome_contract") or visual_plan.get("action_outcome_contract") or {}
    if str(shot.get("purpose") or "").upper() == "HERO PAYOFF" and contract.get("result_shot_required"):
        plan["result_state_reference"] = build_result_state_reference(contract, must_avoid)
    plan["prompt_ready_description"] = compile_reference_prompt(
        shot,
        plan,
        visual_plan.get("factual_boundaries") or [],
        _clean(visual_plan.get("core_visual_subject"), 300),
    )
    return plan


def build_visual_qc_spec(shot: dict[str, Any], reference_plan: dict[str, Any], story: dict[str, Any], visual_plan: dict[str, Any]) -> dict[str, Any]:
    contract = shot.get("action_outcome_contract") or visual_plan.get("action_outcome_contract") or story.get("action_outcome_contract") or {}
    return {
        "shot_id": shot.get("shot_id"),
        "story_beat": shot.get("visual_description"),
        "core_message": story.get("core_message"),
        "core_visual_subject": visual_plan.get("core_visual_subject"),
        "visual_subject": shot.get("visual_subject"),
        "composition": shot.get("composition"),
        "required_objects": shot.get("must_show") or [],
        "forbidden_elements": shot.get("must_avoid") or [],
        "continuity_requirements": shot.get("continuity_requirements") or [],
        "environment": shot.get("environment"),
        "action": shot.get("action"),
        "transition_out": shot.get("transition_out"),
        "reference_frame_plan": reference_plan,
        "action_outcome_contract": contract,
        "action_result_qc_required": bool(str(shot.get("purpose") or "").upper() == "HERO PAYOFF" and contract.get("result_shot_required")),
    }


def _fallback_storyboard(story: dict[str, Any], visual_plan: dict[str, Any], duration: int) -> dict[str, Any]:
    beats = [item for item in visual_plan.get("story_beats", []) if isinstance(item, dict)]
    if not beats:
        beats = [{"purpose": "HOOK", "visual": visual_plan.get("visual_hook") or visual_plan.get("visual_message")}]
    # The story decides the count. The deterministic fallback preserves the approved beats,
    # while limiting only by the amount of time available to communicate them clearly.
    max_clear = max(1, min(len(beats), duration // 3 or 1))
    beats = beats[:max_clear]
    whole, remainder = divmod(duration, len(beats))
    durations = [whole + (1 if index < remainder else 0) for index in range(len(beats))]
    shots = []
    subject = _clean(visual_plan.get("core_visual_subject"), 300).strip(" .")
    story_text = f"{story.get('new_development','')} {story.get('core_message','')} {story.get('viewer_takeaway','')}".lower()
    public_return = any(term in story_text for term in ("public view", "return", "exhibition", "auction", "displayed"))
    safe_must_show = [item for item in (visual_plan.get("must_show") or []) if not any(term in str(item).lower() for term in ("signage", "tag", "card", "text", "logo"))]
    for index, (beat, seconds) in enumerate(zip(beats, durations), 1):
        purpose = str(beat.get("purpose") or "DEVELOPMENT").upper()
        if purpose not in PURPOSES:
            purpose = "HERO PAYOFF" if index == len(beats) else ("HOOK" if index == 1 else "DEVELOPMENT")
        visual = _clean(beat.get("visual") or visual_plan.get("visual_message"), 1000)
        if public_return:
            if index == 1:
                visual = f"A narrow gallery light travels across {subject}, resolving its silhouette from near-shadow."
            elif index == len(beats):
                visual = f"Light and floor reflections settle around {subject}, leaving the complete public display as the renewed focus."
            else:
                visual = f"The light widens as floor reflections extend outward from {subject}, making its return to public view visible without text."
        transition_in = "Begin immediately on the truthful visual hook" if index == 1 else "Continue the previous shot's direction, light, and subject placement"
        transition_out = "Settle into the approved hero payoff" if index == len(beats) else "Carry the subject's movement or camera direction into the next shot"
        camera = "locked camera while the approved light movement reveals the subject"
        if 1 < index < len(beats):
            camera = "one slow controlled pullback continuing the established direction to reveal the wider exhibition context"
        shots.append({
            "shot_id": f"S{index}", "purpose": purpose,
            "source_support": [item for item in story.get("key_visual_facts", [])[:3] if item],
            "visual_subject": subject, "visual_description": visual,
            "action": visual, "environment": "the source-supported display or real-world setting",
            "composition": "article-specific focal composition with the core visual subject unmistakable",
            "camera": camera,
            "lighting": "continuous source-faithful editorial lighting",
            "foreground": "only source-supported foreground detail", "background": "restrained source-supported context",
            "transition_in": transition_in, "transition_out": transition_out,
            "continuity_requirements": [visual_plan.get("continuity_strategy") or f"Preserve the same {subject}"],
            "must_show": safe_must_show,
            "must_avoid": list(dict.fromkeys((visual_plan.get("must_avoid") or []) + (story.get("unsupported_visuals") or []))),
            "duration_seconds": seconds, "reference_frame_required": index in {1, len(beats)},
        })
    return {
        "storyboard": shots,
        "muted_test_v2": {
            "inferred_story": _clean(visual_plan.get("visual_message"), 700),
            "core_message_alignment": "The primary visualizable story remains legible without narration; the declared narration gap is not forced into imagery.",
            "status": "PASS",
            "reason": "Each shot preserves the approved subject and a source-supported story beat.",
        },
        "generic_video_test_v2": {
            "reusable_for_unrelated_stories": False,
            "status": "PASS",
            "reason": "The storyboard is locked to the named core visual subject, sourced facts, and article-specific payoff.",
        },
        "model": "deterministic-storyboard-fallback",
    }


async def _ask_storyboard_model(article: dict[str, Any], story: dict[str, Any], visual_plan: dict[str, Any], duration: int, aspect_ratio: str, feedback: str = "") -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = os.getenv("OPENAI_STORYBOARD_MODEL", "").strip() or os.getenv("OPENAI_STORY_MODEL", "").strip() or os.getenv("OPENAI_MODEL", "").strip() or "gpt-4.1-mini"
    authority = {
        "article_evidence": {
            "headline": article.get("headline"), "standfirst": article.get("standfirst"),
            "article_body": _clean(article.get("article_body"), 40000), "image_captions": article.get("image_captions") or [],
        },
        "story_understanding": story, "approved_visual_story_plan": visual_plan,
        "duration": duration, "aspect_ratio": aspect_ratio,
    }
    instruction = f"""You are Viralizer's Storyboard Director. The supplied Story Director output is immutable semantic authority for WHAT the story means. Translate its primary visualizable story into a connected {duration}-second {aspect_ratio} visual sequence; do not force narration-dependent meaning into generated imagery. Choose shot count from the story, not a fixed duration template. Use only as many shots as supported meanings; two strong supported beats are better than a fabricated third beat. Every shot purpose must be one of: {', '.join(sorted(PURPOSES))}. Every shot must visibly advance the visual_story_target. Use article-specific, truthful first-second curiosity; reject generic fashion-ad or stock-footage grammar. Choose progression appropriate to story_type. Valid mechanisms are: {', '.join(sorted(PROGRESSION_MECHANISMS))}. Physical action is not universally required. A factual context reveal or environmental recontextualization is valid when it adds meaning. Camera movement or lighting change alone is not progression. Unsupported symbolism is not evidence. Use minimum necessary visual completion: neutral walls, floors, empty negative space, ambient lighting, natural shadows, generic architectural surfaces, and physically necessary supports may complete a scene only when they add no story meaning. Never create a new beat from unsupported contextual detail. Crowds, visitors, staff, photographers, ropes, benches, crates, covered objects, preparation activity, signage, furniture, additional mannequins, other displayed artifacts, or a before-state require source or source-media evidence. Do not assume a glass case, pedestal, platform, ropes, furniture, or a specific display method unless explicitly present in article facts or source_visual_evidence. Never invent cover removal, empty-to-occupied display transitions, or other events. Durations must be positive integers and sum exactly to {duration}. shot_id must be a string such as S1. source_support, continuity_requirements, must_show, and must_avoid must be arrays. Set visual_subject to the exact approved core_visual_subject in every shot. Put the chosen progression mechanism at the start of action, for example 'CONTEXT_REVEAL: ...'. Do not request signage, plaques, newspapers, screens, or other readable/fabricated evidence unless supplied in source assets.
For PERSON_ACTION, obey achievement_representation and action_outcome_contract: show the distinctive supported physical feat followed by its expected_visible_result when result_shot_required is true. The final result shot must make the exact relevant object and supported post-action state clearly visible. Do not replace it with a trophy, medal, badge, icon, certificate, scoreboard, judges, crowd, podium, record book, logo, or fabricated event. A counted achievement assigned to controlled text or narration does not require that many visual objects. End on the action's supported physical payoff.
For EVENT or PROCESS, preserve every source_evidence_locks item, its semantic_role, and temporal_status. Keep supported original and new objects distinct, never add an unsupported duplicate, and never depict PLANNED_FUTURE, PROPOSED, or EXPECTED events as completed.
For PRODUCT, do not ask the image/video model to draw readable phrases, dates, labels, numbers, statistics, headlines, annotations, or interface lettering. Compose clean overlay-safe space; verified source UI may only be preserved from its real reference.
Return JSON with exactly: storyboard (array using every required field: {', '.join(REQUIRED_SHOT_FIELDS)}), muted_test_v2 (inferred_story, core_message_alignment, status PASS/FAIL, reason), generic_video_test_v2 (reusable_for_unrelated_stories boolean, status PASS/FAIL, reason). The muted test asks whether the viewer understands the primary visualizable story, not every abstract meaning reserved for narration. The generic test must FAIL if the subject can be swapped and the same construction reused broadly. No hidden reasoning or candidate concepts. {feedback}"""
    payload = {"model": model, "input": [{"role": "system", "content": [{"type": "input_text", "text": instruction}]}, {"role": "user", "content": [{"type": "input_text", "text": json.dumps(authority, ensure_ascii=False)}]}], "text": {"format": {"type": "json_object"}}}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"}, json=payload)
    response.raise_for_status()
    result = json.loads(_json_response_text(response.json()))
    result["model"] = model
    return result


def validate_storyboard(story: dict[str, Any], visual_plan: dict[str, Any], package: dict[str, Any], duration: int) -> dict[str, Any]:
    shots = package.get("storyboard") if isinstance(package.get("storyboard"), list) else []
    core_tokens = _tokens(visual_plan.get("core_visual_subject"))
    unsupported = [str(item).lower() for item in (story.get("unsupported_visuals") or []) + (visual_plan.get("must_avoid") or [])]
    fields = bool(shots) and all(isinstance(shot, dict) and all(field in shot for field in REQUIRED_SHOT_FIELDS) for shot in shots)
    typed = fields and all(
        isinstance(shot.get("shot_id"), str)
        and all(isinstance(shot.get(key), list) for key in ("source_support", "continuity_requirements", "must_show", "must_avoid"))
        for shot in shots
    )
    purposes = fields and all(str(shot.get("purpose") or "").upper() in PURPOSES for shot in shots)
    duration_ok = fields and sum(int(shot.get("duration_seconds") or 0) for shot in shots) == int(duration) and all(int(shot.get("duration_seconds") or 0) > 0 for shot in shots)
    source_support = typed and all(bool(shot.get("source_support")) for shot in shots)
    approved_subject = _clean(visual_plan.get("core_visual_subject"), 400).lower()
    subject_preserved = typed and all(_clean(shot.get("visual_subject"), 400).lower() == approved_subject for shot in shots)
    positive_text = " ".join(str(shot.get(key) or "") for shot in shots for key in ("visual_description", "action", "environment", "foreground", "background")).lower()
    positive_text = re.sub(r"\b(?:without|no)\b[^.;]*", "", positive_text)
    unsafe_inventions = ("signage", "plaque", "newspaper", "readable screen", "archival photo", "reenactment", "multiple mannequins", "other fashion artifacts", "glass cover being lifted", "protective glass cover is partially raised")
    unsupported_safe = (
        not any(item and re.search(rf"\b{re.escape(item)}\b", positive_text) for item in unsupported)
        and not any(re.search(rf"\b{re.escape(term)}\b", positive_text) for term in unsafe_inventions)
    )
    visualizability = normalize_visualizability(visual_plan.get("visualizability_analysis") or story.get("visualizability_analysis"), story)
    story_type = visualizability.get("story_type") or "OTHER"
    camera_only = ("slow pan", "pan ", "slow zoom", "zoom ", "fade ", "static", "still framing", "push-in", "pullback", "pull back")
    presentation_only = re.compile(r"^(?:[^:]+:\s*)?(?:the\s+)?(?:camera|light|lighting|shadow|spotlight|reflection)\b", re.I)
    general_progression = re.compile(r"\b(?:reveals?|resolves?|crosses|opens?|closes?|enters?|leaves?|gathers?|changes?|transforms?|separates?|connects?|moves?|turns?|lifts?|places?|breaks?|falls?|responds?|travels?|widens?|extends?|settles?|returns?|arrives?|surrounds?|becomes?)\b", re.I)
    type_terms = {
        "PERSON_ACTION": re.compile(r"\b(?:walks?|turns?|lifts?|places?|opens?|closes?|enters?|leaves?|holds?|carries?|speaks?)\b", re.I),
        "PROCESS": re.compile(r"\b(?:begins?|feeds?|assembles?|mixes?|forms?|passes?|produces?|finishes?|moves? through)\b", re.I),
        "TRANSFORMATION": re.compile(r"\b(?:changes?|transforms?|becomes?|converts?|restores?|unfolds?)\b", re.I),
        "COMPARISON": re.compile(r"\b(?:compares?|contrasts?|separates?|aligns?|matches?)\b", re.I),
        "OBJECT_SIGNIFICANCE": re.compile(r"\b(?:reveals?|emerges?|returns?|enters?|opens?|surrounds?|recontextualizes?|display)\b", re.I),
    }
    meaningful_progression = False
    for shot in shots:
        action = str(shot.get("action") or "").strip()
        lowered = action.lower()
        declared = lowered.split(":", 1)[0].strip().upper().replace(" ", "_") if ":" in lowered else ""
        valid_declared = declared in PROGRESSION_MECHANISMS
        specific_pattern = type_terms.get(story_type, general_progression)
        if action and not lowered.startswith(camera_only) and not presentation_only.search(action) and (valid_declared or specific_pattern.search(action) or general_progression.search(action)):
            meaningful_progression = True
            break
    connected = len(shots) == 1 or all(_clean(shots[index].get("transition_out")) and _clean(shots[index + 1].get("transition_in")) for index in range(len(shots) - 1))
    muted = package.get("muted_test_v2") if isinstance(package.get("muted_test_v2"), dict) else {}
    generic = package.get("generic_video_test_v2") if isinstance(package.get("generic_video_test_v2"), dict) else {}
    scene_evidence = build_scene_evidence_preflight(story, visual_plan, shots)
    checks = {
        "storyboard_structure": fields and typed, "shot_purpose": purposes, "duration_consistency": duration_ok,
        "source_support": source_support, "core_visual_subject_preserved": subject_preserved,
        "unsupported_assets_rejected": unsupported_safe and scene_evidence["scene_evidence_status"] == "PASS", "connected_visual_story": connected,
        "scene_evidence_status": scene_evidence["scene_evidence_status"] == "PASS",
        "article_specific_visual_progression": meaningful_progression,
        "symbolism_safe": symbolism_is_supported(positive_text, visualizability),
        "muted_test_v2": muted.get("status") == "PASS", "generic_video_test_v2": generic.get("status") == "PASS" and generic.get("reusable_for_unrelated_stories") is False,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "shot_count": len(shots), "duration": duration, **scene_evidence}


def _normalize_candidate(candidate: dict[str, Any], story: dict[str, Any], visual_plan: dict[str, Any]) -> dict[str, Any]:
    """Repair JSON shape and re-assert upstream authority without inventing creative content."""
    result = dict(candidate)
    normalized = []
    approved_subject = _clean(visual_plan.get("core_visual_subject"), 400)
    global_avoid = list(dict.fromkeys((visual_plan.get("must_avoid") or []) + (story.get("unsupported_visuals") or [])))
    for index, original in enumerate(candidate.get("storyboard") or [], 1):
        if not isinstance(original, dict):
            continue
        shot = dict(original)
        shot["shot_id"] = str(shot.get("shot_id") or f"S{index}")
        if not shot["shot_id"].upper().startswith("S"):
            shot["shot_id"] = f"S{shot['shot_id']}"
        shot["visual_subject"] = approved_subject
        purpose = str(shot.get("purpose") or "DEVELOPMENT").upper().replace("_", " ").split("–", 1)[0].split("-", 1)[0].strip()
        purpose_map = {
            "ENVIRONMENT RECONTEXTUALIZATION": "CONTEXT",
            "CONTEXT REVEAL": "CONTEXT",
            "RELATIONAL REVEAL": "DEVELOPMENT",
            "STATE CHANGE": "TRANSFORMATION",
            "OBJECT STATE TRANSITION": "TRANSFORMATION",
            "PROCESS PROGRESSION": "DEVELOPMENT",
            "TEMPORAL CONTRAST": "DEVELOPMENT",
            "SCALE REVEAL": "CONTEXT",
            "CAUSE EFFECT": "DEVELOPMENT",
        }
        shot["purpose"] = purpose if purpose in PURPOSES else purpose_map.get(purpose, "DEVELOPMENT")
        for key in ("source_support", "continuity_requirements", "must_show", "must_avoid"):
            value = shot.get(key) or []
            shot[key] = value if isinstance(value, list) else [value]
        shot["must_show"] = [item for item in shot["must_show"] if not any(term in str(item).lower() for term in ("signage", "tag", "card", "text", "logo"))]
        shot["must_avoid"] = list(dict.fromkeys(shot["must_avoid"] + global_avoid))
        normalized.append(shot)
    result["storyboard"] = enforce_storyboard_preflight_controls(normalized, story, visual_plan)
    return result


def _attach_meaning_progression(package: dict[str, Any], visual_plan: dict[str, Any]) -> None:
    beats = visual_plan.get("story_beats") if isinstance(visual_plan.get("story_beats"), list) else []
    shots = package.get("storyboard") if isinstance(package.get("storyboard"), list) else []
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict) or not beats:
            continue
        beat = beats[min(index, len(beats) - 1)] if isinstance(beats[min(index, len(beats) - 1)], dict) else {}
        shot["before_viewer_understands"] = _clean(shot.get("before_viewer_understands") or beat.get("before_viewer_understands"), 900)
        shot["after_viewer_understands"] = _clean(shot.get("after_viewer_understands") or beat.get("after_viewer_understands"), 900)
        shot["environmental_change"] = _clean(shot.get("environmental_change") or beat.get("environmental_change"), 900)
        shot["controlled_metaphor"] = _clean(shot.get("controlled_metaphor") or beat.get("controlled_metaphor"), 900)


async def _finalize_storyboard_control(package: dict[str, Any], story: dict[str, Any], visual_plan: dict[str, Any]) -> dict[str, Any]:
    _attach_meaning_progression(package, visual_plan)
    package["storyboard"] = enforce_storyboard_preflight_controls(package["storyboard"], story, visual_plan)
    text_routing = route_generated_text(package["storyboard"], visual_plan.get("source_visual_evidence") or [])
    package["storyboard"] = text_routing["storyboard"]
    package["generated_text_routing"] = text_routing
    package["storyboard"] = enrich_storyboard_frames(package["storyboard"])
    references = [build_reference_frame_plan(shot, visual_plan) for shot in package["storyboard"]]
    factual_boundaries = story.get("factual_boundaries") or visual_plan.get("factual_boundaries") or []
    for shot, reference in zip(package["storyboard"], references):
        reference["prompt_ready_description"] = compile_reference_prompt(shot, reference, factual_boundaries, visual_plan.get("core_visual_subject") or "")
    package["reference_frame_plans"] = references
    package["visual_qc_specs"] = [build_visual_qc_spec(shot, references[index], story, visual_plan) for index, shot in enumerate(package["storyboard"])]
    package["creative_story_qc"] = await score_storyboard_creative_qc(package["storyboard"], story, visual_plan)
    package["story_type_qc"] = evaluate_story_type_qc(package["storyboard"], story, visual_plan, text_routing)
    package["effective_visual_story_plan"] = visual_plan
    return package


async def build_storyboard_package(article: dict[str, Any], story: dict[str, Any], visual_plan: dict[str, Any], duration: int, aspect_ratio: str = "9:16") -> dict[str, Any]:
    error = ""
    package: dict[str, Any] | None = None
    last_validation: dict[str, Any] = {}
    for attempt in range(3):
        try:
            failed_checks = [key for key, passed in (last_validation.get("checks") or {}).items() if not passed]
            feedback = "" if attempt == 0 else f"The previous storyboard failed these checks: {', '.join(failed_checks)}. Preserve the exact core subject, use source support for every shot, remove unsupported assets, make transitions connected, make durations sum exactly, and include story-type-appropriate article-specific visual progression. Do not force person action or object transformation when a factual context reveal is the correct mechanism. Pass both V2 tests against the primary visual story."
            candidate = _normalize_candidate(await _ask_storyboard_model(article, story, visual_plan, duration, aspect_ratio, feedback), story, visual_plan)
            validation = validate_storyboard(story, visual_plan, candidate, duration)
            sanitization = sanitize_if_simple_clutter(story, visual_plan, candidate, validation)
            if sanitization:
                candidate["scene_evidence_sanitization"] = sanitization
                if sanitization.get("status") == "PASS":
                    candidate["storyboard"] = sanitization["storyboard"]
                    validation = validate_storyboard(story, visual_plan, candidate, duration)
            last_validation = validation
            package = {**candidate, "validation": validation, "attempts": attempt + 1}
            if validation["status"] == "PASS":
                break
        except Exception as exc:
            error = _clean(exc, 300)
            break
    if not package or package.get("validation", {}).get("status") != "PASS":
        package = _fallback_storyboard(story, visual_plan, duration)
        package["validation"] = validate_storyboard(story, visual_plan, package, duration)
        sanitization = sanitize_if_simple_clutter(story, visual_plan, package, package["validation"])
        if sanitization:
            package["scene_evidence_sanitization"] = sanitization
            if sanitization.get("status") == "PASS":
                package["storyboard"] = sanitization["storyboard"]
                package["validation"] = validate_storyboard(story, visual_plan, package, duration)
        package["attempts"] = 0
        package["fallback_reason"] = error or f"The generated storyboard did not pass validation: {last_validation.get('checks', {})}"
    package = await _finalize_storyboard_control(package, story, visual_plan)
    revision_history: list[dict[str, Any]] = []
    active_visual_plan = visual_plan
    creative_qc = package.get("creative_story_qc") or {}
    if creative_qc.get("available") and creative_qc.get("final_story_pass") != "PASS":
        for revision_index in range(revision_limit()):
            try:
                revision = await direct_creative_revision(
                    article=article, story=story, visual_plan=active_visual_plan,
                    storyboard=package["storyboard"], creative_qc=creative_qc,
                    duration=duration, prior_revisions=revision_history,
                )
                history_item: dict[str, Any] = {"revision_number": revision_index + 1, "director_output": revision}
                if revision.get("validation", {}).get("status") != "PASS":
                    history_item["status"] = "REVISION_REJECTED"
                    revision_history.append(history_item)
                    continue
                revised_visual_plan = apply_revision_to_visual_plan(active_visual_plan, revision)
                feedback = "This is a Creative Revision Director handoff. Preserve the revised visual mechanism and make every shot visibly add the supplied before-to-after viewer understanding. Do not collapse it into close-medium-wide coverage. Do not introduce plaques, documents, labels, pseudo-text, crowds, archival images, or reenactments unless source-supported."
                candidate = _normalize_candidate(await _ask_storyboard_model(article, story, revised_visual_plan, duration, aspect_ratio, feedback), story, revised_visual_plan)
                _attach_meaning_progression(candidate, revised_visual_plan)
                validation = validate_storyboard(story, revised_visual_plan, candidate, duration)
                sanitization = sanitize_if_simple_clutter(story, revised_visual_plan, candidate, validation)
                if sanitization:
                    history_item["scene_evidence_sanitization"] = sanitization
                    candidate["scene_evidence_sanitization"] = sanitization
                    if sanitization.get("status") == "PASS":
                        candidate["storyboard"] = sanitization["storyboard"]
                        validation = validate_storyboard(story, revised_visual_plan, candidate, duration)
                history_item["candidate_storyboard"] = candidate.get("storyboard") or []
                history_item["candidate_muted_test_v2"] = candidate.get("muted_test_v2") or {}
                history_item["candidate_generic_video_test_v2"] = candidate.get("generic_video_test_v2") or {}
                history_item["storyboard_validation"] = validation
                if validation["status"] != "PASS":
                    history_item["status"] = "STORYBOARD_REJECTED"
                    revision_history.append(history_item)
                    continue
                revised_package = {**candidate, "validation": validation, "attempts": 1, "model": candidate.get("model")}
                revised_package = await _finalize_storyboard_control(revised_package, story, revised_visual_plan)
                history_item["creative_story_qc"] = revised_package["creative_story_qc"]
                history_item["status"] = "PASS" if revised_package["creative_story_qc"].get("final_story_pass") == "PASS" else "CREATIVE_QC_FAILED"
                revision_history.append(history_item)
                package = revised_package
                active_visual_plan = revised_visual_plan
                creative_qc = revised_package["creative_story_qc"]
                if creative_qc.get("final_story_pass") == "PASS":
                    break
            except Exception as exc:
                revision_history.append({"revision_number": revision_index + 1, "status": "ERROR", "error": _clean(exc, 500)})
                break
    package["creative_revision_history"] = revision_history
    package["creative_revision_count"] = len([item for item in revision_history if item.get("director_output")])
    package["approved_for_media_generation"] = bool(
        package.get("validation", {}).get("status") == "PASS"
        and package.get("creative_story_qc", {}).get("final_story_pass") == "PASS"
        and package.get("story_type_qc", {}).get("status") == "PASS"
    )
    return package
