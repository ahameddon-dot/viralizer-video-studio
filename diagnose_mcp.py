import asyncio
import json
import os
import sys
import traceback

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    try:
        url = os.environ["MCP_SERVER_URL"]
        headers = {}
        if os.getenv("MCP_API_KEY"):
            headers["X-API-Key"] = os.environ["MCP_API_KEY"]
        if os.getenv("MCP_AUTH_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['MCP_AUTH_TOKEN']}"
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            async with streamable_http_client(url, http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    for tool in tools.tools:
                        print(f"\n{tool.name}\n{json.dumps(tool.inputSchema, indent=2)}")
                    if len(sys.argv) > 2 and sys.argv[1] == "--options":
                        result = await session.call_tool(
                            "hot_topics_options", {"q": sys.argv[2]}
                        )
                        print("\nhot_topics_options response")
                        print(result.model_dump_json(indent=2, by_alias=True))
                    elif len(sys.argv) > 2 and sys.argv[1] == "--detail":
                        result = await session.call_tool(
                            "hot_topics_details", {"topic_id": sys.argv[2]}
                        )
                        print("\nhot_topics_details response")
                        print(result.model_dump_json(indent=2, by_alias=True))
                    elif len(sys.argv) > 1 and sys.argv[1] == "--hotkeys":
                        result = await session.call_tool(
                            "hot_topics_for_keys",
                            {"option_keys": sys.argv[2] if len(sys.argv) > 2 else "deep_dive"},
                        )
                        print("\nhot_topics_for_keys response")
                        print(result.model_dump_json(indent=2, by_alias=True))
                    elif len(sys.argv) > 1 and sys.argv[1] == "--hot":
                        result = await session.call_tool("hot_topics_options", {"q": ""})
                        print("\nhot_topics_options response")
                        print(result.model_dump_json(indent=2, by_alias=True))
                    elif len(sys.argv) > 1:
                        result = await session.call_tool("analyze_topic", {"keyword": sys.argv[1]})
                        payload = json.loads(result.content[0].text)
                        print("\nanalyze_topic summary")
                        print(json.dumps({k: payload.get(k) for k in ("page_ready", "task_id")}, indent=2))
                        if payload.get("task_id") and payload.get("page_ready") is False:
                            result = await session.call_tool(
                                "poll_task_page",
                                {"task_id": payload["task_id"], "timeout_seconds": 150},
                            )
                            payload = json.loads(result.content[0].text)
                        print("\nfinal task response")
                        print(json.dumps(payload, indent=2))
    except BaseException as exc:
        traceback.print_exception(exc)


if __name__ == "__main__":
    asyncio.run(main())
