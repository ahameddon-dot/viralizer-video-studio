from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from visual_specificity_analyzer import (
    RAW_ARTICLE_SPECIFICITY_THRESHOLD,
    evaluate_evidence_relative_specificity,
)
from story_type_qc import evaluate_story_type_qc


def _clean(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _score(value: Any) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return 0


def creative_qc_authority(story: dict[str, Any], visual_plan: dict[str, Any]) -> dict[str, Any]:
    visualizability = visual_plan.get("visualizability_analysis") or story.get("visualizability_analysis") or {}
    narration_gap = visual_plan.get("narration_gap") or visualizability.get("narration_gap") or {}
    allocation = visual_plan.get("editorial_channel_allocation") or visual_plan.get("editorial_allocation") or story.get("editorial_channel_allocation") or story.get("editorial_allocation") or {}
    visual_responsibilities = allocation.get("visual_channel") or narration_gap.get("viewer_should_understand_visually") or visualizability.get("visualizable_facts") or []
    narration_responsibilities = allocation.get("narration_channel") or narration_gap.get("narration_must_explain") or visualizability.get("narration_dependent_meanings") or []
    text_responsibilities = allocation.get("text_channel") or []
    achievement = visual_plan.get("achievement_representation") or story.get("achievement_representation") or {}
    return {
        "core_message": _clean(story.get("core_message"), 1200),
        "new_development": _clean(story.get("new_development"), 1200),
        "viewer_takeaway": _clean(story.get("viewer_takeaway"), 1200),
        "visual_message": _clean(visual_plan.get("visual_message"), 1200),
        "core_visual_subject": _clean(visual_plan.get("core_visual_subject"), 600),
        "factual_boundaries": story.get("factual_boundaries") or [],
        "story_type": visual_plan.get("story_type") or visualizability.get("story_type") or "OTHER",
        "primary_visual_story": visualizability.get("primary_visual_story") or visual_plan.get("visual_message"),
        "viewer_should_understand_visually": visual_responsibilities,
        "narration_must_explain": narration_responsibilities,
        "controlled_text_must_explain": text_responsibilities,
        "editorial_allocation": allocation,
        "qc_stage": "VISUAL_PRODUCTION_QC",
        "visual_semantic_coverage_target": narration_gap.get("visual_semantic_coverage_target", 70),
        "narration_gap_acceptable": bool(narration_gap.get("narration_gap_acceptable", True)),
        "facts_not_required_visually": ["exact date", "auction price", "designer name", "specific historical quotations", *narration_responsibilities, *text_responsibilities],
        "visual_specificity_analysis": visual_plan.get("visual_specificity_analysis") or visualizability.get("visual_specificity_analysis") or {},
        "achievement_representation": achievement,
        "action_outcome_contract": visual_plan.get("action_outcome_contract") or story.get("action_outcome_contract") or achievement.get("action_outcome_contract") or {},
        "source_evidence_locks": visual_plan.get("source_evidence_locks") or [],
        "article_visual_kernel": visual_plan.get("article_visual_kernel") or story.get("article_visual_kernel") or {},
        "selected_visual_mechanism": visual_plan.get("selected_visual_mechanism") or "",
        "article_visual_relation": visual_plan.get("article_visual_relation") or {},
    }


def creative_qc_instruction(kind: str) -> str:
    return f"""You are Viralizer's Human-Like Story Comprehension QC. Evaluate the {kind} as if you know NOTHING about the headline or article and receive no narration, captions, labels, or explanatory text. First state the story an ordinary viewer would infer from only the supplied visual sequence. Compare that inference primarily with primary_visual_story and viewer_should_understand_visually. Do not require narration_must_explain meanings to be independently inferred from muted visuals when narration_gap_acceptable is true. Do not pass merely because the correct object, environment, continuity, motion, or technical quality appears. Camera distance or lighting changing by itself is not narrative progression. Story-type-appropriate context reveal, relational reveal, environmental recontextualization, process progression, temporal contrast, scale reveal, cause/effect, state change, or physical action can add meaning. For every shot, state what genuinely new meaning it adds. Distinguish visual continuity from narrative progression. Penalize unsupported symbolic inventions; metaphor is acceptable only when necessary, clearly editorial, subject-connected, non-misleading, and materially improves comprehension. Evaluate how the environment changes meaning around the subject. Explicitly detect generic luxury advertisement, product showcase, fashion editorial, or museum-exhibition interpretation. Detect informational plaques, documents, labels, wall panels, pseudo-text, or other fake evidence even when unreadable.

Return only JSON with:
viewer_inferred_story (string),
subject_clarity (0-100),
story_progression (0-100),
shot_progression (array of objects: shot_id, new_meaning, adds_new_meaning boolean),
visual_semantic_coverage (object containing overall_score 0-100, communicated array, partial array, weak_or_missing array),
article_specificity (0-100),
visual_impact (0-100),
visual_continuity (0-100),
narrative_progression (0-100),
environmental_storytelling (0-100),
generic_ad_risk (0-100 where 100 is severe),
fake_information_panel_detected (boolean),
fake_information_panel_detail (string),
article_relation (0-100),
genericity (0-100 where 100 is severe),
visual_evidence_usage (0-100),
story_type_match (0-100),
model_final_story_pass (PASS or FAIL),
muted_primary_visual_story_pass (PASS or FAIL),
narration_gap_acceptable (boolean),
failure_reasons (array of concise strings).

Also return visual_channel_coverage (0-100), narration_channel_coverage (use null at visual-production stage), text_channel_coverage (use null at visual-production stage), final_multimodal_coverage (use null at visual-production stage), and action_result_qc containing ACTION_CLEAR, ACTION_ARTICLE_SPECIFIC, RESULT_VISIBLE, RESULT_MATCHES_EVIDENCE, CAUSE_EFFECT_CLEAR, PAYOFF_NON_GENERIC, each exactly PASS or FAIL when action_outcome_contract applies and NOT_APPLICABLE otherwise.

This is STAGE 1 VISUAL PRODUCTION QC. Evaluate only editorial_allocation.visual_channel, technical execution, the action/result contract, source evidence, continuity, and factual safety. Compare viewer_inferred_story directly with article_visual_kernel.visual_story_sentence, not the headline or narration-dependent facts. A polished sequence that can only be inferred as 'people demonstrating technology', 'analysts looking at code', or another category-level scene must receive low article_relation, high genericity, and FAIL. Do not fail visuals for facts assigned to narration_channel, text_channel, controlled_text_dependent, or facts_not_required_visually. Those channels are intentionally deferred to final multimodal QC. The primary allocated visual story must survive visually. Exact names, dates, statistics, opponent identity/context, record titles, and achievement counts do not need to appear when assigned to narration or controlled text. For PERSON_ACTION, require the distinctive supported physical action, its readable cause-and-effect, and the expected visible result; an action without its required result fails RESULT_VISIBLE. Reject generic award poses and symbolic badges/icons/trophies as substitutes. For PRODUCT, require the supported new development or old/new state and reject dependency on model-generated lettering; deterministic overlay routing is valid. For EVENT or PROCESS, require supported technical elements, temporal progression, causal clarity, and strict preservation of planned-versus-completed status. Evaluate only visual identity anchors assigned to the visual channel. Be strict and candid when a technically attractive sequence merely looks like generic category footage."""


def _qc_status(value: Any, default: str = "FAIL") -> str:
    status = str(value or default).upper()
    return status if status in {"PASS", "FAIL", "NOT_APPLICABLE"} else default


def _responsibility_overlap(value: Any, responsibilities: list[Any]) -> bool:
    value_tokens = {token for token in re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(token) > 3 or token.isdigit()}
    if not value_tokens:
        return False
    for item in responsibilities:
        item_tokens = {token for token in re.findall(r"[a-z0-9]+", str(item or "").lower()) if len(token) > 3 or token.isdigit()}
        if item_tokens and len(value_tokens & item_tokens) / max(1, min(len(value_tokens), len(item_tokens))) >= 0.35:
            return True
    return False


def normalize_creative_qc(
    result: dict[str, Any],
    coverage_target: int = 70,
    narration_gap_acceptable: bool = True,
    specificity_analysis: dict[str, Any] | None = None,
    storyboard: list[dict[str, Any]] | None = None,
    authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(result)
    result = dict(result)
    result.setdefault("article_relation", result.get("article_specificity", 0))
    result.setdefault("genericity", result.get("generic_ad_risk", 100))
    result.setdefault("visual_evidence_usage", (result.get("visual_semantic_coverage") or {}).get("overall_score", 0))
    result.setdefault("story_type_match", result.get("article_specificity", 0))
    score_fields = (
        "subject_clarity", "story_progression", "article_specificity", "visual_impact",
        "visual_continuity", "narrative_progression", "environmental_storytelling", "generic_ad_risk",
        "article_relation", "genericity", "visual_evidence_usage", "story_type_match",
    )
    for field in score_fields:
        normalized[field] = _score(result.get(field))
    coverage = result.get("visual_semantic_coverage") if isinstance(result.get("visual_semantic_coverage"), dict) else {}
    normalized["visual_semantic_coverage"] = {
        "overall_score": _score(coverage.get("overall_score")),
        "communicated": [str(item) for item in coverage.get("communicated", []) if str(item).strip()],
        "partial": [str(item) for item in coverage.get("partial", []) if str(item).strip()],
        "weak_or_missing": [str(item) for item in coverage.get("weak_or_missing", []) if str(item).strip()],
    }
    visual_channel_score = _score(result.get("visual_channel_coverage", normalized["visual_semantic_coverage"]["overall_score"]))
    normalized["visual_channel_coverage"] = visual_channel_score
    normalized["narration_channel_coverage"] = result.get("narration_channel_coverage")
    normalized["text_channel_coverage"] = result.get("text_channel_coverage")
    normalized["final_multimodal_coverage"] = result.get("final_multimodal_coverage")
    normalized["coverage_stage"] = "VISUAL_PRODUCTION_QC"
    normalized["viewer_inferred_story"] = _clean(result.get("viewer_inferred_story"), 1600)
    normalized["shot_progression"] = result.get("shot_progression") if isinstance(result.get("shot_progression"), list) else []
    normalized["fake_information_panel_detected"] = bool(result.get("fake_information_panel_detected"))
    reasons = [str(item) for item in result.get("failure_reasons", []) if str(item).strip()]
    raw_specificity = normalized["article_specificity"]
    primary_visual_story_pass = visual_channel_score >= max(0, min(100, int(coverage_target)))
    if specificity_analysis and storyboard is not None:
        specificity_result = evaluate_evidence_relative_specificity(
            storyboard,
            specificity_analysis,
            raw_specificity,
            primary_visual_story_pass=primary_visual_story_pass,
            generic_ad_risk=normalized["generic_ad_risk"],
        )
    else:
        specificity_result = {
            "article_specificity_raw": raw_specificity,
            "article_specificity_relative_to_available_evidence": raw_specificity,
            "specificity_classification": "LEGACY_RAW_THRESHOLD",
            "visual_identity_anchors_used": [],
            "visual_identity_anchors_missed": [],
            "available_visual_anchors_fully_used": False,
            "identity_narration_required": False,
            "specificity_gate_pass": raw_specificity >= RAW_ARTICLE_SPECIFICITY_THRESHOLD,
            "decision": "VISUAL_STORY_APPROVED" if raw_specificity >= RAW_ARTICLE_SPECIFICITY_THRESHOLD else "VISUAL_STORY_REQUIRES_REVISION",
            "raw_specificity_threshold_preserved": RAW_ARTICLE_SPECIFICITY_THRESHOLD,
        }
    normalized.update(specificity_result)
    checks = {
        "subject_clear": normalized["subject_clarity"] >= 65,
        "story_progresses": normalized["story_progression"] >= 70 and normalized["narrative_progression"] >= 70,
        "primary_visual_story_covered": primary_visual_story_pass,
        "article_specific": specificity_result["specificity_gate_pass"],
        "environment_adds_meaning": normalized["environmental_storytelling"] >= 60,
        "not_generic_ad": normalized["generic_ad_risk"] <= 40,
        "no_fake_information_panel": not normalized["fake_information_panel_detected"],
        "article_relation": normalized["article_relation"] >= 65,
        "genericity_kill_switch": normalized["genericity"] <= 40,
        "visual_evidence_used": normalized["visual_evidence_usage"] >= 60,
        "story_type_match": normalized["story_type_match"] >= 60,
        "each_later_shot_adds_meaning": all(bool(item.get("adds_new_meaning")) for item in normalized["shot_progression"][1:] if isinstance(item, dict)) if len(normalized["shot_progression"]) > 1 else True,
    }
    if not checks["story_progresses"]:
        reasons.append("The visual sequence does not add enough new meaning from shot to shot.")
    normalized["muted_primary_visual_story_pass"] = str(result.get("muted_primary_visual_story_pass") or result.get("model_final_story_pass") or "FAIL").upper()
    normalized["narration_gap_acceptable"] = bool(result.get("narration_gap_acceptable", narration_gap_acceptable))
    if not checks["primary_visual_story_covered"]:
        reasons.append("The primary visualizable story is not sufficiently communicated by the visuals alone.")
    if not checks["not_generic_ad"]:
        reasons.append("The sequence risks reading as a generic advertisement or exhibition showcase.")
    if not checks["no_fake_information_panel"]:
        reasons.append("A generated information panel, plaque, document, label, or pseudo-text element is visible.")
    normalized["checks"] = checks
    normalized["failure_reasons"] = list(dict.fromkeys(reasons))
    normalized["model_final_story_pass"] = str(result.get("model_final_story_pass") or "FAIL").upper()
    achievement_allocation_override = False
    story_type_result: dict[str, Any] = {"status": "NOT_APPLICABLE"}
    if (
        authority
        and storyboard is not None
    ):
        story_type_result = evaluate_story_type_qc(
            storyboard,
            {
                "visualizability_analysis": {"story_type": authority.get("story_type")},
                "new_development": authority.get("new_development") or authority.get("core_message"),
            },
            {
                "story_type": authority.get("story_type"),
                "core_visual_subject": authority.get("core_visual_subject"),
                "achievement_representation": authority.get("achievement_representation") or {},
                "source_evidence_locks": authority.get("source_evidence_locks") or [],
            },
        )
        contract = authority.get("action_outcome_contract") or {}
        raw_action_qc = result.get("action_result_qc") if isinstance(result.get("action_result_qc"), dict) else result
        action_fields = ("ACTION_CLEAR", "ACTION_ARTICLE_SPECIFIC", "RESULT_VISIBLE", "RESULT_MATCHES_EVIDENCE", "CAUSE_EFFECT_CLEAR", "PAYOFF_NON_GENERIC")
        action_required = bool(str(authority.get("story_type") or "").upper() == "PERSON_ACTION" and contract.get("result_shot_required"))
        action_result_qc = {
            field: _qc_status(raw_action_qc.get(field), "PASS" if not action_required or story_type_result.get("status") == "PASS" and not reasons else "FAIL")
            for field in action_fields
        }
        normalized["action_result_qc"] = action_result_qc
        checks["action_result"] = not action_required or all(value == "PASS" for value in action_result_qc.values())
        if action_required and checks["action_result"]:
            # In a PERSON_ACTION story the source-supported physical action and
            # observable result may carry the complete visual meaning. A neutral
            # environment is intentional and must not be forced to invent context.
            checks["environment_adds_meaning"] = True
        achievement_allocation_override = bool(
            str(authority.get("story_type") or "").upper() == "PERSON_ACTION"
            and (authority.get("achievement_representation") or {}).get("controlled_text_dependent")
            and
            story_type_result.get("status") == "PASS"
            and normalized["visual_semantic_coverage"]["overall_score"] >= max(0, int(coverage_target) - 5)
            and normalized["story_progression"] >= 70
            and normalized["narrative_progression"] >= 70
            and normalized["generic_ad_risk"] <= 40
        )
        if achievement_allocation_override:
            checks["primary_visual_story_covered"] = True
            normalized["muted_primary_visual_story_pass"] = "PASS"
            normalized["failure_reasons"] = [
                reason for reason in normalized["failure_reasons"]
                if not any(term in reason.lower() for term in ("record count", "10 world", "numeric", "opponent", "competitor", "rival", "subject’s name", "subject's name"))
            ]
    allocation = authority.get("editorial_allocation") if authority else {}
    deferred = list((allocation or {}).get("narration_channel") or []) + list((allocation or {}).get("text_channel") or [])
    if deferred:
        normalized["failure_reasons"] = [reason for reason in normalized["failure_reasons"] if not _responsibility_overlap(reason, deferred)]
    missed = normalized.get("visual_identity_anchors_missed") or []
    missed_visual = [item for item in missed if not _responsibility_overlap(item, deferred)]
    normalized["visual_identity_anchors_missed_for_visual_channel"] = missed_visual
    channel_specificity_pass = bool(allocation and not missed_visual and checks.get("primary_visual_story_covered") and checks.get("action_result", True))
    structured_specificity_pass = bool(
        story_type_result.get("status") == "PASS"
        and checks["primary_visual_story_covered"]
        and (raw_specificity >= 40 or channel_specificity_pass)
        and normalized["story_progression"] >= 70
        and normalized["narrative_progression"] >= 70
        and normalized["generic_ad_risk"] <= 40
    )
    if structured_specificity_pass and not checks["article_specific"]:
        checks["article_specific"] = True
        normalized["specificity_gate_pass"] = True
        normalized["specificity_classification"] = "STRUCTURED_STORY_TYPE_SPECIFICITY"
        normalized["article_specificity_relative_to_available_evidence"] = 100
        normalized["decision"] = "VISUAL_STORY_APPROVED"
    normalized["structured_specificity_override"] = structured_specificity_pass
    normalized["channel_specificity_override"] = channel_specificity_pass
    normalized["achievement_allocation_override"] = achievement_allocation_override
    visual_stage_override = bool(
        allocation and checks.get("primary_visual_story_covered") and checks.get("action_result", True)
        and normalized["story_progression"] >= 70 and normalized["narrative_progression"] >= 70
        and normalized["generic_ad_risk"] <= 40 and not normalized["failure_reasons"]
    )
    normalized["visual_stage_channel_override"] = visual_stage_override
    model_gate = normalized["model_final_story_pass"] == "PASS" or achievement_allocation_override or visual_stage_override
    normalized["final_story_pass"] = "PASS" if all(checks.values()) and model_gate and normalized["muted_primary_visual_story_pass"] == "PASS" and normalized["narration_gap_acceptable"] else "FAIL"
    return normalized


def _response_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    return "".join(str(part.get("text") or "") for item in data.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text")


async def _ask(parts: list[dict[str, Any]], authority: dict[str, Any], storyboard: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return {"available": False, "status": "UNAVAILABLE", "reason": "OPENAI_API_KEY is not configured", "final_story_pass": "UNAVAILABLE"}
    payload = {
        "model": os.getenv("OPENAI_QC_MODEL", "gpt-4.1-mini"),
        "input": [{"role": "user", "content": parts}],
        "text": {"format": {"type": "json_object"}},
    }
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"}, json=payload)
        if response.is_error:
            return {"available": False, "status": "UNAVAILABLE", "reason": f"Creative QC request failed ({response.status_code})", "final_story_pass": "UNAVAILABLE"}
        result = normalize_creative_qc(
            json.loads(_response_text(response.json())),
            int(authority.get("visual_semantic_coverage_target") or 70),
            bool(authority.get("narration_gap_acceptable", True)),
            authority.get("visual_specificity_analysis") or {},
            storyboard,
            authority,
        )
        result.update(available=True, status="COMPLETE", model=payload["model"])
        return result
    except Exception as exc:
        return {"available": False, "status": "UNAVAILABLE", "reason": _clean(exc, 500), "final_story_pass": "UNAVAILABLE"}


async def score_storyboard_creative_qc(storyboard: list[dict[str, Any]], story: dict[str, Any], visual_plan: dict[str, Any]) -> dict[str, Any]:
    authority = creative_qc_authority(story, visual_plan)
    visual_only = [{"shot_id": item.get("shot_id"), "purpose": item.get("purpose"), "visual_description": item.get("visual_description"), "action": item.get("action"), "environment": item.get("environment"), "composition": item.get("composition"), "transition_in": item.get("transition_in"), "transition_out": item.get("transition_out"), "controlled_overlay_text": item.get("controlled_overlay_text") or []} for item in storyboard]
    parts = [{"type": "input_text", "text": creative_qc_instruction("storyboard") + "\nAUTHORITY:\n" + json.dumps(authority, ensure_ascii=False) + "\nVISUAL-ONLY STORYBOARD:\n" + json.dumps(visual_only, ensure_ascii=False)}]
    return await _ask(parts, authority, storyboard)


def extract_story_frames(path: Path, maximum: int = 12) -> list[bytes]:
    with tempfile.TemporaryDirectory() as temp:
        pattern = str(Path(temp) / "story-%02d.jpg")
        result = subprocess.run(["ffmpeg", "-y", "-i", str(path), "-vf", "fps=1,scale=640:-2", "-frames:v", str(maximum), pattern], capture_output=True)
        if result.returncode:
            return []
        return [item.read_bytes() for item in sorted(Path(temp).glob("story-*.jpg"))]


async def score_whole_video_creative_qc(
    path: Path,
    story: dict[str, Any],
    visual_plan: dict[str, Any],
    storyboard: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    frames = extract_story_frames(path)
    if not frames:
        return {"available": False, "status": "UNAVAILABLE", "reason": "No final-video frames could be extracted", "final_story_pass": "UNAVAILABLE"}
    authority = creative_qc_authority(story, visual_plan)
    parts: list[dict[str, Any]] = [{"type": "input_text", "text": creative_qc_instruction("complete final video") + "\nAUTHORITY:\n" + json.dumps(authority, ensure_ascii=False) + f"\nThe following {len(frames)} frames are chronological samples from the complete assembled video."}]
    for index, frame in enumerate(frames, 1):
        parts.append({"type": "input_text", "text": f"Chronological frame {index} of {len(frames)}"})
        parts.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(frame).decode("ascii")})
    return await _ask(parts, authority, storyboard)
