import json
import os
import re
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class MCPOutlineError(RuntimeError):
    pass


def _leaf_errors(exc: BaseException) -> list[BaseException]:
    nested = getattr(exc, "exceptions", None)
    if nested:
        leaves: list[BaseException] = []
        for child in nested:
            leaves.extend(_leaf_errors(child))
        return leaves
    return [exc]


def _connection_error(exc: BaseException, url: str) -> str:
    leaves = _leaf_errors(exc)
    if any(isinstance(item, httpx.ConnectError) for item in leaves):
        return (
            f"Cannot connect to the MCP server at {url}. Check that the MCP server is "
            "running and that MCP_SERVER_URL uses the correct host, port, and /mcp path."
        )
    if any(isinstance(item, httpx.TimeoutException) for item in leaves):
        return f"The MCP server at {url} did not respond within 30 seconds."
    details = "; ".join(dict.fromkeys(str(item) for item in leaves if str(item)))
    return details or str(exc)


def _mcp_config() -> tuple[str, dict[str, str]]:
    url = os.getenv("MCP_SERVER_URL", "").strip()
    if not url:
        raise MCPOutlineError("MCP_SERVER_URL must be configured in .env.")
    headers: dict[str, str] = {}
    api_key = os.getenv("MCP_API_KEY", "").strip()
    token = os.getenv("MCP_AUTH_TOKEN", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return url, headers


def _json_from_text(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        start = value.find("{")
        if start >= 0:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(value[start:])
            except json.JSONDecodeError:
                raise MCPOutlineError(
                    f"The MCP tool returned an unexpected response: {value[:180]}"
                ) from exc
        else:
            raise MCPOutlineError(
                f"The MCP tool returned an unexpected response: {value[:180]}"
            ) from exc
    if not isinstance(parsed, dict):
        raise MCPOutlineError("The MCP tool must return a JSON object containing the outline.")
    return parsed


def _extract_outline(result: Any) -> dict[str, Any]:
    if getattr(result, "isError", False):
        message = " ".join(
            str(getattr(item, "text", "")) for item in getattr(result, "content", [])
        ).strip()
        if "insufficient credits" in message.lower():
            raise MCPOutlineError(
                "Viralizer MCP rejected this request with an insufficient-credit error. "
                "The MCP server mapped the API key to owner 'internal'; if your plan is unlimited, "
                "Viralizer must correct that API-key owner mapping or unlimited-plan credit check."
            )
        raise MCPOutlineError(message or "The MCP tool reported an error.")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        for key in ("outline", "result", "content"):
            if isinstance(structured.get(key), dict):
                return structured[key]
        return structured
    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if text:
            return _json_from_text(text)
    raise MCPOutlineError("The MCP tool returned no usable outline content.")


def _viralizer_outline(payload: dict[str, Any], requested_topic: str) -> dict[str, Any]:
    analysis = payload.get("topicAnalysis")
    if not isinstance(analysis, list):
        payload.setdefault("topic", requested_topic)
        return payload

    sections = {
        item.get("key"): item.get("data", {})
        for item in analysis
        if isinstance(item, dict) and item.get("key")
    }
    topic = str(sections.get("topic", {}).get("topic", requested_topic))
    if ":" in topic and topic.lower().startswith("deep dive"):
        topic = topic.split(":", 1)[1].strip()

    metrics = {
        str(item.get("label", "")): str(item.get("value", ""))
        for item in sections.get("metrics", {}).get("metrics", [])
        if isinstance(item, dict)
    }
    summary_parts = []
    for block in sections.get("metricsSummary", {}).get("metricsSummary", []):
        for section in block.get("sections", []) if isinstance(block, dict) else []:
            value = str(section.get("text", "")).strip()
            if value and value not in ("Overview", "Performance"):
                summary_parts.append(value)

    outline = sections.get("contentOutline", {}).get("contentOutline", {})
    alternatives = sections.get("alternativeIdeas", {}).get("alternativeIdeas", [])
    def collect_hooks(value: Any) -> list[str]:
        """Accept the different hook shapes returned by Viralizer reports."""
        found: list[str] = []
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            if cleaned:
                found.append(cleaned)
        elif isinstance(value, list):
            for item in value:
                found.extend(collect_hooks(item))
        elif isinstance(value, dict):
            preferred = ("text", "hook", "title", "value", "data")
            matched = False
            for key in preferred:
                if key in value:
                    found.extend(collect_hooks(value[key]))
                    matched = True
            if not matched:
                for item in value.values():
                    found.extend(collect_hooks(item))
        return found

    hook_sources = []
    for key, value in sections.items():
        if "hook" in str(key).lower() and key != "contentOutline":
            hook_sources.extend(collect_hooks(value))
    primary_hook = " ".join(str(outline.get("title_hook", {}).get("data", "")).split())
    alternative_hooks = []
    seen_hooks: set[str] = set()
    for hook in hook_sources:
        normalized = hook.casefold()
        if hook and normalized != primary_hook.casefold() and normalized not in seen_hooks:
            seen_hooks.add(normalized)
            alternative_hooks.append(hook)
    thumbnails = []
    main_thumbnail = str(outline.get("sample_thumbnail_img", "")).strip()
    if main_thumbnail:
        thumbnails.append(
            {
                "url": main_thumbnail,
                "label": str(outline.get("thumbnail_disclaimer", "Main thumbnail")),
            }
        )
    for item in sections.get("alternativeThumbnails", {}).get("alternativeThumbnails", []):
        if isinstance(item, dict) and item.get("imageUrl"):
            thumbnails.append(
                {"url": str(item["imageUrl"]), "label": str(item.get("imageTitle", "Thumbnail"))}
            )
    unique_thumbnails = []
    seen_thumbnail_urls: set[str] = set()
    for item in thumbnails:
        if item["url"] not in seen_thumbnail_urls:
            seen_thumbnail_urls.add(item["url"])
            unique_thumbnails.append(item)
    thumbnails = unique_thumbnails

    def metric_number(value: str) -> float | None:
        match = re.search(r"([\d.]+)\s*([KMB]?)", value.upper())
        if not match:
            return None
        multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2)]
        return float(match.group(1)) * multiplier

    total_audience = metrics.get("Total Audience", "")
    remaining_reach = metrics.get("Est. Remaining Views", "")
    total_value = metric_number(total_audience)
    remaining_value = metric_number(remaining_reach)
    resonance = (
        round(min(100, remaining_value / total_value * 100))
        if total_value and remaining_value is not None
        else None
    )
    video_description = outline.get("video_description", {}).get("data", "")
    creator_angle = alternatives[0] if alternatives else video_description.split("\n", 1)[0]
    return {
        "topic": topic or requested_topic,
        "viral_rank": metrics.get("Viral Topic Rank", "").replace("#", "").strip(),
        "total_audience": total_audience,
        "remaining_reach": remaining_reach,
        "estimated_resonance": f"{resonance}%" if resonance is not None else "",
        "why_it_matters": " ".join(summary_parts),
        "creator_angle": creator_angle,
        "video_idea": video_description,
        "hook": primary_hook,
        "suggested_title": primary_hook,
        "alternative_hooks": alternative_hooks,
        "cta": outline.get("call_to_action", {}).get("data", ""),
        "hashtags": outline.get("hashtags", {}).get("data", []),
        "thumbnails": thumbnails[:6],
        "selected_thumbnail": main_thumbnail,
        "source": "Viralizer MCP",
    }


def _has_usable_viralizer_content(payload: dict[str, Any]) -> bool:
    analysis = payload.get("topicAnalysis")
    if not isinstance(analysis, list):
        return bool(payload.get("video_idea") or payload.get("hook"))
    for item in analysis:
        if not isinstance(item, dict) or item.get("key") != "contentOutline":
            continue
        outline = item.get("data", {}).get("contentOutline", {})
        return bool(
            str(outline.get("title_hook", {}).get("data", "")).strip()
            or str(outline.get("video_description", {}).get("data", "")).strip()
        )
    return False


async def get_full_report_from_mcp(topic: str) -> dict[str, Any]:
    url, headers = _mcp_config()
    tool_name = os.getenv("MCP_TOOL_NAME", "").strip()
    topic_argument = os.getenv("MCP_TOPIC_ARGUMENT", "topic").strip() or "topic"
    if not tool_name:
        raise MCPOutlineError("MCP_SERVER_URL and MCP_TOOL_NAME must be configured in .env.")
    try:
        async with httpx.AsyncClient(headers=headers, timeout=180.0) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    available = {tool.name for tool in tools.tools}
                    if tool_name not in available:
                        if "analyze_topic" in available:
                            tool_name = "analyze_topic"
                            topic_argument = "keyword"
                        else:
                            names = ", ".join(sorted(available)) or "none"
                            raise MCPOutlineError(
                                f"MCP tool '{tool_name}' was not found. Available tools: {names}."
                            )
                    result = await session.call_tool(tool_name, {topic_argument: topic})
                    payload = _extract_outline(result)
                    records = payload.get("records", {})
                    task_id = payload.get("task_id") or records.get("task_id")
                    task_name = str(records.get("task_placeholder", {}).get("name", ""))
                    needs_poll = (
                        payload.get("page_ready") is False
                        or "[PENDING]" in task_name
                        or not _has_usable_viralizer_content(payload)
                    )
                    if task_id and needs_poll:
                        if "poll_task_page" not in available:
                            raise MCPOutlineError(
                                "Viralizer started an analysis task but the MCP server has no polling tool."
                            )
                        result = await session.call_tool(
                            "poll_task_page", {"task_id": task_id, "timeout_seconds": 150}
                        )
    except MCPOutlineError:
        raise
    except Exception as exc:
        raise MCPOutlineError(_connection_error(exc, url)) from exc

    if getattr(result, "isError", False):
        message = " ".join(
            str(getattr(item, "text", "")) for item in getattr(result, "content", [])
        ).strip()
        raise MCPOutlineError(message or "The MCP tool reported an error.")
    final_payload = _extract_outline(result)
    return final_payload


async def get_outline_from_mcp(topic: str) -> dict[str, Any]:
    final_payload = await get_full_report_from_mcp(topic)
    outline = _viralizer_outline(final_payload, topic)
    if not str(outline.get("hook", "")).strip() and not str(
        outline.get("video_idea", "")
    ).strip():
        raise MCPOutlineError(
            "Viralizer completed the topic analysis but returned no video outline. "
            "Try the topic again or use a more specific phrase."
        )
    return outline


async def get_hot_topics_from_mcp(option_keys: str | None = None) -> list[dict[str, Any]]:
    url, headers = _mcp_config()
    keys = option_keys or os.getenv(
        "MCP_HOT_TOPIC_KEYS", "google,twitter,US,business,entertainment"
    )
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "hot_topics_for_keys", {"option_keys": keys}
                    )
    except Exception as exc:
        raise MCPOutlineError(_connection_error(exc, url)) from exc

    payload = _extract_outline(result)
    topics_by_id: dict[str, dict[str, Any]] = {}
    for group in payload.get("records", {}).get("items", []):
        if not isinstance(group, dict):
            continue
        group_key = str(group.get("key", ""))
        group_label = str(group.get("label", "Hot topic"))
        for item in group.get("topics", []):
            if isinstance(item, dict) and item.get("topic_id"):
                topic_id = str(item["topic_id"])
                topic = topics_by_id.setdefault(
                    topic_id,
                    {
                        "topic_id": topic_id,
                        "topic": str(item.get("topic", "Untitled topic")),
                        "image": str(item.get("img", "")),
                        "groups": [],
                        "group_keys": [],
                    },
                )
                if group_key not in topic["group_keys"]:
                    topic["group_keys"].append(group_key)
                    topic["groups"].append(group_label)
    return list(topics_by_id.values())


async def get_hot_topic_details_from_mcp(topic_id: str) -> dict[str, Any]:
    url, headers = _mcp_config()
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "hot_topics_details", {"topic_id": topic_id}
                    )
    except Exception as exc:
        raise MCPOutlineError(_connection_error(exc, url)) from exc

    outline = _viralizer_outline(_extract_outline(result), "Current hot topic")
    if not str(outline.get("video_idea", "")).strip():
        raise MCPOutlineError("Viralizer returned no video outline for this hot topic.")
    return outline


async def get_idea_smith_from_mcp(topic: str = "") -> dict[str, Any]:
    """Discover and call Viralizer's Idea Smith tool without hard-coding its schema."""
    url, headers = _mcp_config()
    try:
        async with httpx.AsyncClient(headers=headers, timeout=180.0) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    matching = [
                        tool
                        for tool in listed.tools
                        if "idea" in tool.name.lower() and "smith" in tool.name.lower()
                    ]
                    is_fallback = not matching
                    if is_fallback:
                        fallback = next(
                            (item for item in listed.tools if item.name == "analyze_topic"), None
                        )
                        if not fallback:
                            available = ", ".join(sorted(tool.name for tool in listed.tools)) or "none"
                            raise MCPOutlineError(
                                "Viralizer's Idea Smith MCP tool is not currently available and "
                                f"no topic-analysis fallback was found. Available tools: {available}."
                            )
                        matching = [fallback]

                    if not matching:
                        raise MCPOutlineError(
                            "Viralizer's Idea Smith MCP tool is not currently available."
                        )

                    tool = matching[0]
                    schema = tool.inputSchema or {}
                    properties = schema.get("properties") or {}
                    required = schema.get("required") or []
                    subject = topic.strip() or "current trending content opportunities"
                    arguments: dict[str, Any] = {}
                    preferred = ("topic", "keyword", "query", "q", "prompt", "subject", "niche")
                    selected = next((name for name in preferred if name in properties), None)
                    if selected:
                        arguments[selected] = subject
                    for name in required:
                        if name in arguments:
                            continue
                        definition = properties.get(name) or {}
                        if "default" in definition:
                            arguments[name] = definition["default"]
                        elif definition.get("enum"):
                            arguments[name] = definition["enum"][0]
                        elif definition.get("type") == "string":
                            arguments[name] = subject
                        else:
                            raise MCPOutlineError(
                                f"Idea Smith requires '{name}'. Its current MCP schema needs a UI update."
                            )

                    result = await session.call_tool(tool.name, arguments)
                    payload = _extract_outline(result)
                    records = payload.get("records", {}) if isinstance(payload, dict) else {}
                    task_id = payload.get("task_id") or records.get("task_id")
                    if task_id:
                        poll_tool = next((item for item in listed.tools if item.name == "poll_task_page"), None)
                        if poll_tool:
                            result = await session.call_tool(
                                "poll_task_page", {"task_id": task_id, "timeout_seconds": 150}
                            )
                            payload = _extract_outline(result)
    except MCPOutlineError:
        raise
    except Exception as exc:
        raise MCPOutlineError(_connection_error(exc, url)) from exc

    if getattr(result, "isError", False):
        message = " ".join(
            str(getattr(item, "text", "")) for item in getattr(result, "content", [])
        ).strip()
        raise MCPOutlineError(message or "Idea Smith reported an error.")
    if is_fallback:
        payload = _viralizer_outline(payload, subject)
    return {
        "tool": tool.name,
        "mode": "viralizer_topic_ideas" if is_fallback else "idea_smith",
        "notice": (
            "Viralizer has not exposed Idea Smith as an MCP tool yet; these ideas use "
            "Viralizer topic analysis as the temporary fallback."
            if is_fallback
            else ""
        ),
        "query": topic.strip(),
        "result": payload,
    }
