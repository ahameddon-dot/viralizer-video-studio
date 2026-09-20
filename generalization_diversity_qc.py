"""Cross-story routing and diversity checks for article-driven storyboards."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any


ROUTE_PERSON_ACTION = "PERSON_ACTION"
ROUTE_PRODUCT_TECH = "PRODUCT_TECH"
ROUTE_EVENT_PROCESS = "EVENT_PROCESS"
GENERALIZATION_ROUTES = {ROUTE_PERSON_ACTION, ROUTE_PRODUCT_TECH, ROUTE_EVENT_PROCESS}
PRODUCTION_SPECIAL_CASE_PATTERNS = (
    r"\bDiana\b", r"\bRevenge Dress\b", r"\bFatima Naseem\b",
    r"\bMinuteMirror\b", r"\bGuideAutoWeb\b", r"\bnanosatellite\b",
    r"\bworld records\b",
)


def _clean(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _tokens(value: Any) -> set[str]:
    stop = {
        "with", "from", "that", "this", "into", "through", "their", "story", "visual",
        "article", "subject", "camera", "scene", "same", "shot", "shows", "showing",
    }
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9'-]+", str(value or ""))
        if len(token) > 3 and token.lower() not in stop
    }


def route_story(story: dict[str, Any], visualizability: dict[str, Any] | None = None) -> str:
    """Map the existing story taxonomy into the three validation families."""
    visualizability = visualizability or story.get("visualizability_analysis") or {}
    story_type = _clean(visualizability.get("story_type") or story.get("story_type"), 80).upper()
    text = " ".join(
        _clean(story.get(key), 1600)
        for key in ("what_happened", "new_development", "core_message", "viewer_takeaway")
    ).lower()
    if story_type == "PERSON_ACTION":
        return ROUTE_PERSON_ACTION
    if story_type in {"EVENT", "PROCESS", "TRANSFORMATION"}:
        return ROUTE_EVENT_PROCESS
    if re.search(
        r"\b(?:space mission|scientific mission|construction|manufactur|assembly|progression|eruption|"
        r"storm|launch sequence|changes? over time|completed?|built|formed)\b",
        text,
    ):
        return ROUTE_EVENT_PROCESS
    if story_type == "PRODUCT" or re.search(
        r"\b(?:device|robot|vehicle|machine|interface|hardware|software|chip|processor|"
        r"prototype|technology|platform)\b",
        text,
    ):
        return ROUTE_PRODUCT_TECH
    return story_type or "OTHER"


def _declared_mechanism(action: str) -> str:
    prefix = _clean(action, 500).split(":", 1)[0].upper().replace(" ", "_").replace("-", "_")
    known = {
        "PHYSICAL_ACTION", "STATE_CHANGE", "CONTEXT_REVEAL", "RELATIONAL_REVEAL",
        "ENVIRONMENTAL_RECONTEXTUALIZATION", "PROCESS_PROGRESSION", "TEMPORAL_CONTRAST",
        "SCALE_REVEAL", "CAUSE_EFFECT", "OBJECT_STATE_TRANSITION",
    }
    if prefix in known:
        return prefix
    value = action.lower()
    for label, terms in (
        ("PHYSICAL_ACTION", ("lifts", "places", "runs", "jumps", "performs", "demonstrates")),
        ("PROCESS_PROGRESSION", ("assembles", "flows", "moves through", "sequence", "process")),
        ("STATE_CHANGE", ("changes", "becomes", "transforms", "opens", "closes")),
        ("CONTEXT_REVEAL", ("reveals", "widens", "context")),
    ):
        if any(term in value for term in terms):
            return label
    return "UNDECLARED"


def _camera_strategy(value: Any) -> str:
    text = _clean(value, 1000).lower()
    for label, terms in (
        ("PULLBACK_WIDEN", ("pullback", "pull back", "widen", "wide shot")),
        ("PUSH_IN", ("push-in", "push in", "dolly in")),
        ("TRACKING", ("tracking", "follow", "travelling")),
        ("ORBIT", ("orbit", "arc around")),
        ("PAN_TILT", (" pan", "pan ", "tilt")),
        ("MACRO_CLOSE", ("macro", "close-up", "close up", "tight detail")),
        ("LOCKED", ("locked", "static", "fixed")),
        ("HANDHELD", ("handheld", "hand-held")),
    ):
        if any(term in text for term in terms):
            return label
    return "OTHER"


def _transition_strategy(value: Any) -> str:
    text = _clean(value, 600).lower()
    for label, terms in (
        ("MATCH", ("match", "matched")),
        ("CONTINUOUS", ("continuous", "same motion", "seamless")),
        ("CUT", ("cut", "hard cut")),
        ("DISSOLVE_FADE", ("dissolve", "fade")),
        ("MOTIVATED_REVEAL", ("reveal", "occlusion", "wipe")),
    ):
        if any(term in text for term in terms):
            return label
    return "OTHER"


def storyboard_signature(case: dict[str, Any]) -> dict[str, Any]:
    storyboard = case.get("storyboard") or []
    plan = case.get("visual_story_plan") or case.get("effective_visual_story_plan") or {}
    story = case.get("story_understanding") or {}
    visualizability = case.get("visualizability_analysis") or plan.get("visualizability_analysis") or {}
    mechanisms = [_declared_mechanism(str(shot.get("action") or "")) for shot in storyboard]
    cameras = [
        _camera_strategy(f"{shot.get('camera', '')} {shot.get('composition', '')} {shot.get('visual_description') or shot.get('visual') or ''}")
        for shot in storyboard
    ]
    transitions = [
        _transition_strategy(f"{shot.get('transition_in', '')} {shot.get('transition_out', '')}")
        for shot in storyboard
    ]
    progression = [str(shot.get("purpose") or "").upper() for shot in storyboard]
    environment = [
        _clean(shot.get("environmental_change") or shot.get("environment"), 500)
        for shot in storyboard
    ]
    first = storyboard[0] if storyboard else {}
    last = storyboard[-1] if storyboard else {}
    rendered = " ".join(
        _clean(shot.get(key) if key != "visual_description" else shot.get("visual_description") or shot.get("visual"), 1200)
        for shot in storyboard
        for key in ("purpose", "visual_description", "action", "environment", "camera", "transition_in", "transition_out")
    )
    close_pullback_hero = bool(
        storyboard
        and cameras[0] == "MACRO_CLOSE"
        and "PULLBACK_WIDEN" in cameras[1:]
        and (progression[-1] == "HERO PAYOFF" or "hero" in _clean(plan.get("hero_payoff") or last, 1000).lower())
    )
    category_template_terms = [
        phrase
        for phrase in ("fashion editorial", "product showcase", "technology promo", "museum exhibition", "luxury advertisement")
        if phrase in rendered.lower() or phrase in _clean(plan, 8000).lower()
    ]
    return {
        "case_id": case.get("case_id") or case.get("id") or "",
        "route": case.get("route") or route_story(story, visualizability),
        "story_type": visualizability.get("story_type") or story.get("story_type") or "OTHER",
        "visual_mechanisms": mechanisms,
        "hook_mechanism": mechanisms[0] if mechanisms else "NONE",
        "hook_structure": {
            "purpose": str(first.get("purpose") or "").upper(),
            "mechanism": mechanisms[0] if mechanisms else "NONE",
            "camera": cameras[0] if cameras else "NONE",
        },
        "shot_progression": progression,
        "camera_strategies": cameras,
        "environmental_strategies": environment,
        "transition_strategies": transitions,
        "hero_payoff_strategy": _clean(plan.get("hero_payoff") or last.get("after_viewer_understands"), 1200),
        "close_pullback_hero_pattern": close_pullback_hero,
        "category_template_signals": category_template_terms,
        "rendered_story_tokens": sorted(_tokens(rendered)),
        "rendered_story_text": rendered,
    }


def _text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _clean(left).lower(), _clean(right).lower()).ratio()


def detect_template_reuse(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    same_route = left.get("route") == right.get("route")
    same_mechanisms = left.get("visual_mechanisms") == right.get("visual_mechanisms")
    same_hook = left.get("hook_structure") == right.get("hook_structure")
    same_progression = left.get("shot_progression") == right.get("shot_progression")
    same_cameras = left.get("camera_strategies") == right.get("camera_strategies")
    same_transitions = left.get("transition_strategies") == right.get("transition_strategies")
    similarity = _text_similarity(left.get("rendered_story_text", ""), right.get("rendered_story_text", ""))
    structural_matches = sum((same_mechanisms, same_hook, same_progression, same_cameras, same_transitions))
    detected = bool(
        not same_route
        and (
            (structural_matches >= 4 and similarity >= 0.45)
            or (same_mechanisms and same_hook and same_cameras and similarity >= 0.68)
        )
    )
    return {
        "template_reuse_detected": detected,
        "unrelated_routes": not same_route,
        "structural_match_count": structural_matches,
        "textual_similarity": round(similarity, 3),
        "same_visual_mechanisms": same_mechanisms,
        "same_hook_structure": same_hook,
        "same_shot_progression": same_progression,
        "same_camera_strategy": same_cameras,
        "same_transition_strategy": same_transitions,
        "substitutable_with_noun_swap": detected,
    }


def compare_storyboards(cases: list[dict[str, Any]]) -> dict[str, Any]:
    signatures = [storyboard_signature(case) for case in cases]
    comparisons = []
    failures = []
    for left, right in combinations(signatures, 2):
        reuse = detect_template_reuse(left, right)
        same_close_pullback_hero = bool(left["close_pullback_hero_pattern"] and right["close_pullback_hero_pattern"])
        item = {
            "left": left["case_id"],
            "right": right["case_id"],
            **reuse,
            "same_close_pullback_hero_pattern": same_close_pullback_hero,
        }
        comparisons.append(item)
        if reuse["template_reuse_detected"] or same_close_pullback_hero:
            failures.append(f"{left['case_id']} and {right['case_id']} collapse into the same reusable visual formula.")
    route_coverage = {signature["route"] for signature in signatures}
    if not GENERALIZATION_ROUTES <= route_coverage:
        failures.append("The validation suite does not cover all three required story routes.")
    if any(signature["category_template_signals"] for signature in signatures):
        failures.append("One or more storyboards contains a generic category-template signal.")
    return {
        "status": "GENERALIZATION_PASS" if not failures else "GENERALIZATION_FAILURE",
        "route_coverage": sorted(route_coverage),
        "signatures": signatures,
        "pairwise_comparisons": comparisons,
        "failures": failures,
        "different_visual_mechanisms": len({tuple(item["visual_mechanisms"]) for item in signatures}) == len(signatures),
        "different_hook_structures": len({tuple(item["hook_structure"].values()) for item in signatures}) == len(signatures),
    }


def scan_production_special_cases(root: Path) -> dict[str, Any]:
    """Reject golden-fixture phrases in production Python while allowing tests/scripts."""
    findings = []
    excluded_parts = {"tests", "scripts", "test-output", ".venv", "__pycache__"}
    for path in root.rglob("*.py"):
        if excluded_parts & set(path.relative_to(root).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in PRODUCTION_SPECIAL_CASE_PATTERNS:
            for match in re.finditer(pattern, text, re.I):
                line = text.count("\n", 0, match.start()) + 1
                findings.append({"file": str(path.relative_to(root)), "line": line, "pattern": pattern, "match": match.group(0)})
    return {"status": "PASS" if not findings else "FAIL", "findings": findings}
