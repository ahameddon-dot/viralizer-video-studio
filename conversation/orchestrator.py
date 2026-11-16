from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from autopilot_brand_analysis import analyze_brand_sources
from autopilot_growth import growth_dashboard
from autopilot_intelligence import apply_creative_brief, archive_other_opportunities, generate_concepts, get_brand_profile, get_concept, list_opportunities, rank_opportunities
from conversation import MODEL_ORCHESTRATION_ENABLED
from conversation.director import brand_seed_topics, director_turn
from conversation.onboarding import respond_onboarding
from conversation.redaction import redact
from conversation.registry import TOOL_REGISTRY
from conversation.store import append_message, attach_project, complete_tool_execution, get_conversation, propose_tool_execution
from conversation.tool_contracts import TOOL_DESCRIPTIONS, TOOL_SCHEMAS
from hybrid_project_state import ensure_autopilot_project, get_project_context, revise_storyboard_scene
from storyboard_plan import scene_patch
from mcp_outline_client import MCPOutlineError, get_hot_topics_from_mcp
from creatorthon_store import get_cached_category_topics, list_cached_category_topics
from viralizer_topic_source import fetch_v3_worldwide_topics


SYSTEM_INSTRUCTIONS = """You are Viralizer AI, a concise content-growth operator for individual creators and businesses.
Use tools for customer or project facts; never invent trends, viral scores, publications, metrics, or provider results.
Clearly distinguish live/provider data from simulated or unavailable data. Only take an action when the user asks for it.
Provider-cost actions require an approval card. Publishing always requires the existing exact-content human approval UI; you cannot approve or publish.
When a tool is blocked, explain the required human action. Keep answers practical and easy to understand.
Guide one visible step at a time: choose source, choose topic, choose video length (5 to 60 seconds), review the storyboard, generate the images, create video, approve exact post, publish, learn.
For trend discovery, use the confirmed profile category by default. If it has no current matches, offer exactly three useful paths: choose another category, show the hottest worldwide topics, or use the customer's own idea. When the customer chooses a category, call discover_topics with scope=category and that category. When they request blazing/hottest worldwide topics, call it with scope=worldwide_hot. Never describe category-selected or worldwide topics as profile-matched.
The customer may start with their own idea. A customer idea never requires a live trend or an existing opportunity ID. Ask the desired length if missing, then call create_from_idea with their exact idea. Clearly label it as customer-directed, not a live trend.
After ranking opportunities, ask the customer to select one. After they select, ask the length unless already stated, then call create_concepts with duration_seconds. After concept creation, present the storyboard and ask whether to generate the images.
The workflow context states how many scenes the storyboard has (N). When the customer says yes to the images, call generate_keyframe once for each scene index 0 to N-1 that still needs an image. Do not ask them to confirm each scene separately.
After every scene has an image, ask whether to create the video. If the user says create video, use these images, animate, proceed, confirm, or yes after image review, immediately call animate_scene once for each scene index 0 to N-1. Do not ask for confirmation in prose: the tool layer will render one grouped approval card.
To change a scene or the whole video, call revise_storyboard (free), then offer to regenerate ONLY the edited scenes' images. Never regenerate scenes the customer did not change.
Never call generate_keyframe again for a scene that already has an image unless the user explicitly asks to regenerate it or the context says it needs a new image.
After all scene animations are complete, immediately call finalize_video for the same concept. Do not return to image generation.
Never expose internal registry names, project IDs, tool names, or implementation details to the customer."""


CATEGORY_TERMS = {
    "food": {"food", "cooking", "cook", "recipe", "cuisine", "restaurant", "meal", "kitchen", "chef", "dish", "biryani", "grocery", "dining", "beverage", "drink"},
    "technology": {"technology", "tech", "software", "cloud", "coding", "developer", "digital", "computer", "ai", "robot"},
    "business": {"business", "finance", "market", "company", "startup", "commerce", "economy", "sales", "entrepreneur"},
    "entertainment": {"entertainment", "film", "movie", "music", "celebrity", "television", "streaming", "theatre"},
    "sports": {"sport", "sports", "football", "cricket", "tennis", "basketball", "racing", "athlete", "league", "tournament"},
    "fashion": {"fashion", "style", "apparel", "clothing", "designer", "runway", "beauty"},
    "travel": {"travel", "tourism", "destination", "hotel", "flight", "holiday", "vacation", "city guide"},
    "health": {"health", "medical", "medicine", "fitness", "wellness", "doctor", "hospital", "disease"},
    "pets": {"pet", "pets", "dog", "puppy", "cat", "animal", "veterinary"},
}


def _matches_category(item: dict[str, Any], category: str) -> bool:
    key = category.casefold().strip()
    terms = CATEGORY_TERMS.get(key, {key})
    structured = " ".join(str(item.get(field) or "") for field in ("category", "groups", "group_keys", "tags")).casefold()
    if key and (key in structured or any(re.search(rf"\b{re.escape(term)}\b", structured) for term in terms)):
        return True
    text = " ".join(str(item.get(field) or "") for field in ("topic", "title", "summary", "description", "video_idea")).casefold()
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)


def tool_definitions() -> list[dict[str, Any]]:
    return [{"type": "function", "name": name, "description": TOOL_DESCRIPTIONS[name], "parameters": schema, "strict": False}
            for name, schema in TOOL_SCHEMAS.items() if name in TOOL_REGISTRY]


def _output_text(payload: dict[str, Any]) -> str:
    if str(payload.get("output_text") or "").strip():
        return str(payload["output_text"]).strip()
    parts: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") == "message":
            parts.extend(str(content["text"]) for content in item.get("content") or []
                         if content.get("type") in {"output_text", "text"} and content.get("text"))
    return "\n".join(parts).strip()


def _function_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in payload.get("output") or [] if item.get("type") == "function_call"]


def _history(root: Path, customer_id: str, conversation: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    for message in (conversation.get("messages") or [])[-20:]:
        if message.get("role") == "tool":
            content = message.get("content") or {}
            output = content.get("output") or {}
            if output.get("status") == "completed" and content.get("tool") in {"rank_opportunities", "create_concepts", "create_from_idea"}:
                result.append({
                    "role": "user",
                    "content": "Saved Viralizer workflow state (use these exact IDs; do not show IDs to the customer):\n"
                    + json.dumps({"tool": content.get("tool"), "data": output.get("data") or {}}, ensure_ascii=False, default=str)[:30000],
                })
            continue
        if message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content") or {}
        text = str(content.get("text") or content.get("message") or "").strip()
        if message.get("role") == "assistant" and content.get("type") == "tool_result":
            state = {
                "completed_tool": content.get("tool"),
                "concept_id": (content.get("result") or {}).get("concept_id"),
                "scene_index": (content.get("result") or {}).get("scene_index"),
                "status": (content.get("result") or {}).get("status") or "completed",
                "media_url": content.get("media_url") or "",
            }
            text = (text + "\nSaved completed production state: " + json.dumps(state, default=str)).strip()
        if text:
            result.append({"role": message["role"], "content": text[:12000]})
    project_id = str(conversation.get("active_project_context_id") or "")
    if project_id:
        project = redact(get_project_context(root, customer_id, project_id))
        summary = {"id": project.get("id"), "concept_id": project.get("concept_id"), "revision": project.get("revision"), "active_storyboard": project.get("active_storyboard")}
        result.insert(0, {"role": "user", "content": "Active Viralizer project context:\n" + json.dumps(summary, ensure_ascii=False, default=str)[:30000]})
    return result


def _discovery_fallback(root: Path, customer_id: str, limit: int, source: Any) -> dict[str, Any]:
    """Never dead-end: reuse saved opportunities, else brand-grounded evergreen ideas. Always labeled honestly."""
    saved = list_opportunities(root, customer_id, limit)
    if saved:
        topics = [dict(item.get("source") or {}, title=item.get("title"), topic=item.get("title"), category=item.get("category")) for item in saved]
        return {"topics": topics[:limit], "provenance": {"data_source": "saved_fallback", "source": source, "provider_mode": "live", "is_simulated": False, "is_live_trend": False,
                "note": "The live trend feed returned nothing right now, so these are your previously ranked opportunities. Say that clearly and offer to retry the live feed later."}}
    seeds = brand_seed_topics(get_brand_profile(root, customer_id), limit)
    return {"topics": seeds, "provenance": {"data_source": "brand_seed", "source": source, "provider_mode": "live", "is_simulated": False, "is_live_trend": False,
            "note": "The live trend feed returned nothing right now. These are evergreen ideas built from the confirmed brand profile, not live trends. Say that clearly, then rank them."}}


def _revise_storyboard(root: Path, customer_id: str, arguments: dict[str, Any], actor_id: str) -> dict[str, Any]:
    """Apply per-scene or whole-video edits through the shared project revision history."""
    concept_id = str(arguments.get("concept_id") or "").strip()
    concept = get_concept(root, customer_id, concept_id)
    if not concept:
        raise ValueError("That storyboard was not found. Create a storyboard first.")
    storyboard = (concept.get("content") or {}).get("storyboard") or []
    style = str(arguments.get("style_direction") or "").strip()
    edits = [dict(item) for item in (arguments.get("edits") or []) if isinstance(item, dict)]
    if not edits and not style:
        raise ValueError("Tell me what to change: a scene, or the overall style.")
    targets: dict[int, dict[str, Any]] = {}
    for edit in edits:
        index = int(edit.get("scene_index", -1))
        if not 0 <= index < len(storyboard):
            raise ValueError(f"Scene {index + 1} does not exist. This storyboard has {len(storyboard)} scenes.")
        targets[index] = edit
    if style:
        for index in range(len(storyboard)):
            targets.setdefault(index, {"scene_index": index})
    project = ensure_autopilot_project(root, customer_id, concept_id, actor_id)
    revision, changed = int(project["revision"]), []
    summary = " ".join(str(arguments.get("summary") or "Chat storyboard revision").split())[:480]
    for index in sorted(targets):
        edit = targets[index]
        patch = scene_patch(storyboard[index], edit.get("narration"), edit.get("visual"), edit.get("motion"), style or None)
        if not patch:
            continue
        result = revise_storyboard_scene(root, customer_id, str(project["id"]), index, revision, patch, "user_chat", actor_id, summary, "")
        revision = int(result["project"]["revision"])
        changed.append(index)
    if not changed:
        raise ValueError("Nothing changed. Describe the new narration, visual, motion or style.")
    return {"concept": get_concept(root, customer_id, concept_id), "changed_scenes": changed, "stale_images": changed,
            "project": {"id": project["id"], "revision": revision}}


async def _execute(root: Path, customer_id: str, name: str, arguments: dict[str, Any], conversation_id: str = "", actor_id: str = "") -> Any:
    if name == "get_brand_profile":
        return get_brand_profile(root, customer_id)
    if name == "analyze_brand_sources":
        return await analyze_brand_sources(str(arguments.get("website_url") or ""), list(arguments.get("social_urls") or []))
    if name == "discover_topics":
        limit = max(1, min(25, int(arguments.get("limit") or 10)))
        brand = get_brand_profile(root, customer_id)
        profile = ((brand or {}).get("profile") or {})
        profile_category = str(profile.get("category") or "").strip()
        if not profile_category:
            profile_text = " ".join(str(value) for value in profile.values()).casefold()
            inferred = (("Food", ("food", "cook", "recipe", "cuisine", "restaurant", "meal")),
                        ("Pets", ("pet", "dog", "puppy", "cat", "animal")),
                        ("Technology", ("technology", "software", "cloud", "coding", " ai ")),
                        ("Fashion", ("fashion", "style", "apparel", "clothing")),
                        ("Travel", ("travel", "tourism", "hotel", "destination")),
                        ("Health", ("health", "fitness", "wellness", "medical")),
                        ("Business", ("business", "finance", "marketing", "commerce")))
            profile_category = next((label for label, words in inferred if any(word in profile_text for word in words)), "")
        # The V3 catalog uses broad category names (Food, Pets, Business, etc.)
        # while onboarding may save combined labels such as Food & Cooking.
        profile_category = profile_category.split("&", 1)[0].split("/", 1)[0].strip()
        scope = str(arguments.get("scope") or "profile").strip().lower()
        requested_category = " ".join(str(arguments.get("category") or "").split())[:80]
        category = requested_category if scope == "category" and requested_category else "" if scope == "worldwide_hot" else profile_category
        cached = get_cached_category_topics(root, category, allow_stale=True)[:limit] if category else []
        if category and not cached:
            cached = [item for item in list_cached_category_topics(root, allow_stale=True)
                      if _matches_category(item, category)][:limit]
        category_catalog_verified = bool(cached)
        if cached:
            topics, source = cached, f"Viralizer V3 {category} catalog"
        else:
            # Some older V3 deployments ignore the category query parameter.
            # Pull a larger candidate set, then enforce the category locally.
            try:
                topics, source = await fetch_v3_worldwide_topics(50 if category else limit, category=category)
            except MCPOutlineError as exc:
                topics, source = [], "Viralizer V3 temporarily unavailable"
                provider_error = " ".join(str(exc).split())[:240]
        decorated = []
        for raw in topics:
            item = dict(raw)
            if category and not category_catalog_verified and not _matches_category(item, category):
                continue
            if category_catalog_verified and category and not item.get("category"):
                item["category"] = category
            if scope == "worldwide_hot":
                item["user_selected_worldwide"] = True
            elif scope == "category" and requested_category:
                item["user_selected_category"] = True
            elif category and (category_catalog_verified or category.casefold() in str(item.get("category") or "").casefold()):
                item["profile_category_verified"] = True
            decorated.append(item)
            if len(decorated) >= limit:
                break
        discovery = ({"topics": decorated, "provenance": {"data_source": "viralizer_v3", "source": source, "provider_mode": "live", "is_simulated": False,
                                                          "scope": scope, "category": category, "profile_matched": scope == "profile"}}
                     if topics else _discovery_fallback(root, customer_id, limit, source))
        if not topics and 'provider_error' in locals():
            discovery = {"topics": [], "opportunities": [], "provenance": {
                "data_source": "viralizer_v3", "source": source, "provider_mode": "unavailable",
                "is_simulated": False, "scope": scope, "category": category,
                "profile_matched": False, "provider_error": provider_error,
            }}
        # Discovery is a worldwide feed, not a personalized result. Enforce the
        # customer relevance gate here so the model can never describe raw V3
        # topics as "profile matched" when it skips the separate ranking tool.
        if brand and brand.get("status") == "confirmed":
            candidates = discovery.get("topics") or []
            opportunities = (rank_opportunities(root, customer_id, {"topics": candidates, "limit": limit})
                             if candidates else [])
            archive_other_opportunities(root, customer_id, [str(item["id"]) for item in opportunities])
            verified_topics = []
            for item in opportunities:
                verified_topics.append(dict(
                    item.get("source") or {},
                    topic=item["title"], title=item["title"], category=item.get("category") or "",
                    opportunity_id=item["id"], profile_match_score=item["components"]["brand_relevance"],
                ))
            discovery["topics"] = verified_topics
            discovery["opportunities"] = opportunities
            discovery["provenance"]["profile_match_verified"] = True
            discovery["provenance"]["rejected_unrelated_count"] = max(0, len(topics) - len(verified_topics))
        return discovery
    if name == "rank_opportunities":
        opportunities = rank_opportunities(root, customer_id, {"topics": arguments.get("topics") or [], "limit": arguments.get("limit") or 5})
        archive_other_opportunities(root, customer_id, [str(item["id"]) for item in opportunities])
        return {"opportunities": opportunities}
    if name == "create_from_idea":
        idea = " ".join(str(arguments.get("idea") or "").split())[:500]
        if len(idea) < 3:
            raise ValueError("Tell me the video idea you want to create.")
        ranked = rank_opportunities(root, customer_id, {"topics": [{
            "topic": idea, "title": idea, "category": "Customer idea",
            "summary": "Customer-directed creative brief.",
            "why_it_matters": str(arguments.get("goal") or "Create the customer's requested video.")[:500],
            "source_type": "user_idea", "user_directed": True, "is_live_trend": False,
        }], "limit": 1})
        if not ranked:
            raise ValueError("The idea could not be saved. Confirm the Brand Profile, then try again.")
        opportunity = ranked[0]
        concepts = generate_concepts(root, customer_id, {
            "opportunity_id": opportunity["id"], "platform": arguments.get("platform") or "instagram",
            "goal": arguments.get("cta") or "", "duration_seconds": arguments.get("duration_seconds") or 15,
        })
        concepts = apply_creative_brief(root, customer_id, concepts, {
            "narration_mode": arguments.get("narration_mode") or "ai",
            "narration_text": arguments.get("narration_text") or "",
            "visual_style": arguments.get("visual_style") or "",
            "aspect_ratio": arguments.get("aspect_ratio") or "9:16",
        })
        project = None
        if concepts:
            project = ensure_autopilot_project(root, customer_id, str(concepts[0]["id"]), actor_id)
            if conversation_id:
                attach_project(root, customer_id, conversation_id, str(project["id"]))
        return {"opportunity": opportunity, "concepts": concepts,
                "provenance": {"source_type": "user_idea", "is_live_trend": False, "customer_directed": True},
                "project": {"id": project["id"], "revision": project["revision"]} if project else None}
    if name == "create_concepts":
        requested = str(arguments.get("opportunity_id") or "").strip()
        opportunities = list_opportunities(root, customer_id, 25)
        opportunity_id = requested
        if requested.isdigit() and 1 <= int(requested) <= len(opportunities):
            opportunity_id = str(opportunities[int(requested) - 1]["id"])
        elif requested and not any(str(item.get("id")) == requested for item in opportunities):
            needle = requested.casefold()
            matched = next((item for item in opportunities if needle in str(item.get("title") or "").casefold() or str(item.get("title") or "").casefold() in needle), None)
            if matched:
                opportunity_id = str(matched["id"])
        if not opportunity_id or not any(str(item.get("id")) == opportunity_id for item in opportunities):
            raise ValueError("Select one of the displayed opportunities before creating the storyboard.")
        concepts = generate_concepts(root, customer_id, {"opportunity_id": opportunity_id, "platform": arguments.get("platform") or "instagram", "goal": arguments.get("goal") or "", "duration_seconds": arguments.get("duration_seconds") or 15})
        project = None
        if concepts:
            project = ensure_autopilot_project(root, customer_id, str(concepts[0]["id"]), actor_id)
            if conversation_id:
                attach_project(root, customer_id, conversation_id, str(project["id"]))
        return {"concepts": concepts, "project": {"id": project["id"], "revision": project["revision"]} if project else None}
    if name == "revise_storyboard":
        return _revise_storyboard(root, customer_id, arguments, actor_id)
    if name == "get_growth_report":
        return growth_dashboard(root, customer_id)
    raise ValueError("This action requires its dedicated approved workflow.")


def _next_suggestions(root: Path, customer_id: str, conversation_id: str, brand_confirmed: bool, latest_text: str) -> list[dict[str, str]]:
    """Quick replies for the state AFTER this turn's tools ran."""
    try:
        fresh = get_conversation(root, customer_id, conversation_id)
        return director_turn(fresh.get("messages") or [], brand_confirmed, latest_text)["suggestions"][:4]
    except Exception:
        return []


def _no_match_suggestions() -> list[dict[str, str]]:
    return [
        {"label": "Choose another category", "prompt": "Show me the available trend categories."},
        {"label": "Show hottest worldwide", "prompt": "Show me the hottest worldwide topics across all categories."},
        {"label": "Use my own idea", "prompt": "I want to start with my own video idea."},
    ]


def _normalize_publication_arguments(arguments: dict[str, Any], selected: dict[str, Any] | None,
                                     concept_title: str) -> dict[str, Any]:
    """Keep alternate-category/worldwide post copy grounded in its actual topic."""
    result = dict(arguments)
    scope = str((selected or {}).get("scope") or "profile")
    if scope in {"category", "worldwide_hot"}:
        topic = " ".join(str((selected or {}).get("title") or concept_title or "Viralizer video").split())[:200]
        result["title"] = topic
        result["caption"] = f"{topic} — the key update, why it matters, and what to watch next."
    return result


async def _deterministic_discovery_turn(root: Path, customer_id: str, conversation_id: str, actor_id: str,
                                        message_id: str, arguments: dict[str, Any], label: str) -> dict[str, Any]:
    call_id = f"discover_{uuid.uuid4().hex}"
    idem = hashlib.sha256(f"{conversation_id}:{message_id}:discover:{json.dumps(arguments, sort_keys=True)}".encode()).hexdigest()
    execution = propose_tool_execution(root, customer_id, conversation_id, "discover_topics", arguments,
                                       idem, call_id, message_id=message_id, cost_confirmed=False)
    result = redact(await _execute(root, customer_id, "discover_topics", arguments, conversation_id, actor_id))
    complete_tool_execution(root, customer_id, execution["id"], result=result)
    append_message(root, customer_id, conversation_id, "tool", {
        "tool": "discover_topics", "call_id": call_id,
        "output": {"status": "completed", "tool": "discover_topics", "data": result},
    })
    opportunities = result.get("opportunities") or []
    if opportunities:
        suggestions = _next_suggestions(root, customer_id, conversation_id, True, label)
        text = f"I found {len(opportunities)} verified {label} opportunities from Viralizer V3. Choose one topic below to create your video."
        intent = "verified_trends"
    else:
        suggestions = _no_match_suggestions()
        unavailable = (result.get("provenance") or {}).get("provider_mode") == "unavailable"
        text = ("Viralizer V3 is temporarily unavailable, so I could not verify live topics right now. You can try another category, retry the hottest worldwide feed, or start with your own idea."
                if unavailable else
                "There are no current verified trends in your profile niche. I did not replace them with unrelated topics. You can choose another category, see the hottest worldwide topics, or start with your own idea.")
        intent = "no_verified_brand_match"
    message = append_message(root, customer_id, conversation_id, "assistant", {
        "type": "text", "text": text, "provider": "viralizer_workflow", "model": "deterministic",
        "suggestions": suggestions, "stage": "choose_topic" if opportunities else "discover", "intent": intent,
    })
    return {"message": message, "approval_cards": [], "model": "deterministic",
            "provider": "viralizer_workflow", "suggestions": suggestions}


async def respond(root: Path, customer_id: str, conversation_id: str, actor_id: str, message_id: str = "", cost_confirmed: bool = False,
                  client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    conversation = get_conversation(root, customer_id, conversation_id)
    if message_id and not any(item["id"] == message_id and item["role"] == "user" for item in conversation.get("messages") or []):
        raise ValueError("The user message was not found in this conversation.")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_CONVERSATION_MODEL", "").strip() or os.getenv("OPENAI_MODEL", "").strip() or "gpt-4.1-mini"
    brand = get_brand_profile(root, customer_id)
    latest_text = ""
    for item in reversed(conversation.get("messages") or []):
        if item.get("role") == "user" and (not message_id or item.get("id") == message_id):
            latest_text = str((item.get("content") or {}).get("text") or (item.get("content") or {}).get("message") or "")
            break
    directed = director_turn(conversation.get("messages") or [], bool(brand and brand.get("status") == "confirmed"), latest_text)
    if directed["state"].stage == "onboarding":
        return await respond_onboarding(root, customer_id, conversation_id, conversation.get("messages") or [], latest_text)
    if not MODEL_ORCHESTRATION_ENABLED:
        raise RuntimeError("Viralizer AI is not configured on this server.")
    if re.search(r"available trend categories|choose another category", latest_text, re.I):
        categories = ("Food", "Technology", "Business", "Entertainment", "Sports", "Fashion", "Travel", "Health", "Pets")
        suggestions = [{"label": category, "prompt": f"Show current {category} trends from Viralizer V3."} for category in categories]
        message = append_message(root, customer_id, conversation_id, "assistant", {
            "type": "text", "text": "Which category do you want to explore? Choose one below.",
            "provider": "viralizer_workflow", "model": "deterministic", "suggestions": suggestions,
            "stage": "discover", "intent": "choose_trend_category",
        })
        return {"message": message, "approval_cards": [], "model": "deterministic",
                "provider": "viralizer_workflow", "suggestions": suggestions}
    category_request = re.search(r"show current\s+(.+?)\s+trends from Viralizer V3", latest_text, re.I)
    if category_request:
        category = " ".join(category_request.group(1).split())[:80]
        return await _deterministic_discovery_turn(root, customer_id, conversation_id, actor_id, message_id,
                                                   {"limit": 10, "scope": "category", "category": category},
                                                   f"{category} category")
    if re.search(r"hottest worldwide|blazing topics worldwide", latest_text, re.I):
        return await _deterministic_discovery_turn(root, customer_id, conversation_id, actor_id, message_id,
                                                   {"limit": 10, "scope": "worldwide_hot"}, "hottest worldwide")
    if re.search(r"find (?:profile-matched )?(?:live )?trends|find trends for me", latest_text, re.I):
        return await _deterministic_discovery_turn(root, customer_id, conversation_id, actor_id, message_id,
                                                   {"limit": 10, "scope": "profile"}, "profile-matched")
    instructions = SYSTEM_INSTRUCTIONS + "\n\n" + directed["context"]
    directed_state = directed["state"]
    if directed_state.stage == "final_review" and directed_state.publication_step in {"platform", "caption", "timing"}:
        copy = {
            "platform": "Your final video is approved. Where should I publish it? Choose one of your connected accounts.",
            "caption": f"{directed_state.publish_platform.title()} selected. What caption should I use? You can write it, or I can create one from the approved video.",
            "timing": "When should I publish it—now or at a specific date and time? I’ll show the exact post for one final approval before anything is sent.",
        }
        suggestions = directed["suggestions"]
        message = append_message(root, customer_id, conversation_id, "assistant", {
            "type": "text", "text": copy[directed_state.publication_step],
            "provider": "viralizer_workflow", "model": "deterministic", "suggestions": suggestions,
            "stage": directed_state.stage, "intent": "prepare_publication",
            "flow_step": directed_state.publication_step,
        })
        return {"message": message, "approval_cards": [], "model": "deterministic",
                "provider": "viralizer_workflow", "suggestions": suggestions}
    if directed["intent"] == "create_from_idea" and directed_state.idea_mode_requested:
        step_copy = {
            "idea": "Describe the video idea in your own words. I’ll keep it exactly as your creative brief.",
            "duration": "How long should the video be?",
            "narration": "How should narration work for this video?",
            "style": "What visual style should I use?",
            "platform": "Which platform and video size should I create it for?",
        }
        if directed_state.brief_step != "ready":
            suggestions = directed["suggestions"]
            message = append_message(root, customer_id, conversation_id, "assistant", {
                "type": "text",
                "text": step_copy[directed_state.brief_step],
                "provider": "viralizer_workflow", "model": "deterministic", "suggestions": suggestions,
                "stage": directed_state.stage, "intent": directed["intent"], "flow_step": directed_state.brief_step,
            })
            return {"message": message, "approval_cards": [], "model": "deterministic",
                    "provider": "viralizer_workflow", "suggestions": suggestions}
        call_id = f"idea_{uuid.uuid4().hex}"
        narration = (directed_state.narration_text if directed_state.narration_mode == "custom"
                     else "Write narration according to the content" if directed_state.narration_mode == "ai"
                     else "No narration or voiceover")
        creative_goal = (f"Narration: {narration}. Visual style: {directed_state.visual_style}. "
                         f"Format: {directed_state.target_platform} {directed_state.aspect_ratio}.")
        arguments = {"idea": directed_state.custom_idea, "duration_seconds": directed_state.requested_duration,
                     "platform": directed_state.target_platform, "goal": creative_goal,
                     "narration_mode": directed_state.narration_mode, "narration_text": directed_state.narration_text,
                     "visual_style": directed_state.visual_style, "aspect_ratio": directed_state.aspect_ratio}
        idem = hashlib.sha256(f"{conversation_id}:{directed_state.custom_idea}:{directed_state.requested_duration}".encode()).hexdigest()
        execution = propose_tool_execution(root, customer_id, conversation_id, "create_from_idea", arguments,
                                           idem, call_id, message_id=message_id, cost_confirmed=False)
        result = redact(await _execute(root, customer_id, "create_from_idea", arguments, conversation_id, actor_id))
        complete_tool_execution(root, customer_id, execution["id"], result=result)
        tool_output = {"status": "completed", "tool": "create_from_idea", "data": result}
        append_message(root, customer_id, conversation_id, "tool", {
            "tool": "create_from_idea", "call_id": call_id, "output": tool_output})
        suggestions = _next_suggestions(root, customer_id, conversation_id,
                                        bool(brand and brand.get("status") == "confirmed"), latest_text)
        message = append_message(root, customer_id, conversation_id, "assistant", {
            "type": "text", "text": "I created the complete storyboard from your brief. Review every scene, hook, narration, visual and motion below. You can edit one field, one scene, or the whole story before generating images.",
            "provider": "viralizer_workflow", "model": "deterministic", "suggestions": suggestions,
            "stage": "storyboard_review", "intent": directed["intent"],
        })
        return {"message": message, "approval_cards": [], "model": "deterministic",
                "provider": "viralizer_workflow", "suggestions": suggestions}
    owns_client, http = client is None, client or httpx.AsyncClient(timeout=60.0)
    approvals: list[dict[str, Any]] = []
    response_id = ""
    try:
        body: dict[str, Any] = {"model": model, "instructions": instructions, "input": _history(root, customer_id, conversation), "tools": tool_definitions(), "max_output_tokens": 1400}
        for _ in range(4):
            response = await http.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body)
            if response.status_code >= 400:
                raise RuntimeError(f"The AI provider rejected the request ({response.status_code}).")
            payload = response.json(); response_id = str(payload.get("id") or response_id)
            calls = _function_calls(payload)
            if not calls:
                text = _output_text(payload) or "I could not produce a response. Please try again."
                suggestions = _next_suggestions(root, customer_id, conversation_id, bool(brand and brand.get("status") == "confirmed"), latest_text)
                message = append_message(root, customer_id, conversation_id, "assistant", {"type": "text", "text": text, "provider": "openai", "model": model, "response_id": response_id, "suggestions": suggestions, "stage": directed["state"].stage, "intent": directed["intent"]})
                return {"message": message, "approval_cards": approvals, "model": model, "provider": "openai", "suggestions": suggestions}
            outputs = []
            no_verified_matches = False
            for call in calls:
                name, call_id = str(call.get("name") or ""), str(call.get("call_id") or uuid.uuid4().hex)
                try:
                    arguments = json.loads(call.get("arguments") or "{}")
                except (TypeError, ValueError):
                    arguments = {}
                if name == "prepare_publication":
                    arguments = _normalize_publication_arguments(
                        arguments, directed_state.selected_opportunity, directed_state.concept_title)
                idem = hashlib.sha256(f"{conversation_id}:{call_id}:{name}".encode()).hexdigest()
                execution = propose_tool_execution(root, customer_id, conversation_id, name, arguments, idem, call_id, message_id=message_id, cost_confirmed=cost_confirmed)
                decision = execution.get("authorization") or {}
                if decision.get("execution_enabled"):
                    try:
                        result = redact(await _execute(root, customer_id, name, arguments, conversation_id, actor_id))
                        complete_tool_execution(root, customer_id, execution["id"], result=result)
                        tool_output = {"status": "completed", "tool": name, "data": result}
                        if name in {"discover_topics", "rank_opportunities"} and not (result.get("opportunities") or []):
                            no_verified_matches = True
                    except (ValueError, RuntimeError) as exc:
                        safe_message = " ".join(str(exc).split())[:300] or "The workflow step could not complete."
                        error = {"code": "tool_failed", "message": safe_message}
                        complete_tool_execution(root, customer_id, execution["id"], error=error)
                        tool_output = {"status": "failed", "tool": name, "error": error["message"]}
                    except Exception:
                        error = {"code": "tool_failed", "message": "The workflow step could not complete. Please retry or choose another saved opportunity."}
                        complete_tool_execution(root, customer_id, execution["id"], error=error)
                        tool_output = {"status": "failed", "tool": name, "error": error["message"]}
                else:
                    card = {"execution_id": execution["id"], "tool": name, "code": decision.get("code"), "reason": decision.get("reason"), "cost": execution.get("cost_class"), "approval": execution.get("approval_status"), "arguments": redact(arguments)}
                    approvals.append(card); tool_output = {"status": "approval_required", **card}
                append_message(root, customer_id, conversation_id, "tool", {"tool": name, "call_id": call_id, "output": tool_output})
                outputs.append({"type": "function_call_output", "call_id": call_id, "output": json.dumps(tool_output, ensure_ascii=False, default=str)[:60000]})
            if no_verified_matches:
                suggestions = _no_match_suggestions()
                message = append_message(root, customer_id, conversation_id, "assistant", {
                    "type": "text",
                    "text": "There are no current verified trends in your profile niche. I did not replace them with unrelated topics. You can choose another category, see the hottest worldwide topics, or start with your own idea.",
                    "provider": "viralizer_workflow", "model": "deterministic", "suggestions": suggestions,
                    "stage": "discover", "intent": "no_verified_brand_match",
                })
                return {"message": message, "approval_cards": approvals, "model": "deterministic",
                        "provider": "viralizer_workflow", "suggestions": suggestions}
            body = {"model": model, "instructions": instructions, "previous_response_id": response_id, "input": outputs, "tools": tool_definitions(), "max_output_tokens": 1400}
        message = append_message(root, customer_id, conversation_id, "assistant", {"type": "text", "text": "I reached the action limit for one turn. Review the completed steps and continue in a new message.", "provider": "openai", "model": model})
        return {"message": message, "approval_cards": approvals, "model": model, "provider": "openai"}
    finally:
        if owns_client:
            await http.aclose()
