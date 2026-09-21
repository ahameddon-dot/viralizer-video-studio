"""Article-specific visual authority and anti-genericity controls.

This module converts extracted article meaning into the visual facts, mechanism,
channel allocation, concept candidates, and quality gates consumed downstream.
It deliberately contains no publisher-, country-, company-, or example-specific
rules; decisions are based on the reported event and evidence language.
"""
from __future__ import annotations

import re
from typing import Any

from editorial_story_layer import allocate_editorial_information


STORY_TYPES = {
    "PERSON_ACTION", "ACHIEVEMENT", "PRODUCT_LAUNCH", "PRODUCT_CHANGE",
    "INTERFACE_CHANGE", "TECHNICAL_PROCESS", "CYBERSECURITY_INCIDENT",
    "POLICY_COLLABORATION", "BUSINESS_CHANGE", "SCIENTIFIC_DISCOVERY",
    "MISSION_OR_PROJECT", "EVENT", "OBJECT_SIGNIFICANCE", "INFRASTRUCTURE",
    "COMPARISON", "TRANSFORMATION", "DATA_OR_MARKET_STORY", "OTHER",
}
VISUAL_MECHANISMS = {
    "ACTION_RESULT", "BEFORE_AFTER", "SYSTEM_CONNECTION", "BOUNDARY_CROSSING",
    "PROCESS_PROGRESSION", "STATE_TRANSITION", "NETWORK_EXPANSION",
    "OBJECT_REVEAL", "INTERFACE_CHANGE", "CAUSE_EFFECT", "RELATIONAL_CHANGE",
    "SCALE_CHANGE", "ENVIRONMENTAL_CHANGE", "ASSEMBLY", "COMPARISON",
    "CONTAINMENT_FAILURE", "MISSION_PREPARATION", "PHYSICAL_DEMONSTRATION",
    "EVIDENCE_REVEAL",
}

GENERIC_VISUAL_PATTERNS = (
    r"\b(?:team member|engineer) demonstrates\b", r"\bcolleagues observe\b",
    r"\btechnology business editorial\b", r"\bprofessional environment\b",
    r"\bpeople (?:looking|staring) at (?:monitors|screens|code)\b",
    r"\bbusiness team\b", r"\bscientists? (?:in|around) (?:a )?laboratory\b",
    r"\bhoodie hacker\b", r"\bgreen code rain\b", r"\bfuturistic blue server room\b",
    r"\brandom (?:electronic|futuristic) (?:device|gadget|machine)\b",
)
UNSUPPORTED_TECH_DECORATION = (
    "futuristic cylinder", "holographic chip", "laser gadget", "fake scientific machine",
    "meaningless antenna box", "fictional scanner", "glowing brain", "humanoid robot",
)
READABLE_GENERATED_SCREEN = re.compile(
    r"\b(?:readable|display(?:s|ing)?|show(?:s|ing)?)\s+(?:code|headlines?|company names?|dates?|statistics?|terminal commands?|ui labels?|news articles?|chart labels?|map labels?)\b",
    re.I,
)


def _clean(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _unique(values: list[Any], limit: int = 12) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value, 800)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key); result.append(text)
    return result[:limit]


def _tokens(value: Any) -> set[str]:
    stop = {"about", "after", "again", "article", "could", "from", "into", "more", "other", "their", "there", "these", "this", "through", "video", "visual", "with"}
    return {item.lower() for item in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]+", str(value or "")) if len(item) > 3 and item.lower() not in stop}


def classify_article_story_type(story: dict[str, Any], article: dict[str, Any] | None = None) -> str:
    declared = _clean((story.get("visualizability_analysis") or {}).get("story_type") or story.get("story_type"), 80).upper()
    text = " ".join(_clean((article or {}).get(key), 20000) for key in ("headline", "standfirst", "article_body"))
    text += " " + " ".join(_clean(story.get(key), 4000) for key in ("what_happened", "new_development", "core_message", "viewer_takeaway"))
    lower = text.lower()
    rules = (
        ("CYBERSECURITY_INCIDENT", r"\b(?:cyber|hack|breach|malware|ransomware|vulnerabilit|unauthori[sz]ed|sandbox escape|security boundary|privilege escalation)"),
        ("POLICY_COLLABORATION", r"\b(?:joins?|agreement|initiative|alliance|coalition|collaborat|partnership|standards? body|memorandum|countries)"),
        ("INTERFACE_CHANGE", r"\b(?:interface|dashboard|menu|button|user interface|ui |redesign|navigation)"),
        ("PRODUCT_LAUNCH", r"\b(?:launch(?:es|ed)?|unveil(?:s|ed)?|debut(?:s|ed)?|introduc(?:es|ed))\b.*\b(?:product|device|model|service|platform|phone|car)"),
        ("PRODUCT_CHANGE", r"\b(?:update|upgrade|redesign|recall|feature|version|changes?)\b.*\b(?:product|device|model|service|platform|phone|car)"),
        ("SCIENTIFIC_DISCOVERY", r"\b(?:discover|study finds|researchers? found|scientists? found|breakthrough|experiment)"),
        ("MISSION_OR_PROJECT", r"\b(?:mission|project|expedition|programme|program)\b.*\b(?:plan|prepare|launch|build|develop)"),
        ("INFRASTRUCTURE", r"\b(?:infrastructure|network deployment|antenna|wireless network|telecom|rail|bridge|grid|data center)"),
        ("DATA_OR_MARKET_STORY", r"\b(?:market|revenue|sales|shares?|stock|growth|decline|forecast|index|price)"),
        ("ACHIEVEMENT", r"\b(?:record|wins?|award|achievement|milestone|first person|champion)"),
        ("TECHNICAL_PROCESS", r"\b(?:process|system|workflow|manufactur|assembly|algorithm|mechanism|pipeline)"),
        ("COMPARISON", r"\b(?:compared with|versus| vs\.? |outperform|faster than|slower than)"),
        ("BUSINESS_CHANGE", r"\b(?:acquire|merger|restructur|appoint|expands?|closes?|opens?|investment|funding)"),
        ("TRANSFORMATION", r"\b(?:transform|convert|restore|becomes?|turned into|transition)"),
        ("PERSON_ACTION", r"\b(?:person|woman|man|athlete|actor|singer|player|chef|designer)\b.*\b(?:performs?|creates?|wears?|walks?|builds?|breaks?|cuts?|prepares?|cooks?|demonstrates?|wins?)"),
        ("OBJECT_SIGNIFICANCE", r"\b(?:artifact|dress|object|painting|jewel|document|auction|exhibition|display)"),
        ("EVENT", r"\b(?:event|festival|ceremony|match|conference|summit|show)"),
    )
    for story_type, pattern in rules:
        if re.search(pattern, lower, re.I | re.S):
            return story_type
    aliases = {"PROCESS": "TECHNICAL_PROCESS", "PRODUCT": "PRODUCT_CHANGE", "RELATIONSHIP": "POLICY_COLLABORATION", "PLACE": "INFRASTRUCTURE", "EXPLANATION": "OTHER"}
    return aliases.get(declared, declared if declared in STORY_TYPES else "OTHER")


def _temporal_status(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(?:proposed|proposal|considering|may|might|could)\b", lower): return "PROPOSED"
    if re.search(r"\b(?:expected|forecast|projected|anticipated)\b", lower): return "EXPECTED"
    if re.search(r"\b(?:will|plans? to|scheduled|upcoming|set to)\b", lower): return "PLANNED_FUTURE"
    if re.search(r"\b(?:has|have|had|was|were|announced|launched|joined|found|reported)\b", lower): return "PAST_CONFIRMED"
    return "CURRENT_CONFIRMED"


def select_visual_mechanism(story_type: str, kernel: dict[str, Any]) -> str:
    mapping = {
        "PERSON_ACTION": "ACTION_RESULT", "ACHIEVEMENT": "ACTION_RESULT",
        "PRODUCT_LAUNCH": "OBJECT_REVEAL", "PRODUCT_CHANGE": "BEFORE_AFTER",
        "INTERFACE_CHANGE": "INTERFACE_CHANGE", "TECHNICAL_PROCESS": "PROCESS_PROGRESSION",
        "CYBERSECURITY_INCIDENT": "BOUNDARY_CROSSING", "POLICY_COLLABORATION": "SYSTEM_CONNECTION",
        "BUSINESS_CHANGE": "RELATIONAL_CHANGE", "SCIENTIFIC_DISCOVERY": "EVIDENCE_REVEAL",
        "MISSION_OR_PROJECT": "MISSION_PREPARATION", "EVENT": "ACTION_RESULT",
        "OBJECT_SIGNIFICANCE": "OBJECT_REVEAL", "INFRASTRUCTURE": "NETWORK_EXPANSION",
        "COMPARISON": "COMPARISON", "TRANSFORMATION": "STATE_TRANSITION",
        "DATA_OR_MARKET_STORY": "SCALE_CHANGE", "OTHER": "CAUSE_EFFECT",
    }
    mechanism = mapping.get(story_type, "CAUSE_EFFECT")
    change = _clean(kernel.get("main_change"), 800).lower()
    if any(term in change for term in ("contain", "escape", "breach", "cross")): mechanism = "BOUNDARY_CROSSING"
    elif any(term in change for term in ("connect", "join", "collaborat", "partner")): mechanism = "SYSTEM_CONNECTION"
    elif any(term in change for term in ("assemble", "build", "prepare")): mechanism = "ASSEMBLY"
    return mechanism


def build_article_visual_kernel(article: dict[str, Any], story: dict[str, Any], visualizability: dict[str, Any]) -> dict[str, Any]:
    story_type = classify_article_story_type(story, article)
    facts = _unique(list(story.get("key_visual_facts") or []) + list(visualizability.get("visualizable_facts") or []), 10)
    subjects = _unique(story.get("main_subjects") or [], 8)
    subject = _clean(visualizability.get("primary_visual_story") or (subjects[0] if subjects else story.get("what_happened")), 500)
    change = _clean(story.get("new_development") or story.get("what_happened") or story.get("core_message"), 900)
    evidence = " ".join(_clean(article.get(key), 12000) for key in ("headline", "standfirst", "article_body"))
    relations = [fact for fact in facts if re.search(r"\b(?:with|between|joins?|connect|affect|from|to|across|against)\b", fact, re.I)]
    locations = _unique(re.findall(r"\b(?:in|at|across|from)\s+([A-Z][A-Za-z.-]+(?:\s+[A-Z][A-Za-z.-]+){0,3})", evidence), 5)
    nonvisual = _unique(list(visualizability.get("narration_dependent_meanings") or []) + list(visualizability.get("partially_visualizable_meanings") or []), 10)
    anchors = _unique([*subjects, *facts[:4]], 10)
    temporary = {"main_change": change}
    mechanism = select_visual_mechanism(story_type, temporary)
    environments = {
        "CYBERSECURITY_INCIDENT": "isolated computing systems and a clearly legible security boundary",
        "POLICY_COLLABORATION": "the supported operational, standards, infrastructure, or system relationship behind the collaboration",
        "INFRASTRUCTURE": "the article-supported infrastructure and connected nodes",
        "TECHNICAL_PROCESS": "the real process environment and its necessary components",
        "SCIENTIFIC_DISCOVERY": "the supported experiment, observation, specimen, or evidence context",
        "PRODUCT_LAUNCH": "the product's supported real usage or launch context",
        "PRODUCT_CHANGE": "the product's supported real usage context",
        "INTERFACE_CHANGE": "abstract non-readable interface geometry unless legitimate source UI is supplied",
        "MISSION_OR_PROJECT": "the supported preparation or assembly environment",
    }
    environment = environments.get(story_type, "the minimum real-world context supported by the article")
    visual_sentence = {
        "CYBERSECURITY_INCIDENT": f"Show {subject} as the execution path reaches and crosses the supported security boundary, affects the evidenced target relationship, and ends in visible containment or investigation.",
        "POLICY_COLLABORATION": f"Show {subject} establishing visible links through the supported infrastructure or system relationship into the wider standards and research network; reserve names, counts, and agreement details for narration or controlled text.",
        "INFRASTRUCTURE": f"Show {subject} changing from the article's prior state into the newly connected or expanded infrastructure state, using only supported nodes and relationships.",
        "TECHNICAL_PROCESS": f"Follow {subject} through the specific supported process so each visible state causes the next and the final result reveals the article's change.",
        "SCIENTIFIC_DISCOVERY": f"Reveal the supported evidence around {subject}, moving from the observable starting condition to the newly established finding without fabricating a laboratory event.",
        "PRODUCT_LAUNCH": f"Reveal {subject} in its supported use context and show the new capability or launch change through one observable interaction.",
        "PRODUCT_CHANGE": f"Compare the supported prior and changed states of {subject}, making the article's specific difference visible without generated labels.",
        "PERSON_ACTION": f"Show {subject} performing the supported action and end on its observable physical result.",
        "ACHIEVEMENT": f"Show {subject} completing the supported feat and end on the article-supported result rather than symbolic awards.",
    }.get(story_type, f"Show {subject} moving through the article-supported change: {change.rstrip(' .')}, ending on the clearest observable result.")
    before_state = _clean(story.get("important_context"), 700)
    if not before_state or before_state.lower().startswith("the article describes"):
        before_state = _clean(f"the supported state immediately before {change.rstrip(' .')}", 700)
    return {
        "article_event": _clean(story.get("what_happened"), 1000),
        "main_change": change,
        "core_visual_subject": subject,
        "visualizable_action_or_change": _clean(visualizability.get("primary_visual_story") or change, 1000),
        "before_state": before_state,
        "after_state": _clean(story.get("new_development") or story.get("viewer_takeaway"), 700),
        "important_relationships": _unique(relations, 8),
        "physical_evidence": facts,
        "location_or_environment_if_supported": _unique([*locations, environment], 6),
        "temporal_status": _temporal_status(evidence + " " + change),
        "unique_visual_anchors": anchors,
        "nonvisual_facts": nonvisual,
        "abstract_meanings": _unique(visualizability.get("partially_visualizable_meanings") or [], 8),
        "visual_story_sentence": visual_sentence,
        "story_type": story_type,
        "selected_visual_mechanism": mechanism,
        "human_presence": {
            "required": story_type in {"PERSON_ACTION", "ACHIEVEMENT"},
            "justification": "A visible human action carries the article meaning." if story_type in {"PERSON_ACTION", "ACHIEVEMENT"} else "People are excluded unless source evidence makes them necessary to understand the event.",
        },
        "visual_truth_classification": "SAFE_EDITORIAL_VISUALIZATION" if story_type in {"CYBERSECURITY_INCIDENT", "POLICY_COLLABORATION", "DATA_OR_MARKET_STORY"} else ("LITERAL_SUPPORTED_VISUAL" if facts else "SAFE_EDITORIAL_VISUALIZATION"),
    }


def article_relation_score(candidate: Any, kernel: dict[str, Any]) -> dict[str, Any]:
    text = _clean(candidate, 12000).lower()
    anchors = _tokens(" ".join(kernel.get("unique_visual_anchors") or []) + " " + _clean(kernel.get("main_change"), 1000))
    matched = sorted(item for item in anchors if item in text)
    anchor_score = round(55 * len(matched) / max(1, min(len(anchors), 10)))
    mechanism = str(kernel.get("selected_visual_mechanism") or "").lower().replace("_", " ")
    mechanism_terms = set(mechanism.split()) | _tokens(kernel.get("visual_story_sentence"))
    mechanism_score = 25 if any(item in text for item in mechanism_terms) else 0
    change_score = 20 if _tokens(kernel.get("visualizable_action_or_change")) & _tokens(text) else 0
    generic_hits = [pattern for pattern in GENERIC_VISUAL_PATTERNS if re.search(pattern, text, re.I)]
    decoration_hits = [item for item in UNSUPPORTED_TECH_DECORATION if item in text]
    score = max(0, min(100, anchor_score + mechanism_score + change_score - 25 * len(generic_hits) - 20 * len(decoration_hits)))
    return {"score": score, "status": "PASS" if score >= 60 and not generic_hits and not decoration_hits else "FAIL", "matched_anchors": matched, "generic_patterns": generic_hits, "unsupported_tech_decoration": decoration_hits}


def build_concept_candidates(kernel: dict[str, Any]) -> list[dict[str, Any]]:
    subject = kernel["core_visual_subject"]
    mechanism = kernel["selected_visual_mechanism"]
    before, after = kernel["before_state"], kernel["after_state"]
    raw = [
        f"{mechanism}: {kernel['visual_story_sentence']}",
        f"EVIDENCE_REVEAL: begin with {subject} in {before}; reveal the supported evidence and resolve on {after}.",
        f"CAUSE_EFFECT: show the supported change affecting {subject}, then reveal the article-specific resulting relationship or state: {after}.",
    ]
    candidates = []
    for concept in raw:
        relation = article_relation_score(concept, kernel)
        candidates.append({
            "concept": concept, "visual_mechanism": concept.split(":", 1)[0],
            "article_specificity": relation["score"], "visualizability": 85,
            "factual_safety": 90, "generation_feasibility": 82,
            "genericity_risk": "LOW" if relation["status"] == "PASS" else "HIGH",
            "article_visual_relation_score": relation["score"],
        })
    return sorted(candidates, key=lambda item: (item["article_visual_relation_score"], item["factual_safety"], item["generation_feasibility"]), reverse=True)


def strengthen_article_visual_plan(article: dict[str, Any], story: dict[str, Any], visualizability: dict[str, Any], plan: dict[str, Any], specificity: dict[str, Any]) -> dict[str, Any]:
    kernel = build_article_visual_kernel(article, story, visualizability)
    allocation = allocate_editorial_information(story, visualizability, specificity, article)
    candidates = build_concept_candidates(kernel)
    selected = candidates[0]
    result = dict(plan)
    result.update(
        article_visual_kernel=kernel,
        story_type=kernel["story_type"],
        selected_visual_mechanism=kernel["selected_visual_mechanism"],
        creative_concept_candidates=candidates,
        selected_creative_concept=selected["concept"],
        creative_concept_selection_reason="Selected for the strongest article relation, factual safety, visible progression, and feasible continuity.",
        core_visual_subject=kernel["core_visual_subject"],
        visual_message=kernel["visual_story_sentence"],
        editorial_channel_allocation=allocation,
        human_presence_justification=kernel["human_presence"],
    )
    beat_relation = article_relation_score(result.get("story_beats") or [], kernel)
    if beat_relation["status"] != "PASS":
        existing_count = max(1, min(4, len(result.get("story_beats") or []) or 2))
        evidence = kernel.get("physical_evidence") or [kernel["visualizable_action_or_change"]]
        beats = []
        for index in range(existing_count):
            if existing_count == 1:
                visual = kernel["visual_story_sentence"]
                purpose = "HERO PAYOFF"
            elif index == 0:
                visual = f"{kernel['selected_visual_mechanism']}: establish {kernel['core_visual_subject']} in the supported before-state: {kernel['before_state']}."
                purpose = "HOOK"
            elif index == existing_count - 1:
                visual = f"{kernel['selected_visual_mechanism']}: resolve the supported change on {kernel['after_state']}."
                purpose = "HERO PAYOFF"
            else:
                visual = f"{kernel['selected_visual_mechanism']}: reveal this article evidence through the same subject and environment: {evidence[min(index - 1, len(evidence) - 1)]}."
                purpose = "DEVELOPMENT"
            beats.append({"beat": index + 1, "purpose": purpose, "visual": visual, "progression_mechanism": kernel["selected_visual_mechanism"], "before_viewer_understands": kernel["before_state"] if index == 0 else beats[-1]["visual"], "after_viewer_understands": kernel["after_state"] if index == existing_count - 1 else visual})
        result["story_beats"] = beats
    must_avoid = list(result.get("must_avoid") or [])
    must_avoid += ["generic category footage", "unsupported technology devices", "generated readable screens or labels"]
    if not kernel["human_presence"]["required"]:
        must_avoid.append("unsupported people added only for visual polish")
    if kernel["story_type"] == "CYBERSECURITY_INCIDENT":
        must_avoid += ["hoodie hacker", "green code rain", "generic analysts watching monitors", "fake terminal text"]
    result["must_avoid"] = _unique(must_avoid, 20)
    relation = article_relation_score(" ".join([result.get("selected_creative_concept", ""), result.get("visual_message", ""), str(result.get("story_beats") or "")]), kernel)
    result["article_visual_relation"] = relation
    result["genericity_result"] = {"status": relation["status"], "code": "PASS" if relation["status"] == "PASS" else "GENERIC_VISUAL_CONCEPT_FAIL", "could_come_from_category_alone": relation["status"] != "PASS"}
    return result


def attach_shot_meaning_contracts(storyboard: list[dict[str, Any]], visual_plan: dict[str, Any]) -> list[dict[str, Any]]:
    kernel = visual_plan.get("article_visual_kernel") or {}
    mechanism = visual_plan.get("selected_visual_mechanism") or kernel.get("selected_visual_mechanism") or "CAUSE_EFFECT"
    anchors = kernel.get("unique_visual_anchors") or []
    evidence = kernel.get("physical_evidence") or visual_plan.get("must_show") or []
    previous = _clean(kernel.get("before_state") or "The reported change has not yet been shown", 700)
    result = []
    for shot in storyboard:
        item = dict(shot)
        after = _clean(item.get("after_viewer_understands") or item.get("visual_description") or item.get("action"), 900)
        if after.casefold() == previous.casefold():
            after = _clean(f"The viewer now sees {kernel.get('main_change') or visual_plan.get('visual_message')}", 900)
        item.update(
            viewer_understands_before=_clean(item.get("viewer_understands_before") or previous, 900),
            viewer_understands_after=after,
            new_article_meaning_added=_clean(item.get("new_article_meaning_added") or after, 900),
            visual_mechanism=_clean(item.get("visual_mechanism") or mechanism, 80),
            source_evidence=_unique(list(item.get("source_evidence") or item.get("source_support") or evidence), 8),
            required_visual_anchors=_unique(list(item.get("required_visual_anchors") or anchors), 8),
            forbidden_generic_elements=_unique(list(item.get("forbidden_generic_elements") or []) + list(visual_plan.get("must_avoid") or []), 12),
        )
        previous = after; result.append(item)
    return result


def evaluate_storyboard_article_relation(storyboard: list[dict[str, Any]], visual_plan: dict[str, Any]) -> dict[str, Any]:
    kernel = visual_plan.get("article_visual_kernel") or {}
    if not kernel:
        return {"score": 100, "status": "PASS", "matched_anchors": [], "generic_patterns": [], "unsupported_tech_decoration": [], "shot_meaning_contracts": True, "meaning_progression": True, "failure_code": ""}
    positive_storyboard = [{key: item.get(key) for key in ("visual_description", "action", "environment", "viewer_understands_before", "viewer_understands_after", "new_article_meaning_added", "visual_mechanism", "source_evidence", "required_visual_anchors")} for item in storyboard]
    relation = article_relation_score(positive_storyboard, kernel)
    progression = all(_clean(item.get("viewer_understands_before")) != _clean(item.get("viewer_understands_after")) for item in storyboard)
    contracts = all(all(key in item for key in ("viewer_understands_before", "viewer_understands_after", "new_article_meaning_added", "visual_mechanism", "source_evidence", "required_visual_anchors", "forbidden_generic_elements")) for item in storyboard)
    status = "PASS" if relation["status"] == "PASS" and progression and contracts else "FAIL"
    return {**relation, "status": status, "shot_meaning_contracts": contracts, "meaning_progression": progression, "failure_code": "" if status == "PASS" else "GENERIC_VISUAL_CONCEPT_FAIL"}


def evaluate_final_prompt(prompt: str, visual_plan: dict[str, Any]) -> dict[str, Any]:
    kernel = visual_plan.get("article_visual_kernel") or {}
    positive_prompt = re.split(r"\b(?:Do not introduce:|Must not generate:|No cuts,)", prompt, maxsplit=1, flags=re.I)[0]
    relation = article_relation_score(positive_prompt, kernel) if kernel else {"score": 100, "status": "PASS", "generic_patterns": [], "unsupported_tech_decoration": []}
    lower = prompt.lower()
    story_first = not re.match(r"^(?:create\s+)?(?:a|an|one)?\s*(?:cinematic|professional|stunning|immersive|technology|business|editorial|slow)", lower)
    text_safe = not READABLE_GENERATED_SCREEN.search(prompt)
    temporal = kernel.get("temporal_status")
    temporal_safe = not (temporal in {"PLANNED_FUTURE", "PROPOSED", "EXPECTED"} and re.search(r"\b(?:completed|fully deployed|already operating|successful mission)\b", lower))
    status = "PASS" if relation["status"] == "PASS" and story_first and text_safe and temporal_safe else "FAIL"
    return {"status": status, "article_relation": relation, "story_first_ordering": story_first, "text_safety": text_safe, "temporal_truth": temporal_safe, "provider_feasibility": True}
