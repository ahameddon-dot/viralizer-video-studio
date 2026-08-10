import asyncio
import json
import re
import httpx
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from pixverse_client import build_video_prompt
from video_providers import (
    VideoProviderError,
    generate_video as generate_with_provider,
    provider_catalog,
    video_status as provider_video_status,
)
from daily_trends import daily_trends
from mcp_outline_client import (
    MCPOutlineError,
    get_full_report_from_mcp,
    get_hot_topic_details_from_mcp,
    get_hot_topics_from_mcp,
    get_outline_from_mcp,
)
from viralizer_pdf import build_viralizer_pdf
from betting_topics import betting_report
from regional_trends import regional_report


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="Viralizer + PixVerse")


@app.on_event("startup")
async def start_daily_scheduler():
    asyncio.create_task(daily_trends.scheduler())


@app.get("/health")
async def health():
    return {"status": "ok", "service": "viralizer-video-studio"}


class GenerateRequest(BaseModel):
    content: dict[str, Any]
    provider: str = "pixverse"
    prompt: str | None = None
    duration: int = Field(default=5, ge=5, le=15)
    quality: str = "720p"


class TopicRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)


@app.get("/api/betting/topics")
async def betting_topics(query: str = ""):
    try:
        return await betting_report(query.strip())
    except (httpx.HTTPError, MCPOutlineError) as exc:
        raise HTTPException(502, f"Could not load betting topics: {exc}") from exc


@app.get("/api/regional/topics")
async def regional_topics(query: str = ""):
    return await regional_report(query.strip())


def topic_variants(topic: str) -> list[str]:
    concise = " ".join(topic.split()[:10]).rstrip("?!,.;:-")
    candidates = [
        concise,
        re.split(r"\s*[:|;]\s*", topic, maxsplit=1)[0],
        re.split(r"\s+[–—-]\s+", topic, maxsplit=1)[0],
        topic,
    ]
    return list(dict.fromkeys(value.strip() for value in candidates if len(value.strip()) >= 4))[:3]


async def outline_with_fallback(topic: str):
    last_error = None
    for variant in topic_variants(topic):
        try:
            return await get_outline_from_mcp(variant)
        except MCPOutlineError as exc:
            last_error = exc
    raise last_error or MCPOutlineError("Viralizer returned no report for this topic.")


async def full_report_with_fallback(topic: str):
    last_error = None
    for variant in topic_variants(topic):
        try:
            return await get_full_report_from_mcp(variant)
        except MCPOutlineError as exc:
            last_error = exc
    raise last_error or MCPOutlineError("Viralizer returned no full report for this topic.")


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/topic/sample")
async def sample_topic():
    return json.loads((ROOT / "sample_hot_topic.json").read_text(encoding="utf-8"))


@app.get("/api/daily/status")
async def daily_status():
    return daily_trends.status()


@app.get("/api/daily/latest")
async def daily_latest():
    report = daily_trends.latest_report()
    if not report:
        raise HTTPException(404, "No daily opportunity report has been generated yet.")
    return report


@app.post("/api/daily/run")
async def daily_run():
    started = daily_trends.start()
    return {"started": started, **daily_trends.status()}


@app.post("/api/daily/report")
async def daily_topic_report(request: TopicRequest):
    try:
        return await outline_with_fallback(request.topic.strip())
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/daily/pdf")
async def daily_topic_pdf(request: TopicRequest):
    try:
        payload = await full_report_with_fallback(request.topic.strip())
        path = build_viralizer_pdf(request.topic.strip(), payload)
        return FileResponse(path, media_type="application/pdf", filename=path.name)
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/topic/from-mcp")
async def topic_from_mcp(request: TopicRequest):
    try:
        return await get_outline_from_mcp(request.topic.strip())
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/topics/hot")
async def hot_topics():
    try:
        return {"topics": await get_hot_topics_from_mcp()}
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/topics/hot/{topic_id}")
async def hot_topic_details(topic_id: str):
    try:
        return await get_hot_topic_details_from_mcp(topic_id)
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/video/generate")
async def generate_video(request: GenerateRequest):
    prompt = (request.prompt or build_video_prompt(request.content, request.duration)).strip()
    if not prompt:
        raise HTTPException(422, "The MCP content did not contain a usable video prompt.")
    try:
        job_id = await generate_with_provider(
            request.provider,
            prompt,
            content=request.content,
            duration=request.duration,
            quality=request.quality,
        )
        return {"job_id": job_id, "provider": request.provider, "status": "processing", "prompt": prompt}
    except VideoProviderError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/video/providers")
async def video_providers():
    return {"providers": provider_catalog()}


@app.get("/api/video/{provider}/{job_id}")
async def video_status(provider: str, job_id: str):
    try:
        result = await provider_video_status(provider, job_id)
    except VideoProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"job_id": job_id, "provider": provider, **result}
