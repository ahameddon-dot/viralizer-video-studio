from __future__ import annotations

import json
import re
from typing import Any

from action_outcome_contract import build_action_outcome_contract


def _text(storyboard: list[dict[str, Any]]) -> str:
    positive = []
    for shot in storyboard:
        positive.append({
            key: shot.get(key)
            for key in ("visual_description", "action", "environment", "composition", "foreground", "background", "must_show")
        })
    return json.dumps(positive, ensure_ascii=False).lower()


def evaluate_story_type_qc(storyboard: list[dict[str, Any]], story: dict[str, Any], visual_plan: dict[str, Any], text_routing: dict[str, Any] | None = None) -> dict[str, Any]:
    story_type = str(visual_plan.get("story_type") or (story.get("visualizability_analysis") or {}).get("story_type") or "OTHER").upper()
    text = _text(storyboard)
    checks: dict[str, bool] = {}
    if story_type == "PERSON_ACTION":
        representation = visual_plan.get("achievement_representation") or {}
        contract = visual_plan.get("action_outcome_contract") or representation.get("action_outcome_contract") or story.get("action_outcome_contract") or {}
        if not contract:
            legacy_facts = list(representation.get("visually_demonstrated") or [])
            legacy_facts.extend(
                " ".join(str(shot.get(key) or "") for key in ("visual_description", "action"))
                for shot in storyboard
            )
            # Backward compatibility for already-approved plans created before the
            # explicit contract field existed. New plans receive the contract at
            # story analysis; old plans are upgraded deterministically for QC.
            contract = build_action_outcome_contract([". ".join(legacy_facts), *legacy_facts])
        visual_facts = " ".join(representation.get("visually_demonstrated") or []).lower()
        fact_tokens = {t for t in re.findall(r"[a-z]{5,}", visual_facts) if t not in {"record", "records", "achievement", "completed"}}
        forbidden = ("trophy", "medal", "badge", "icon", "certificate", "scoreboard", "record book", "judges", "podium")
        payoff = storyboard[-1] if storyboard else {}
        payoff_text = " ".join(
            str(payoff.get(key) or "")
            for key in ("visual_description", "action", "foreground", "composition", "start_frame", "end_frame")
        ).lower()
        result_terms = {token for token in re.findall(r"[a-z]{4,}", str(contract.get("expected_visible_result") or "").lower()) if token not in {"after", "same", "with", "visible", "visibly", "remain", "hands"}}
        result_required = bool(contract.get("result_shot_required"))
        checks = {
            "distinctive_action_present": bool(fact_tokens and any(token in text for token in fact_tokens)),
            "cause_effect_present": any(term in text for term in ("respond", "result", "remains", "intact", "lands", "falls", "completes", "after")),
            "non_generic_payoff": not any(term in text and term not in visual_facts for term in forbidden),
            "count_not_forced_into_generated_objects": not bool(re.search(r"(?:show|display|arrange|surround).{0,40}\b\d+\b.{0,40}(?:troph|medal|certificate|record book)", text)),
            "action_outcome_contract_present": bool(contract.get("action")) and (not result_required or bool(contract.get("result_source_support"))),
            "observable_result_payoff": not result_required or bool(result_terms and any(term in payoff_text for term in result_terms) and any(term in payoff_text for term in ("result", "after", "remain", "intact", "unbroken", "completes"))),
        }
    elif story_type == "PRODUCT":
        routing = text_routing or {}
        generated_dependency = any(item.get("route") not in {"SOURCE_UI_TEXT", "CONTROLLED_OVERLAY_TEXT"} for item in routing.get("routes") or [])
        checks = {
            "product_identity_present": bool(visual_plan.get("core_visual_subject")),
            "new_development_present": bool(story.get("new_development")),
            "supported_state_or_interface_change": any(term in text for term in ("interface", "control", "layout", "state", "before", "after", "change", "remain", "stay")),
            "no_generated_text_dependency": not generated_dependency,
        }
    elif story_type in {"EVENT", "PROCESS", "TRANSFORMATION"} and visual_plan.get("source_evidence_locks"):
        locks = visual_plan.get("source_evidence_locks") or []
        planned = [item for item in locks if item.get("temporal_status") in {"PLANNED_FUTURE", "PROPOSED", "EXPECTED"}]
        future_shown_completed = False
        for shot in storyboard:
            shot_text = " ".join(str(shot.get(key) or "") for key in ("visual_description", "action", "environment")).lower()
            future_cue = bool(re.search(r"\b(?:planned|next year|will launch|future|upcoming|proposed|expected)\b", shot_text))
            completed_cue = bool(re.search(r"\b(?:successfully launched|completed|finished|deployed|already operational|in orbit)\b", shot_text))
            explicit_noncompletion = bool(re.search(r"\b(?:not happened|do not depict completion|still being|continues|preparator)\w*\b", shot_text))
            if future_cue and completed_cue and not explicit_noncompletion:
                future_shown_completed = True
        role_checks = []
        for role in {item.get("semantic_role") for item in locks if item.get("evidence_lock") and item.get("semantic_role") != "UNSPECIFIED"}:
            patterns = {
                "ORIGINAL_SATELLITE": r"\b(?:original|first|earlier|previous|existing|1u|compact|nanosat)\w*\b",
                "NEW_SATELLITE": r"\b(?:new|next|planned|upcoming|3u|larger)\w*\b",
                "ASSEMBLY_COMPONENT": r"\b(?:assembl|component|panel|circuit|hardware|module)\w*\b",
                "PAYLOAD": r"\bpayload\w*\b",
                "LAUNCH_CONTEXT": r"\b(?:launch|orbit|rocket|deploy|ground station)\w*\b",
                "LAB_CONTEXT": r"\b(?:lab|laboratory|workbench|research)\w*\b",
                "COLLABORATION_ELEMENT": r"\b(?:collaborat|partner|team|engineer|researcher|university|joint)\w*\b",
                "SCALE_REFERENCE": r"\b(?:scale|size|dimension|larger|smaller|compar)\w*\b",
            }
            role_checks.append(bool(re.search(patterns.get(role, r"$^"), text)))
        checks = {
            "temporal_progression_present": any(term in text for term in ("process", "progress", "assemble", "prepare", "planned", "before", "after", "transition")),
            "source_locked_elements_preserved": all(role_checks) if role_checks else True,
            "planned_not_shown_as_completed": not (planned and future_shown_completed),
            "causal_clarity": any(term in text for term in ("because", "causes", "leads", "responds", "then", "after", "result", "progress")),
        }
    else:
        checks = {"applicable": True}
    return {"story_type": story_type, "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
