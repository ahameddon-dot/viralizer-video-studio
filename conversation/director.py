"""Conversation Director: deterministic workflow brain for the Viralizer chat.

The language model should write good replies. It should NOT have to remember
where the customer is in the workflow, what was shown a minute ago, or which
"first topic" they mean. This module derives all of that from saved messages
on every turn, then hands the model a compact, factual context pack plus
strict per-intent rules.

Pure standard library: no database, network or framework imports, so it is
cheap to test and safe to call on every turn.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from storyboard_plan import MAX_DURATION, MIN_DURATION, SECONDS_PER_SCENE, normalize_duration, scene_plan

# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------
ONBOARDING = "onboarding"          # no confirmed brand profile yet
DISCOVER = "discover"              # brand ready, no opportunities shown yet
CHOOSE_TOPIC = "choose_topic"      # opportunities shown, none selected
STORYBOARD = "storyboard_review"   # concept + storyboard exist, no images yet
IMAGES = "images_review"           # some/all keyframes exist
ANIMATING = "animating"            # animation started, final video not ready
FINAL = "final_review"             # final video ready, not published
LEARN = "learn"                    # published / reviewing performance

STAGES = (ONBOARDING, DISCOVER, CHOOSE_TOPIC, STORYBOARD, IMAGES, ANIMATING, FINAL, LEARN)

# --------------------------------------------------------------------------
# Intents
# --------------------------------------------------------------------------
ASK_ABOUT_OPPORTUNITIES = "ask_about_opportunities"
EDIT_SCENE = "edit_scene"
EDIT_WHOLE = "edit_whole"
SET_DURATION = "set_duration"
SHOW_RESULTS = "show_results"
FIND_TRENDS = "find_trends"
CREATE_FROM_IDEA = "create_from_idea"
CONFIRM = "confirm"
OFF_TOPIC = "off_topic"
GENERAL = "general"

DOMAIN_WORDS = {
    "video", "videos", "post", "posts", "content", "trend", "trends", "trending", "topic", "topics",
    "brand", "scene", "scenes", "storyboard", "image", "images", "keyframe", "caption", "hashtag",
    "hashtags", "instagram", "youtube", "tiktok", "linkedin", "audience", "viral", "publish",
    "platform", "script", "hook", "followers", "engagement", "growth", "niche", "voice", "style",
    "opportunity", "opportunities", "idea", "ideas", "reel", "reels", "short", "shorts", "clip",
    "performance", "analytics", "views", "likes", "profile", "website", "handle", "campaign",
    "second", "seconds", "duration", "approve", "regenerate", "animate", "photo", "music", "voiceover",
}
_ORDINALS = {
    "first": 0, "1st": 0, "top": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3, "fifth": 4, "5th": 4,
}
_CONFIRM_RE = re.compile(
    r"^\s*(yes|yep|yeah|yup|sure|ok|okay|go ahead|do it|proceed|continue|approve[d]?|looks good|"
    r"sounds good|let'?s go|confirm|great|perfect|create (it|the video)|use these images|"
    r"the images are approved.*)\W*\s*$", re.I)
_EDIT_VERBS = r"(change|make|edit|redo|regenerate|replace|swap|add|remove|delete|more|less|brighter|darker|funnier|shorter|longer|update|fix|different|show)"


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
@dataclass
class DirectorState:
    stage: str = ONBOARDING
    brand_confirmed: bool = False
    opportunities: list[dict[str, Any]] = field(default_factory=list)   # compact, in displayed order
    discovery_empty: bool = False                                        # last live discovery returned nothing
    selected_opportunity: dict[str, Any] | None = None
    concept_id: str = ""
    concept_title: str = ""
    scenes: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: int = 15
    requested_duration: int | None = None
    keyframes: dict[int, str] = field(default_factory=dict)             # scene index -> media url
    animations: dict[int, str] = field(default_factory=dict)            # scene index -> status
    final_media_url: str = ""
    published: bool = False
    last_user_text: str = ""
    idea_mode_requested: bool = False
    custom_idea: str = ""
    narration_mode: str = ""
    narration_text: str = ""
    visual_style: str = ""
    target_platform: str = ""
    aspect_ratio: str = ""
    publication_step: str = ""
    publish_platform: str = ""
    publish_caption: str = ""
    publish_timing: str = ""

    @property
    def brief_step(self) -> str:
        if not self.idea_mode_requested or self.concept_id:
            return ""
        if not self.custom_idea:
            return "idea"
        if not self.requested_duration:
            return "duration"
        if not self.narration_mode:
            return "narration"
        if not self.visual_style:
            return "style"
        if not self.target_platform:
            return "platform"
        return "ready"

    @property
    def scene_count(self) -> int:
        return len(self.scenes)

    @property
    def missing_images(self) -> list[int]:
        return [i for i in range(self.scene_count) if i not in self.keyframes]

    @property
    def images_ready(self) -> bool:
        return self.scene_count > 0 and len(self.keyframes) >= self.scene_count


def _compact_opportunity(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") or {}
    components = item.get("components") or {}
    return {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or "")[:160],
        "category": str(item.get("category") or source.get("category") or "")[:60],
        "score": item.get("score"),
        "viral_rank": components.get("viral_rank") or source.get("viral_rank"),
        "why": str(item.get("rationale") or "")[:220],
    }


def _scenes_from_concept(concept: dict[str, Any]) -> list[dict[str, Any]]:
    content = concept.get("content") or {}
    scenes = content.get("storyboard") or content.get("scenes") or []
    result = []
    for scene in scenes:
        result.append({
            "start": scene.get("start"), "end": scene.get("end"), "purpose": scene.get("purpose"),
            "narration": str(scene.get("narration") or "")[:200],
        })
    return result


def parse_duration(text: str) -> int | None:
    """Return a requested duration in seconds (5..60) or None."""
    match = re.search(r"\b(\d{1,2})\s*(?:-?\s*)(?:s|sec|secs|second|seconds)\b", text or "", re.I)
    if not match:
        return None
    value = int(match.group(1))
    return value if MIN_DURATION <= value <= MAX_DURATION else None


def _parse_narration(text: str) -> tuple[str, str]:
    clean = " ".join((text or "").split())
    if re.search(r"\b(no|without)\s+(voice|voiceover|narration)\b", clean, re.I):
        return "none", ""
    if re.search(r"\b(write|create|generate|suggest|you decide|ai)\b.*\b(narration|voiceover|script)\b|\bnarration for me\b", clean, re.I):
        return "ai", ""
    match = re.search(r"(?:my\s+)?(?:narration|voiceover|script)\s*[:\-]\s*(.+)", clean, re.I)
    return ("custom", match.group(1)[:1200]) if match else ("", "")


def _parse_style(text: str) -> str:
    styles = ("cinematic", "realistic", "luxury", "product commercial", "documentary", "animated", "editorial", "minimal")
    lowered = (text or "").lower()
    return next((style for style in styles if style in lowered), "")


def _parse_platform(text: str) -> tuple[str, str]:
    lowered = (text or "").lower()
    if "youtube short" in lowered or "shorts" in lowered:
        return "youtube", "9:16"
    if "youtube" in lowered and not ("short" in lowered):
        return "youtube", "16:9"
    if "instagram" in lowered or "instagaram" in lowered or "instgram" in lowered or "reel" in lowered:
        return "instagram", "9:16"
    if "tiktok" in lowered:
        return "tiktok", "9:16"
    if "linkedin" in lowered:
        return "linkedin", "1:1"
    if "square" in lowered or "1:1" in lowered:
        return "instagram", "1:1"
    return "", ""


def derive_state(messages: list[dict[str, Any]], brand_confirmed: bool) -> DirectorState:
    """Rebuild workflow state from persisted conversation messages (oldest first)."""
    state = DirectorState(brand_confirmed=bool(brand_confirmed))
    last_substantive_user = ""
    for message in messages or []:
        role, content = message.get("role"), message.get("content") or {}
        if role == "user":
            text = str(content.get("text") or content.get("message") or "")
            state.last_user_text = text
            if state.final_media_url:
                publish_approval = bool(re.search(
                    r"\bapprove\b.*\b(final\s+)?video\b|\bapprove\s*(?:&|and)?\s*post\b|\bpublish\s+(?:it|the video)\b",
                    text, re.I))
                if state.publication_step == "caption" and not publish_approval:
                    if re.search(r"\bchange\b.*\bplatform\b", text, re.I):
                        publish_platform, _ = _parse_platform(text)
                        if publish_platform:
                            state.publish_platform = publish_platform
                            state.publication_step = "caption"
                    elif re.search(r"\b(write|create|generate|suggest)\b.*\bcaption\b|\bcaption for me\b", text, re.I):
                        state.publish_caption = "__ai__"
                        state.publication_step = "timing"
                    else:
                        caption_match = re.match(r"\s*(?:caption\s*[:\-]\s*)?(.+)", text, re.I | re.S)
                        if caption_match and len(caption_match.group(1).strip()) >= 3:
                            state.publish_caption = caption_match.group(1).strip()[:2200]
                            state.publication_step = "timing"
                elif state.publication_step == "timing":
                    if re.search(r"\b(now|immediately|right away)\b", text, re.I):
                        state.publish_timing = "now"
                        state.publication_step = "approval"
                    elif re.search(r"\b(schedule|tomorrow|today|\d{1,2}[:.]\d{2}|am|pm)\b", text, re.I):
                        state.publish_timing = text.strip()[:200]
                        state.publication_step = "approval"
                else:
                    publish_platform, _ = _parse_platform(text)
                    if publish_platform:
                        state.publish_platform = publish_platform
                        state.publication_step = "caption"
                    elif publish_approval and not state.publish_platform:
                        state.publication_step = "platform"
            if not _CONFIRM_RE.match(text) and len(text.strip()) >= 3:
                last_substantive_user = text.strip()[:500]
            activates_idea_mode = bool(re.search(
                r"\b(own|my|custom)\s+(video\s+)?idea\b|\bstart with (my |an? )?idea\b", text, re.I))
            if activates_idea_mode:
                state.idea_mode_requested = True
                inline_idea = re.search(r"\b(?:own|my|custom)\s+(?:video\s+)?idea\s*(?:is\s*:|is|:|-)\s*(.+)", text, re.I | re.S)
                if inline_idea and inline_idea.group(1).strip():
                    state.custom_idea = inline_idea.group(1).strip()[:500]
            elif state.idea_mode_requested and not state.custom_idea and not _CONFIRM_RE.match(text) and len(text.strip()) >= 3:
                state.custom_idea = text.strip()[:500]
            duration = parse_duration(text)
            if duration:
                state.requested_duration = duration
            narration_mode, narration_text = _parse_narration(text)
            if state.idea_mode_requested and narration_mode:
                state.narration_mode, state.narration_text = narration_mode, narration_text
            style = _parse_style(text)
            if state.idea_mode_requested and state.custom_idea and style:
                state.visual_style = style
            platform, ratio = _parse_platform(text)
            if state.idea_mode_requested and state.custom_idea and platform:
                state.target_platform, state.aspect_ratio = platform, ratio
            match = re.search(r"opportunity ID\s+([A-Za-z0-9_-]+)", text)
            if match:
                chosen = next((o for o in state.opportunities if o["id"] == match.group(1)), None)
                if chosen:
                    state.selected_opportunity = chosen
            elif state.opportunities:
                # Topic cards and numbered chat lists both allow a customer to
                # answer with only "1", "#2", or "option 3". Persist that
                # selection in derived state so the next buttons advance to
                # duration instead of falling back to discovery actions.
                ordinal = re.fullmatch(r"\s*(?:option\s*)?#?(\d{1,2})\s*", text, re.I)
                if ordinal:
                    index = int(ordinal.group(1)) - 1
                    if 0 <= index < len(state.opportunities):
                        state.selected_opportunity = state.opportunities[index]
        elif role == "tool":
            output = content.get("output") or {}
            if output.get("status") != "completed":
                continue
            data, tool = output.get("data") or {}, content.get("tool")
            if tool == "discover_topics":
                ranked = [_compact_opportunity(o) for o in data.get("opportunities") or []]
                state.discovery_empty = not ranked
                if ranked:
                    state.opportunities = ranked
                    state.selected_opportunity = None
            elif tool == "rank_opportunities":
                ranked = [_compact_opportunity(o) for o in data.get("opportunities") or []]
                # A transient empty refresh must never erase a topic the
                # customer already selected. Preserve the last valid ranked
                # set and selection; the user can explicitly request a new
                # discovery when they actually want to replace it.
                if ranked:
                    state.opportunities = ranked
                    state.selected_opportunity = None
                    state.concept_id, state.scenes, state.keyframes, state.animations = "", [], {}, {}
                    state.final_media_url, state.published = "", False
                else:
                    state.discovery_empty = True
            elif tool == "create_concepts":
                concepts = data.get("concepts") or []
                if concepts:
                    first = concepts[0]
                    state.concept_id = str(first.get("id") or "")
                    state.concept_title = str((first.get("content") or {}).get("title") or first.get("name") or "")
                    state.scenes = _scenes_from_concept(first)
                    state.duration_seconds = int((first.get("content") or {}).get("duration_seconds") or 15)
                    state.keyframes, state.animations = {}, {}
                    state.final_media_url = ""
                    opportunity_id = str(first.get("opportunity_id") or "")
                    chosen = next((o for o in state.opportunities if o["id"] == opportunity_id), None)
                    if chosen:
                        state.selected_opportunity = chosen
            elif tool == "create_from_idea":
                concepts = data.get("concepts") or []
                if concepts:
                    first = concepts[0]
                    state.concept_id = str(first.get("id") or "")
                    state.concept_title = str((first.get("content") or {}).get("title") or first.get("name") or "")
                    state.scenes = _scenes_from_concept(first)
                    state.duration_seconds = int((first.get("content") or {}).get("duration_seconds") or 15)
                    state.keyframes, state.animations = {}, {}
                    state.final_media_url = ""
                    state.idea_mode_requested = False
                    state.custom_idea = ""
            elif tool == "revise_storyboard":
                revised = data.get("concept") or {}
                if revised.get("id") and str(revised.get("id")) == state.concept_id:
                    state.scenes = _scenes_from_concept(revised)
                    for index in data.get("stale_images") or []:
                        state.keyframes.pop(int(index), None)
                        state.animations.pop(int(index), None)
                    state.final_media_url = ""
            elif tool == "get_growth_report":
                state.published = state.published or bool((data.get("publications") or data.get("posts")))
        elif role == "assistant":
            if content.get("type") == "tool_result":
                result, tool = content.get("result") or {}, content.get("tool")
                index = result.get("scene_index")
                if tool == "generate_keyframe" and isinstance(index, int):
                    state.keyframes[index] = str(content.get("media_url") or "done")
                elif tool == "animate_scene" and isinstance(index, int):
                    state.animations[index] = str(result.get("status") or "started")
                elif tool == "finalize_video":
                    state.final_media_url = str(content.get("media_url") or "done")
            else:
                assistant_text = str(content.get("text") or content.get("message") or "")
                confirmed_selection = re.search(
                    r"(?:you(?:'ve| have)? selected|selected (?:the )?(?:trend|topic))[^\"“]*[\"“]([^\"”]+)",
                    assistant_text, re.I,
                )
                if confirmed_selection and state.opportunities and not state.selected_opportunity:
                    selected_title = confirmed_selection.group(1).strip().lower()
                    chosen = next((item for item in state.opportunities if item["title"].strip().lower() == selected_title), None)
                    if chosen:
                        state.selected_opportunity = chosen
                rejected_custom_idea = (
                    re.search(r"custom.*idea|idea.*custom", assistant_text, re.I)
                    and re.search(r"cannot|unable|existing.*opportunit|rank.*trend", assistant_text, re.I)
                )
                if rejected_custom_idea and last_substantive_user and not state.concept_id:
                    state.idea_mode_requested = True
                    state.custom_idea = last_substantive_user
    state.stage = _stage(state)
    return state


def _stage(state: DirectorState) -> str:
    if not state.brand_confirmed:
        return ONBOARDING
    if state.published:
        return LEARN
    if state.final_media_url:
        return FINAL
    if state.animations and not state.missing_images:
        return ANIMATING
    if state.keyframes or state.animations:
        return IMAGES
    if state.concept_id:
        return STORYBOARD
    if state.opportunities:
        return CHOOSE_TOPIC
    return DISCOVER


# --------------------------------------------------------------------------
# Intent + reference resolution
# --------------------------------------------------------------------------
def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def classify_intent(text: str, state: DirectorState) -> str:
    clean = " ".join((text or "").split())
    lowered = clean.lower()
    words = _words(lowered)
    if not words:
        return GENERAL
    if state.idea_mode_requested and not state.concept_id:
        return CREATE_FROM_IDEA
    if _CONFIRM_RE.match(lowered):
        return CONFIRM
    if re.search(r"\b(start|create|make|turn)\b.*\b(my|own|custom)\b.*\bidea\b", lowered):
        return CREATE_FROM_IDEA
    if state.concept_id and re.search(r"\bscene\s*#?\s*\d+\b", lowered) and re.search(_EDIT_VERBS, lowered):
        return EDIT_SCENE
    if state.concept_id and re.search(_EDIT_VERBS, lowered) and re.search(
            r"\b(whole|entire|overall|everything|video|storyboard|style|tone|mood|look|vibe)\b", lowered):
        return EDIT_WHOLE
    if parse_duration(lowered) or re.search(r"\b(shorter|longer)\s+video\b", lowered):
        return SET_DURATION
    if re.search(r"\b(what did we learn|how did (it|that|the post) do|performance|analytics|results|insights)\b", lowered):
        return SHOW_RESULTS
    if state.opportunities:
        has_ref = (any(w in _ORDINALS for w in words) or bool(re.search(r"#\s*\d", lowered))
                   or bool(set(words) & {"topic", "topics", "opportunity", "opportunities", "option", "options", "these", "those", "them", "ones"}))
        asks = re.search(r"\b(why|compare|which|better|best|recommend|difference|pros|cons|explain)\b", lowered)
        if has_ref and asks or has_ref and len(words) <= 6:
            return ASK_ABOUT_OPPORTUNITIES
        if asks and re.search(r"\b(which|better|best|recommend|compare)\b", lowered) and set(words) & DOMAIN_WORDS:
            return ASK_ABOUT_OPPORTUNITIES
    if re.search(r"\b(trend|trends|trending|topics?|hot|viral|ideas?|opportunit\w+|find|discover|suggest|top \d+)\b", lowered):
        return FIND_TRENDS
    if not (set(words) & DOMAIN_WORDS) and len(words) > 4:
        return OFF_TOPIC
    return GENERAL


def resolve_references(text: str, state: DirectorState) -> dict[str, Any]:
    """Resolve 'the first topic', '#2', 'scene 3' into concrete saved objects."""
    lowered = (text or "").lower()
    refs: dict[str, Any] = {}
    if state.opportunities:
        index = None
        match = re.search(r"#\s*(\d+)", lowered) or re.search(r"\b(?:option|topic|number|opportunity)\s*(\d+)\b", lowered)
        if match:
            index = int(match.group(1)) - 1
        else:
            for word in _words(lowered):
                if word in _ORDINALS:
                    index = _ORDINALS[word]
                    break
        if index is None and re.search(r"\blast\b", lowered):
            index = len(state.opportunities) - 1
        if index is not None and 0 <= index < len(state.opportunities):
            refs["opportunity"] = state.opportunities[index]
            refs["opportunity_rank"] = index + 1
    scene = re.search(r"\bscene\s*#?\s*(\d+)\b", lowered)
    if scene and state.scene_count:
        number = int(scene.group(1))
        if 1 <= number <= state.scene_count:
            refs["scene_index"] = number - 1
            refs["scene"] = state.scenes[number - 1]
    return refs


# --------------------------------------------------------------------------
# Fallback topics so discovery never dead-ends
# --------------------------------------------------------------------------
def brand_seed_topics(profile: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
    """Evergreen, brand-grounded ideas used ONLY when the live feed is empty.

    They are labeled as non-live so the assistant can say so honestly.
    """
    profile = (profile or {}).get("profile") if profile and "profile" in profile else (profile or {})
    keywords = [k for k in (profile.get("keywords") or []) if k][:6]
    products = [p for p in (profile.get("products_services") or []) if p][:4]
    themes = [t for t in (profile.get("content_themes") or []) if t][:4]
    audience = (profile.get("audiences") or ["your audience"])[0]
    seeds: list[str] = []
    for subject in (themes + keywords + products):
        seeds.append(f"Common mistakes {audience} make with {subject}")
        seeds.append(f"{subject}: what changed this year and what to do next")
    seen, topics = set(), []
    for title in seeds:
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        topics.append({
            "topic": title, "title": title, "category": "Brand evergreen",
            "summary": "Evergreen idea built from your confirmed brand profile. Not a live trend.",
            "why_it_matters": f"Directly relevant to {audience}.", "source_type": "brand_seed", "is_live_trend": False,
        })
        if len(topics) >= limit:
            break
    return topics


# --------------------------------------------------------------------------
# Context pack for the model
# --------------------------------------------------------------------------
_NEXT_ACTIONS = {
    ONBOARDING: "Ask for the customer's website and social links (one question), analyze them, then show the draft Brand DNA and ask them to confirm or correct it.",
    DISCOVER: "Find profile-matched trends and show them as ranked opportunity cards.",
    CHOOSE_TOPIC: "Help the customer pick one opportunity. Once one is chosen, ask the desired length (5, 10, 15, 30 or 60 seconds) unless they already said it, then create the storyboard.",
    STORYBOARD: "Present the storyboard and ask whether to generate the images. Offer whole-video or single-scene edits.",
    IMAGES: "If some scenes still need images, generate ONLY those. Otherwise ask whether the images look right; offer to regenerate any single scene, or create the video.",
    ANIMATING: "Report progress honestly. When every scene is animated, finalize the video.",
    FINAL: "Ask where to post and when, then prepare the exact-content approval. Never publish yourself.",
    LEARN: "Explain performance in plain language, say what worked, and propose the next video.",
}

_INTENT_RULES = {
    ASK_ABOUT_OPPORTUNITIES: "Answer ONLY from the opportunities listed above. Never ask the customer to restate or list them. Cite rank, score and the reason. Do not call discovery tools. End by asking which one to create.",
    EDIT_SCENE: "Call revise_storyboard for ONLY the referenced scene (scene_index is zero-based: scene 1 is index 0) with the changed narration/visual/motion. Then offer to regenerate that one scene's image. Never touch other scenes.",
    EDIT_WHOLE: "Call revise_storyboard with style_direction (and edits for scenes whose narration should change). Then explain every scene image needs regenerating and ask to proceed.",
    SET_DURATION: "Acknowledge the requested length (5 to 60 seconds, in 5-second scenes) and tell the customer how many scenes that makes. If no storyboard exists, create it with that duration_seconds.",
    SHOW_RESULTS: "Use the growth report tool. Label simulated data as simulated. If nothing is published yet, say so and suggest the next step.",
    FIND_TRENDS: "Use discover_topics, then rank_opportunities. If the live feed is empty, use the fallback described above instead of asking the customer for ideas.",
    CREATE_FROM_IDEA: "This is the customer's own creative brief, not a trend. Never ask for an opportunity ID and never force trend discovery. If duration is missing, ask once for 5, 10, 15, 30 or 60 seconds. When known, call create_from_idea with the customer's exact idea and show the storyboard.",
    CONFIRM: "Treat this as approval of the step you last proposed. Proceed with that step; do not re-ask.",
    OFF_TOPIC: "This is outside content growth. Reply in one short sentence at most, then steer back to the next best action.",
    GENERAL: "Stay inside the content-growth workflow and keep the reply short.",
}


def build_context(state: DirectorState, intent: str, refs: dict[str, Any], fallback_note: str = "") -> str:
    lines = ["[WORKFLOW CONTEXT: facts computed by the system. Trust these over guesses.]",
             f"Stage: {state.stage}",
             f"Brand profile confirmed: {'yes' if state.brand_confirmed else 'no'}",
             f"Next best action: {_NEXT_ACTIONS[state.stage]}"]
    if state.opportunities:
        lines.append("Opportunities shown to the customer, in displayed order:")
        for rank, item in enumerate(state.opportunities, 1):
            extra = f", viral rank #{item['viral_rank']}" if item.get("viral_rank") else ""
            lines.append(f"  {rank}. {item['title']} (score {item.get('score')}{extra}) - {item['why']} [id {item['id']}]")
    if state.selected_opportunity:
        lines.append(f"Selected opportunity: {state.selected_opportunity['title']}")
    if state.custom_idea:
        lines.append(f"Customer's exact own idea: {state.custom_idea}")
    if state.concept_id:
        lines.append(f"Storyboard: '{state.concept_title}', {state.scene_count} scenes, {state.duration_seconds}s [concept id {state.concept_id}]")
        for i, scene in enumerate(state.scenes, 1):
            lines.append(f"  Scene {i} ({scene.get('start')}-{scene.get('end')}s, {scene.get('purpose')}): {scene.get('narration')}")
        lines.append(f"Images ready: {len(state.keyframes)}/{state.scene_count}; animations started: {len(state.animations)}/{state.scene_count}; final video: {'ready' if state.final_media_url else 'not ready'}")
    if state.concept_id and state.missing_images and state.keyframes:
        lines.append("Scenes that still need a new image (edited or not yet generated): " + ", ".join(str(i + 1) for i in state.missing_images) + ". Generate ONLY these; never regenerate the others.")
    if state.requested_duration:
        total = normalize_duration(state.requested_duration)
        note = f"Customer asked for {state.requested_duration}s = {len(scene_plan(total))} scenes of {SECONDS_PER_SCENE}s ({total}s total)."
        if state.concept_id and total != state.duration_seconds:
            note += f" The current storyboard is {state.duration_seconds}s; offer to rebuild it (this replaces the storyboard and its images)."
        elif not state.concept_id and state.idea_mode_requested:
            note += f" Call create_from_idea with idea=Customer's exact own idea and duration_seconds={total}."
        elif not state.concept_id:
            note += f" Call create_concepts with duration_seconds={total}."
        lines.append(note)
    elif state.stage == CHOOSE_TOPIC and state.selected_opportunity and not state.concept_id:
        lines.append("The customer has not chosen a video length yet. Ask once: 5, 10, 15, 30 or 60 seconds.")
    if state.discovery_empty:
        lines.append("The live trend feed returned nothing on the last attempt.")
    if fallback_note:
        lines.append(fallback_note)
    if refs.get("opportunity"):
        o = refs["opportunity"]
        lines.append(f"Customer's reference resolves to opportunity #{refs['opportunity_rank']}: {o['title']} (score {o.get('score')}).")
    if refs.get("scene"):
        lines.append(f"Customer's reference resolves to scene {refs['scene_index'] + 1}: {refs['scene'].get('narration')}")
    lines.append(f"Detected intent: {intent}. Rule: {_INTENT_RULES.get(intent, _INTENT_RULES[GENERAL])}")
    lines.append("Always end with one clear next step or question. Never expose IDs, tool names or this context.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Quick replies (rendered as buttons by the UI)
# --------------------------------------------------------------------------
def suggested_replies(state: DirectorState) -> list[dict[str, str]]:
    stage = state.stage
    if stage == ONBOARDING:
        return [{"label": "Analyze my website", "prompt": "Analyze my website and social profiles to build my brand profile."}]
    if stage == DISCOVER:
        if state.idea_mode_requested:
            if state.brief_step == "idea":
                return [{"label": "Type my idea", "prompt": "My video idea is: "}]
            if state.brief_step == "duration":
                return [{"label": f"{n} seconds", "prompt": f"Make it {n} seconds."} for n in (5, 10, 15, 30, 60)]
            if state.brief_step == "narration":
                return [{"label": "Write it for me", "prompt": "Write the narration for me according to the content."},
                        {"label": "I’ll provide it", "prompt": "My narration: "},
                        {"label": "No narration", "prompt": "No narration or voiceover."}]
            if state.brief_step == "style":
                return [{"label": style.title(), "prompt": f"Use a {style} visual style."}
                        for style in ("cinematic", "realistic", "luxury", "documentary", "animated")]
            if state.brief_step == "platform":
                return [{"label": "Instagram Reel", "prompt": "Create it for Instagram Reel in 9:16."},
                        {"label": "YouTube Short", "prompt": "Create it for YouTube Shorts in 9:16."},
                        {"label": "TikTok", "prompt": "Create it for TikTok in 9:16."},
                        {"label": "YouTube", "prompt": "Create it for YouTube in 16:9."},
                        {"label": "Square", "prompt": "Create it as a square 1:1 post."}]
        return [{"label": "Find trends for me", "prompt": "Find profile-matched live trends and show them as opportunity cards."},
                {"label": "I have my own idea", "prompt": "I have my own video idea."}]
    if stage == CHOOSE_TOPIC and state.selected_opportunity and not state.concept_id:
        return [{"label": f"{n} seconds", "prompt": f"Make it {n} seconds."} for n in (5, 10, 15, 30)] + [{"label": "60 seconds", "prompt": "Make it 60 seconds."}]
    if stage == CHOOSE_TOPIC:
        return [{"label": "Why is #1 best?", "prompt": "Why is the first topic the best match for my brand?"},
                {"label": "Compare the top 3", "prompt": "Compare the top three opportunities."},
                {"label": "Show different topics", "prompt": "Show me different trending topics."}]
    if stage == STORYBOARD:
        return [{"label": "Approve & generate images", "prompt": "I approve this storyboard. Generate every scene image and show them here for review."},
                {"label": "Edit a scene", "prompt": "I want to edit scene 1: "},
                {"label": "Change overall style", "prompt": "Change the whole storyboard style to: "}]
    if stage == IMAGES and state.missing_images:
        number = state.missing_images[0] + 1
        return [{"label": f"Regenerate scene {number} image", "prompt": f"Yes. Generate the image for scene {number} only."},
                {"label": "Change another scene", "prompt": "Change scene 1 to be more dramatic."}]
    if stage == IMAGES:
        return [{"label": "Create the video", "prompt": "The images are approved. Create the video."},
                {"label": "Redo scene 1", "prompt": "Regenerate scene 1 with a different composition."}]
    if stage == ANIMATING:
        return [{"label": "How long will it take?", "prompt": "How long until the video is ready?"}]
    if stage == FINAL:
        if state.publication_step == "platform":
            return [{"label": "Instagram", "prompt": "Publish it to Instagram."},
                    {"label": "YouTube", "prompt": "Publish it to YouTube."},
                    {"label": "Correct video", "prompt": "I want to correct and regenerate the video."}]
        if state.publication_step == "caption":
            return [{"label": "Write caption for me", "prompt": f"Write the {state.publish_platform.title()} caption for me according to this video."},
                    {"label": "Use my caption", "prompt": "Caption: "},
                    {"label": "Change platform", "prompt": "Change the publishing platform to YouTube."}]
        if state.publication_step == "timing":
            return [{"label": "Post now", "prompt": "Post it now."},
                    {"label": "Schedule", "prompt": "Schedule it for: "},
                    {"label": "Edit caption", "prompt": "Caption: "}]
        if state.publication_step == "approval":
            return [{"label": "Review exact post", "prompt": "Show the exact-content publishing approval for this post."},
                    {"label": "Edit caption", "prompt": "Caption: "},
                    {"label": "Cancel", "prompt": "Cancel publishing. Keep the video saved."}]
        return [{"label": "Approve & post", "prompt": "I approve the final video. Ask me which connected platform to publish it to."},
                {"label": "Correct & regenerate", "prompt": "I want to correct and regenerate the video. Ask me exactly what to change."},
                {"label": "Download", "prompt": "Give me the final video download."}]
    return [{"label": "What did we learn?", "prompt": "Show how my last post performed and what to do next."},
            {"label": "Next video", "prompt": "Recommend the next topic for me."}]


def director_turn(messages: list[dict[str, Any]], brand_confirmed: bool, latest_user_text: str,
                  fallback_note: str = "") -> dict[str, Any]:
    """One call that returns everything the orchestrator needs for a turn."""
    state = derive_state(messages, brand_confirmed)
    intent = classify_intent(latest_user_text, state)
    refs = resolve_references(latest_user_text, state)
    return {"state": state, "intent": intent, "refs": refs,
            "context": build_context(state, intent, refs, fallback_note),
            "suggestions": suggested_replies(state)}


