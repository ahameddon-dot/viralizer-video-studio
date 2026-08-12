import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import httpx
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from pixverse_client import build_video_prompt
from openai_image_client import OpenAIImageError, generate_instagram_album, generate_instagram_image, prepare_image_prompt
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
    get_idea_smith_from_mcp,
    get_outline_from_mcp,
)
from viralizer_pdf import build_viralizer_pdf
from betting_topics import betting_report
from regional_trends import regional_report


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="Viralizer + PixVerse")

AUTH_COOKIE = "viralizer_access"


def configured_password() -> str:
    return os.getenv("APP_PASSWORD", "").strip()


def access_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"viralizer-video-studio", hashlib.sha256).hexdigest()


def is_authenticated(request: Request) -> bool:
    password = configured_password()
    if not password:
        return True
    supplied = request.cookies.get(AUTH_COOKIE, "")
    return hmac.compare_digest(supplied, access_token(password))


@app.middleware("http")
async def require_password(request: Request, call_next):
    public_paths = {"/login", "/health"}
    if request.url.path not in public_paths and not is_authenticated(request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Password required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    message = '<p class="error">Incorrect password. Please try again.</p>' if error else ""
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Viralizer Studio · Sign in</title><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at top,#29154b,#090611 65%);color:#fff;font-family:Inter,Arial,sans-serif}}
.card{{width:min(420px,calc(100% - 32px));padding:36px;border:1px solid #563483;border-radius:20px;background:rgba(19,13,30,.94);box-shadow:0 24px 80px #0008}}
.mark{{display:inline-grid;place-items:center;width:46px;height:46px;border-radius:13px;background:#8b3dff;font-size:24px;font-weight:800}}h1{{margin:20px 0 8px;font-size:30px}}p{{color:#bdb2d2;line-height:1.5}}
label{{display:block;margin:24px 0 8px;font-weight:700}}input{{width:100%;padding:14px 16px;border:1px solid #56496a;border-radius:11px;background:#0d0915;color:#fff;font-size:17px;outline:none}}input:focus{{border-color:#a66cff;box-shadow:0 0 0 3px #8b3dff33}}
button{{width:100%;margin-top:16px;padding:14px;border:0;border-radius:11px;background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;font-size:16px;font-weight:800;cursor:pointer}}.error{{color:#ff9aaf;margin:14px 0 0}}
</style></head><body><main class="card"><div class="mark">V</div><h1>Viralizer Video Studio</h1><p>Enter the access password to continue.</p>{message}
<form method="post" action="/login"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" autofocus required><button type="submit">Open studio</button></form></main></body></html>""")


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    expected = configured_password()
    if not expected or not hmac.compare_digest(password, expected):
        return RedirectResponse("/login?error=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    response.set_cookie(
        AUTH_COOKIE,
        access_token(expected),
        max_age=86400,
        httponly=True,
        secure=forwarded_proto == "https",
        samesite="lax",
    )
    return response


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE)
    return response


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


class ImageGenerateRequest(BaseModel):
    content: dict[str, Any]
    prompt: str | None = None
    purpose: str = "instagram"


class TopicRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)


class IdeaSmithRequest(BaseModel):
    topic: str = Field(default="", max_length=500)


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


@app.post("/api/ideas/smith")
async def idea_smith(request: IdeaSmithRequest):
    try:
        return await get_idea_smith_from_mcp(request.topic)
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


@app.post("/api/image/openai")
async def generate_openai_image(request: ImageGenerateRequest):
    try:
        image = await generate_instagram_image(request.content, request.prompt, request.purpose)
    except OpenAIImageError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(
        content=image,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="instagram-post.png"'},
    )


@app.post("/api/image/prompt")
async def image_prompt(request: ImageGenerateRequest):
    return {"prompt": await prepare_image_prompt(request.content, request.purpose)}


@app.post("/api/image/openai/album")
async def generate_openai_album(request: ImageGenerateRequest):
    try:
        images = await generate_instagram_album(request.content, 5, request.prompt)
    except OpenAIImageError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "images": [f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}" for image in images]
    }
