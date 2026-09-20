from __future__ import annotations

import re
from typing import Any

from action_outcome_contract import build_action_outcome_contract


ACHIEVEMENT_TYPES = {
    "COUNTED_ACHIEVEMENT", "FIRST_OF_KIND", "SPEED_RECORD", "DISTANCE_RECORD",
    "REPEATED_PERFORMANCE", "RANKING", "CERTIFICATION", "MILESTONE", "OTHER",
}


def _clean(value: Any, limit: int = 2000) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _source_text(article: dict[str, Any], story: dict[str, Any]) -> str:
    fields = [
        article.get("headline"), article.get("standfirst"), article.get("article_body"),
        story.get("what_happened"), story.get("new_development"), story.get("core_message"),
        *(story.get("key_visual_facts") or []),
    ]
    return " ".join(_clean(item, 40000) for item in fields if _clean(item))


def _sentences(text: str) -> list[str]:
    return [
        _clean(item, 700)
        for item in re.split(r"(?<=[.!?])\s+|\n+", text)
        if _clean(item)
        and "@" not in item
        and not re.search(r"\b(?:submit your|opinion pieces|press releases|newsletter|cookie policy)\b", item, re.I)
    ]


def _classify(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b\d+\s+(?:[a-z-]+\s+){0,3}(?:records?|titles?|wins?|achievements?|milestones?)\b", lowered):
        return "COUNTED_ACHIEVEMENT"
    if re.search(r"\b(?:first|youngest|oldest)\b", lowered):
        return "FIRST_OF_KIND"
    if re.search(r"\b(?:per\s+(?:minute|second|hour)|fastest|speed)\b", lowered):
        return "SPEED_RECORD"
    if re.search(r"\b(?:distance|metres?|meters?|kilometres?|kilometers?|miles?)\b", lowered):
        return "DISTANCE_RECORD"
    if re.search(r"\b(?:consecutive|repeated|in a row|times)\b", lowered):
        return "REPEATED_PERFORMANCE"
    if re.search(r"\b(?:ranked|ranking|number one|top[- ]?\d+)\b", lowered):
        return "RANKING"
    if re.search(r"\b(?:certified|certification|accredited|qualified)\b", lowered):
        return "CERTIFICATION"
    if re.search(r"\b(?:milestone|completed|achieved|reached)\b", lowered):
        return "MILESTONE"
    return "OTHER"


def _observable_facts(story: dict[str, Any], text: str) -> list[str]:
    candidates = list(story.get("key_visual_facts") or []) + _sentences(text)
    action = re.compile(
        r"\b(?:punch(?:es|ed|ing)?|kick(?:s|ed|ing)?|strike(?:s|ing)?|lift(?:s|ed|ing)?|"
        r"run(?:s|ning)?|jump(?:s|ed|ing)?|throw(?:s|ing)?|hold(?:s|ing)?|balance(?:s|d|ing)?|"
        r"complete(?:s|d|ing)?|perform(?:s|ed|ing)?|demonstrat(?:e|es|ed|ing)|break(?:s|ing)?)\b",
        re.I,
    )
    ranked = []
    for item in candidates:
        cleaned = _clean(item, 700)
        if cleaned and action.search(cleaned):
            score = (
                len(re.findall(r"\b\d+\b", cleaned)) * 5
                + len(re.findall(r"\b(?:punch|kick|strike|hold|egg|ball|object|tool|apparatus)\w*\b", cleaned, re.I)) * 7
                + (8 if cleaned in (story.get("key_visual_facts") or []) else 0)
                - len(cleaned) // 90
            )
            ranked.append((score, cleaned))
    return list(dict.fromkeys(item for _, item in sorted(ranked, reverse=True)))[:4]


def analyze_achievement_representation(article: dict[str, Any], story: dict[str, Any]) -> dict[str, Any]:
    """Allocate achievement meaning without inventing ceremonial evidence."""
    source = _source_text(article, story)
    kind = _classify(source)
    sentences = _sentences(source)
    count_claims = [
        item for item in sentences
        if re.search(r"\b\d+\s+(?:[a-z-]+\s+){0,3}(?:records?|titles?|wins?|achievements?|milestones?)\b", item, re.I)
    ][:3]
    timed_claims = [item for item in sentences if re.search(r"\b\d+\s+(?:punches?|repetitions?|laps?|goals?|points?)\b.*\b(?:minute|second|hour)\b", item, re.I)][:3]
    observable = _observable_facts(story, source)
    action_outcome = build_action_outcome_contract(observable or sentences)
    visually_demonstrated = observable[:2]
    visually_suggested = observable[2:4]
    controlled_text = list(dict.fromkeys(count_claims + timed_claims))
    narration = [
        item for item in sentences
        if item in controlled_text or re.search(r"\b(?:record|rank|certif|milestone|achievement|first|youngest|oldest)\b", item, re.I)
    ][:5]
    if not visually_demonstrated:
        visually_demonstrated = [_clean(story.get("primary_visual_story") or story.get("what_happened"), 700)]
    payoff = (
        "Resolve on the supported physical performance completing cleanly, with its distinctive object, "
        "body control, and immediate physical outcome still visible; do not substitute a generic award pose."
    )
    return {
        "achievement_type": kind if kind in ACHIEVEMENT_TYPES else "OTHER",
        "visually_demonstrated": [item for item in visually_demonstrated if item],
        "visually_suggested": visually_suggested,
        "narration_dependent": narration,
        "controlled_text_dependent": controlled_text,
        "count_requires_literal_objects": False,
        "strong_payoff_requirement": payoff,
        "action_outcome_contract": action_outcome,
        "forbidden_inventions": [
            "unsupported trophies", "unsupported medals", "unsupported certificates",
            "unsupported scoreboards", "unsupported judges", "unsupported crowds",
            "unsupported record books", "unsupported logos", "fabricated event staging",
        ],
    }


def apply_achievement_representation(article: dict[str, Any], story: dict[str, Any], visual_plan: dict[str, Any]) -> dict[str, Any] | None:
    story_type = str(visual_plan.get("story_type") or (story.get("visualizability_analysis") or {}).get("story_type") or "").upper()
    if story_type != "PERSON_ACTION":
        return None
    analysis = analyze_achievement_representation(article, story)
    story["achievement_representation"] = analysis
    visual_plan["achievement_representation"] = analysis
    gap = visual_plan.get("narration_gap") if isinstance(visual_plan.get("narration_gap"), dict) else {}
    gap["narration_must_explain"] = list(dict.fromkeys((gap.get("narration_must_explain") or []) + analysis["narration_dependent"]))
    gap["controlled_text_must_explain"] = analysis["controlled_text_dependent"]
    visual_plan["narration_gap"] = gap
    visual_plan["must_show"] = list(dict.fromkeys((visual_plan.get("must_show") or []) + analysis["visually_demonstrated"]))
    visual_plan["must_avoid"] = list(dict.fromkeys((visual_plan.get("must_avoid") or []) + analysis["forbidden_inventions"]))
    visual_plan["hero_payoff"] = analysis["strong_payoff_requirement"]
    story["action_outcome_contract"] = analysis["action_outcome_contract"]
    visual_plan["action_outcome_contract"] = analysis["action_outcome_contract"]
    return analysis
