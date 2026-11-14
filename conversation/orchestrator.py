from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from autopilot_brand_analysis import analyze_brand_sources
from autopilot_growth import growth_dashboard
from autopilot_intelligence import generate_concepts, get_brand_profile, list_opportunities, rank_opportunities
from conversation import MODEL_ORCHESTRATION_ENABLED
from conversation.redaction import redact
from conversation.registry import TOOL_REGISTRY
from conversation.store import append_message, attach_project, complete_tool_execution, get_conversation, propose_tool_execution
from conversation.tool_contracts import TOOL_DESCRIPTIONS, TOOL_SCHEMAS
from hybrid_project_state import ensure_autopilot_project, get_project_context
from mcp_outline_client import get_hot_topics_from_mcp
from viralizer_topic_source import fetch_v3_worldwide_topics


SYSTEM_INSTRUCTIONS = """You are Viralizer AI, a concise content-growth operator for individual creators and businesses.
Use tools for customer or project facts; never invent trends, viral scores, publications, metrics, or provider results.
Clearly distinguish live/provider data from simulated or unavailable data. Only take an action when the user asks for it.
Provider-cost actions require an approval card. Publishing always requires the existing exact-content human approval UI; you cannot approve or publish.
When a tool is blocked, explain the required human action. Keep answers practical and easy to understand.
Guide one visible step at a time: choose source, choose topic, review three-scene storyboard, generate all three images, create video, approve exact post, publish, learn.
After ranking opportunities, ask the customer to select one. After concept creation, present the storyboard and ask whether to generate all three images.
When the customer says yes to all three images, call generate_keyframe once for each scene index 0, 1 and 2. Do not ask them to confirm each scene separately.
After three keyframes exist, ask whether to create the video. If the user says create video, use these images, animate, proceed, confirm, or yes after image review, immediately call animate_scene once for each scene index 0, 1 and 2. Do not ask for confirmation in prose: the tool layer will render one grouped approval card.
Never call generate_keyframe again after scenes 1, 2 and 3 have succeeded unless the user explicitly asks to regenerate an image.
After all three animation results are complete, immediately call finalize_video for the same concept. Do not return to image generation.
Never expose internal registry names, project IDs, tool names, or implementation details to the customer."""


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
            if output.get("status") == "completed" and content.get("tool") in {"rank_opportunities", "create_concepts"}:
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


async def _execute(root: Path, customer_id: str, name: str, arguments: dict[str, Any], conversation_id: str = "", actor_id: str = "") -> Any:
    if name == "get_brand_profile":
        return get_brand_profile(root, customer_id)
    if name == "analyze_brand_sources":
        return await analyze_brand_sources(str(arguments.get("website_url") or ""), list(arguments.get("social_urls") or []))
    if name == "discover_topics":
        limit = max(1, min(25, int(arguments.get("limit") or 10)))
        topics, source = await fetch_v3_worldwide_topics(limit)
        return {"topics": topics[:limit], "provenance": {"data_source": "viralizer_v3", "source": source, "provider_mode": "live", "is_simulated": False}}
    if name == "rank_opportunities":
        return {"opportunities": rank_opportunities(root, customer_id, {"topics": arguments.get("topics") or [], "limit": arguments.get("limit") or 5})}
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
        concepts = generate_concepts(root, customer_id, {"opportunity_id": opportunity_id, "platform": arguments.get("platform") or "instagram", "goal": arguments.get("goal") or ""})
        project = None
        if concepts:
            project = ensure_autopilot_project(root, customer_id, str(concepts[0]["id"]), actor_id)
            if conversation_id:
                attach_project(root, customer_id, conversation_id, str(project["id"]))
        return {"concepts": concepts, "project": {"id": project["id"], "revision": project["revision"]} if project else None}
    if name == "get_growth_report":
        return growth_dashboard(root, customer_id)
    raise ValueError("This action requires its dedicated approved workflow.")


async def respond(root: Path, customer_id: str, conversation_id: str, actor_id: str, message_id: str = "", cost_confirmed: bool = False,
                  client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    if not MODEL_ORCHESTRATION_ENABLED:
        raise RuntimeError("Viralizer AI is not configured on this server.")
    conversation = get_conversation(root, customer_id, conversation_id)
    if message_id and not any(item["id"] == message_id and item["role"] == "user" for item in conversation.get("messages") or []):
        raise ValueError("The user message was not found in this conversation.")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_CONVERSATION_MODEL", "").strip() or os.getenv("OPENAI_MODEL", "").strip() or "gpt-4.1-mini"
    owns_client, http = client is None, client or httpx.AsyncClient(timeout=60.0)
    approvals: list[dict[str, Any]] = []
    response_id = ""
    try:
        body: dict[str, Any] = {"model": model, "instructions": SYSTEM_INSTRUCTIONS, "input": _history(root, customer_id, conversation), "tools": tool_definitions(), "max_output_tokens": 1400}
        for _ in range(4):
            response = await http.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body)
            if response.status_code >= 400:
                raise RuntimeError(f"The AI provider rejected the request ({response.status_code}).")
            payload = response.json(); response_id = str(payload.get("id") or response_id)
            calls = _function_calls(payload)
            if not calls:
                text = _output_text(payload) or "I could not produce a response. Please try again."
                message = append_message(root, customer_id, conversation_id, "assistant", {"type": "text", "text": text, "provider": "openai", "model": model, "response_id": response_id})
                return {"message": message, "approval_cards": approvals, "model": model, "provider": "openai"}
            outputs = []
            for call in calls:
                name, call_id = str(call.get("name") or ""), str(call.get("call_id") or uuid.uuid4().hex)
                try:
                    arguments = json.loads(call.get("arguments") or "{}")
                except (TypeError, ValueError):
                    arguments = {}
                idem = hashlib.sha256(f"{conversation_id}:{call_id}:{name}".encode()).hexdigest()
                execution = propose_tool_execution(root, customer_id, conversation_id, name, arguments, idem, call_id, message_id=message_id, cost_confirmed=cost_confirmed)
                decision = execution.get("authorization") or {}
                if decision.get("execution_enabled"):
                    try:
                        result = redact(await _execute(root, customer_id, name, arguments, conversation_id, actor_id))
                        complete_tool_execution(root, customer_id, execution["id"], result=result)
                        tool_output = {"status": "completed", "tool": name, "data": result}
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
            body = {"model": model, "instructions": SYSTEM_INSTRUCTIONS, "previous_response_id": response_id, "input": outputs, "tools": tool_definitions(), "max_output_tokens": 1400}
        message = append_message(root, customer_id, conversation_id, "assistant", {"type": "text", "text": "I reached the action limit for one turn. Review the completed steps and continue in a new message.", "provider": "openai", "model": model})
        return {"message": message, "approval_cards": approvals, "model": model, "provider": "openai"}
    finally:
        if owns_client:
            await http.aclose()
