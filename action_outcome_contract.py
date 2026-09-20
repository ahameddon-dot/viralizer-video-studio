"""Evidence-bound action/outcome contracts for PERSON_ACTION stories."""
from __future__ import annotations

import re
from typing import Any


def _clean(value: Any, limit: int = 900) -> str:
    return " ".join(str(value or "").split())[:limit].strip(" -")


def build_action_outcome_contract(source_facts: list[Any]) -> dict[str, Any]:
    """Build a visible result contract only when the evidence supplies one."""
    facts = [_clean(item) for item in source_facts if _clean(item)]
    ranked = sorted(
        facts,
        key=lambda item: (
            bool(re.search(r"\b(?:held|holding|carried|balanced)\b", item, re.I)),
            bool(re.search(r"\b(?:delivered|completed|performed|finished|surpassed)\b", item, re.I)),
            bool(re.search(r"\b(?:egg|glass|fragile|unbroken|intact)\w*\b", item, re.I)),
            len(item),
        ),
        reverse=True,
    )
    fact = ranked[0] if ranked else ""
    action_match = re.search(
        r"((?:held|holding|carried|balanced)\b.{0,180}?(?:delivered|completed|performed|finished)\b.{0,180}?)(?:,|\.|;|\bsurpassing\b|\bbeating\b)",
        fact,
        re.I,
    )
    action = _clean(action_match.group(1) if action_match else fact, 500)
    held_match = re.search(r"\b(?:held|holding|carried|balanced)\s+(.{1,80}?)(?:\s+in\s+|\s+while\s+|\s+and\s+|,|\.)", fact, re.I)
    relevant_object = _clean(held_match.group(1) if held_match else "", 120)
    fragile = bool(re.search(r"\b(?:egg|glass|fragile|unbroken|intact)\w*\b", fact, re.I))
    completed = bool(re.search(r"\b(?:delivered|completed|performed|finished|surpassed|achieved)\b", fact, re.I))
    held = bool(re.search(r"\b(?:held|holding|carried|balanced)\b", fact, re.I))
    visualizable = bool(action and completed and held and relevant_object)
    if visualizable:
        result = f"After the supported action completes, the same {relevant_object} remain visibly held in the performer's hands"
        if fragile:
            result += " with no visible breakage"
        result += "."
    else:
        result = ""
    return {
        "action": action,
        "expected_visible_result": result,
        "result_source_support": [fact] if visualizable else [],
        "result_visualizable": visualizable,
        "result_shot_required": visualizable,
    }


def result_object(contract: dict[str, Any]) -> str:
    result = _clean(contract.get("expected_visible_result"), 500)
    match = re.search(r"\bthe same\s+(.{1,100}?)\s+remain\b", result, re.I)
    return _clean(match.group(1) if match else "relevant action object", 120)


def build_result_state_reference(contract: dict[str, Any], must_avoid: list[Any]) -> dict[str, Any]:
    if not contract.get("result_shot_required"):
        return {}
    expected = _clean(contract.get("expected_visible_result"), 700)
    return {
        "exact_relevant_object": result_object(contract),
        "post_action_state": expected,
        "must_remain_unchanged": [
            "the same performer identity and anatomy",
            "the same relevant action object and object count",
            "wardrobe, lighting, and spatial continuity",
        ],
        "successful_completion_proof": expected,
        "must_not_appear": list(dict.fromkeys(str(item) for item in must_avoid if str(item).strip())),
    }
