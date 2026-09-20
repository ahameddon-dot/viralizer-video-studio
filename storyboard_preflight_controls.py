from __future__ import annotations

import copy
import re
from typing import Any

from action_outcome_contract import result_object


POSITIVE_FIELDS = ("visual_description", "action", "environment", "composition", "foreground", "background")


def _clean(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _person_action_control(shots: list[dict[str, Any]], representation: dict[str, Any]) -> list[dict[str, Any]]:
    facts = [_clean(item, 700) for item in representation.get("visually_demonstrated") or [] if _clean(item)]
    if not shots or not facts:
        return shots
    fact = facts[0]
    physical_fact = re.split(r",\s*(?:surpassing|beating|setting|breaking)\b", fact, maxsplit=1, flags=re.I)[0]
    physical_fact = re.sub(r"^\s*[-–]\s*", "", physical_fact)
    physical_fact = re.sub(r"\b\d+(?:\.\d+)?\b", "", physical_fact)
    physical_fact = re.sub(r"\b(?:in|within)\s+(?:one|a)\s+(?:minute|second|hour)\b", "", physical_fact, flags=re.I)
    physical_fact = _clean(physical_fact, 260)
    count_claims = [_clean(item, 300) for item in representation.get("controlled_text_dependent") or [] if _clean(item)]
    prohibited = re.compile(r"\b(?:troph(?:y|ies)|medals?|medallions?|certificates?|scoreboards?|judges?|podiums?|record books?|record icons?|symbolic (?:tokens?|badges?|icons?)|record tokens?|competitor badges?|achievement badges?|award-like (?:frames?|props?))\b", re.I)
    for shot in shots:
        for field in POSITIVE_FIELDS:
            value = str(shot.get(field) or "")
            value = prohibited.sub("supported training detail", value)
            for claim in count_claims:
                value = value.replace(claim, "")
            value = re.sub(r"\b(?:ten|10)\s+(?:symbolic\s+)?(?:tokens?|badges?|icons?|objects?)\b", "", value, flags=re.I)
            shot[field] = _clean(value)
        for field in ("must_show", "continuity_requirements"):
            shot[field] = [
                _clean(item) for item in (shot.get(field) or [])
                if _clean(item) and not prohibited.search(_clean(item))
                and not any(claim.lower() in _clean(item).lower() for claim in count_claims)
            ]
    contract = representation.get("action_outcome_contract") or {}
    expected_result = _clean(contract.get("expected_visible_result"), 700)
    if len(shots) == 1:
        shots[0]["visual_description"] = f"The subject performs the distinctive supported feat: {physical_fact}"
        shots[0]["action"] = f"PHYSICAL_ACTION: perform {physical_fact}, then settle with the immediate physical outcome visible: {expected_result or physical_fact}."
    else:
        shots[0]["visual_description"] = f"The subject assumes the truthful starting position for this supported feat: {physical_fact}"
        shots[0]["action"] = f"PHYSICAL_ACTION: establish the distinctive objects, grip, stance, and body control required for {physical_fact}."
        for shot in shots[1:-1]:
            shot["visual_description"] = f"The subject performs the supported feat with visible intensity and control: {physical_fact}"
            shot["action"] = f"PHYSICAL_ACTION: perform {physical_fact} continuously and precisely."
        shots[-1]["visual_description"] = expected_result or physical_fact
        shots[-1]["action"] = f"CAUSE_EFFECT: complete {physical_fact}, then hold on the source-supported result: {expected_result or physical_fact}"
        shots[-1]["purpose"] = "HERO PAYOFF"
        shots[-1]["camera"] = "Steady close-up on the same hands and relevant action objects after the action completes."
        shots[-1]["composition"] = f"Close view of the source-supported result: {expected_result or result_object(contract)}"
        shots[-1]["foreground"] = expected_result or result_object(contract)
        shots[-1]["background"] = "restrained source-supported background with clean negative space"
        shots[-1]["must_show"] = list(dict.fromkeys((shots[-1].get("must_show") or []) + ([expected_result] if expected_result else [])))
        if expected_result:
            shots[-1]["start_frame"] = f"Post-action result state: {expected_result}"
            shots[-1]["end_frame"] = f"Stable proof of successful completion: {expected_result}"
    for shot in shots:
        shot["action_outcome_contract"] = dict(contract)
        shot["must_avoid"] = list(dict.fromkeys((shot.get("must_avoid") or []) + (representation.get("forbidden_inventions") or [])))
        shot["must_avoid"] = list(dict.fromkeys(shot["must_avoid"] + ["symbolic badges", "achievement icons", "podiums"]))
    return shots


def _event_temporal_control(shots: list[dict[str, Any]], locks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not shots:
        return shots
    future = [item for item in locks if item.get("temporal_status") in {"PLANNED_FUTURE", "PROPOSED", "EXPECTED"}]
    if not future:
        return shots
    future_fact = _clean(future[0].get("element"), 700)
    past = [item for item in locks if item.get("temporal_status") == "PAST_CONFIRMED"]
    collaboration = [item for item in locks if item.get("semantic_role") == "COLLABORATION_ELEMENT"]
    completed = re.compile(r"\b(?:successfully )?(?:launched|deployed|completed|finished|operational|in orbit|arrived)\b", re.I)
    if past:
        past_fact = _clean(past[0].get("element"), 700)
        shots[0]["visual_description"] = f"Past-confirmed baseline shown literally from the source evidence: {past_fact}"
        shots[0]["action"] = f"TEMPORAL_CONTRAST: establish the completed earlier milestone as the factual baseline: {past_fact}"
        shots[0]["purpose"] = "CONTEXT"
    future_seen = False
    for shot in shots:
        positive = " ".join(str(shot.get(field) or "") for field in POSITIVE_FIELDS)
        if completed.search(positive) and not any(
            _clean(item.get("element"), 700).lower() in positive.lower() for item in past
        ):
            shot["visual_description"] = f"Preparatory work continues for the source-confirmed future development: {future_fact}"
            shot["action"] = f"PROCESS_PROGRESSION: show grounded assembly, testing, or collaboration still in progress; the planned event has not happened: {future_fact}"
            shot["environment"] = "a source-supported working or laboratory context, without fabricated launch imagery"
            shot["must_avoid"] = list(dict.fromkeys((shot.get("must_avoid") or []) + [
                "completed launch", "deployed future system", "future system already operational",
            ]))
            future_seen = True
    if not future_seen:
        target = shots[-1]
        target["visual_description"] = f"Preparatory work continues for the source-confirmed future development: {future_fact}"
        target["action"] = f"PROCESS_PROGRESSION: show the planned work still being assembled, tested, or coordinated; do not depict completion: {future_fact}"
    if past:
        shots[0]["source_support"] = list(dict.fromkeys((shots[0].get("source_support") or []) + [_clean(past[0].get("element"), 700)]))
    if collaboration and len(shots) > 1:
        collaboration_fact = _clean(collaboration[0].get("element"), 700)
        shots[-1]["source_support"] = list(dict.fromkeys((shots[-1].get("source_support") or []) + [collaboration_fact]))
        shots[-1]["visual_description"] = _clean(f"{shots[-1].get('visual_description')} Preserve the source-supported collaboration through researchers working together: {collaboration_fact}", 1200)
        shots[-1]["action"] = _clean(f"{shots[-1].get('action')} Researchers visibly coordinate the preparatory work together.", 1200)
    return shots


def enforce_storyboard_preflight_controls(storyboard: list[dict[str, Any]], story: dict[str, Any], visual_plan: dict[str, Any]) -> list[dict[str, Any]]:
    shots = copy.deepcopy(storyboard)
    story_type = str(visual_plan.get("story_type") or (story.get("visualizability_analysis") or {}).get("story_type") or "").upper()
    if story_type == "PERSON_ACTION":
        shots = _person_action_control(shots, visual_plan.get("achievement_representation") or {})
    elif story_type in {"EVENT", "PROCESS", "TRANSFORMATION"} and visual_plan.get("source_evidence_locks"):
        shots = _event_temporal_control(shots, visual_plan.get("source_evidence_locks") or [])
    return shots
