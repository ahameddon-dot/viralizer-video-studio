import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
import httpx
import io
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from PIL import Image, ImageOps

from pixverse_client import PixVerseClient, PixVerseError, build_narration_script, build_video_prompt
from pixverse_growth_client import PixVerseGrowthClient, PixVerseGrowthError
from openai_image_client import OpenAIImageError, analyze_reference_image, generate_instagram_album, generate_instagram_image, generate_reference_image, prepare_image_prompt
from cloudflare_image_client import CloudflareImageError, generate_cloudflare_album, generate_cloudflare_image
from video_providers import (
    VideoProviderError,
    generate_video as generate_with_provider,
    provider_catalog,
    video_status as provider_video_status,
)
from media_finisher import MediaFinisherError, finish_video
from saved_videos import SavedVideoError, list_saved_videos, save_video
from long_video import start as start_long_video, status as long_video_status
from production_controller import prepare_production, record_production
from heygen_client import HeyGenClient, HeyGenError
from heygen_director import build_heygen_script, build_presenter_direction
from heygen_video_director import build_heygen_plan, compile_heygen_request
from hybrid_video import start as start_hybrid_video, status as hybrid_video_status
from google_auth import GoogleAuthError, authorization_url as google_authorization_url, configured as google_configured, exchange_code as google_exchange_code, new_state as google_new_state, read_session as read_google_session, read_signed_payload as read_google_state, redirect_uri as google_redirect_uri, session_token as google_session_token, user_allowed as google_user_allowed
from daily_trends import daily_trends
from global_sources import annotate_topic_taxonomy, build_category_discovery_queries, discover_category_topics, discover_global_sources, suggest_logos_for_content
from mcp_outline_client import (
    MCPOutlineError,
    get_full_report_from_mcp,
    get_hot_topic_details_from_mcp,
    get_hot_topics_from_mcp,
    get_idea_smith_from_mcp,
    get_category_intelligence_from_mcp,
    get_outline_from_mcp,
    outline_from_full_report,
)
from viralizer_pdf import build_viralizer_pdf
from betting_topics import betting_report
from regional_trends import regional_report
from taxonomy import TaxonomyError, load_taxonomy, save_uploaded_taxonomy
from release_dashboard import (
    ReleaseDashboardError,
    compare_versions,
    environment_snapshot,
    load_catalog,
    rollback_preview,
)
from release_actions import ReleaseActionError, publish_beta, rollback_production
from creatorthon_store import create_project, get_profile, list_projects, save_profile, update_project
from social_publisher import MANDATORY_HASHTAG, SocialPublishError, build_hashtags, publish_all, publishing_status
from website_to_video import WebsiteAnalysisError, analyze_website, fetch_public_image
from article_intelligence import prepare_article_intelligence


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="Viralizer + PixVerse")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

REPORT_CACHE_TTL_SECONDS = int(os.getenv("VIRALIZER_REPORT_CACHE_TTL", "1800"))
_viralizer_report_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_viralizer_report_locks: dict[str, asyncio.Lock] = {}

AUTH_COOKIE = "viralizer_access"
ADMIN_COOKIE = "viralizer_admin_access"
GOOGLE_STATE_COOKIE = "viralizer_google_state"


def configured_password() -> str:
    return os.getenv("APP_PASSWORD", "").strip()


def access_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"viralizer-video-studio", hashlib.sha256).hexdigest()


def is_authenticated(request: Request) -> bool:
    supplied = request.cookies.get(AUTH_COOKIE, "")
    if read_google_session(supplied):
        return True
    password = configured_password()
    if password and hmac.compare_digest(supplied, access_token(password)):
        return True
    return not password and not google_configured()


def configured_admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD", "").strip()


def admin_access_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"viralizer-release-dashboard", hashlib.sha256).hexdigest()


def is_admin_authenticated(request: Request) -> bool:
    password = configured_admin_password()
    if not password:
        return False
    return hmac.compare_digest(request.cookies.get(ADMIN_COOKIE, ""), admin_access_token(password))


def require_admin(request: Request) -> None:
    if not is_admin_authenticated(request):
        raise HTTPException(401, "Administrator authentication required.")


@app.middleware("http")
async def require_password(request: Request, call_next):
    public_paths = {"/login", "/creatorthon/login", "/creatorthon-v2/login", "/auth/google", "/auth/google/callback", "/health", "/health/pixverse", "/health/pixverse-growth"}
    public_login_assets = {
        "/static/viralizer-intro.css",
        "/static/viralizer-intro.js",
        "/static/viralizer-login-intro.mp4",
        "/static/viralizer-original-logo.png",
        "/static/final/viralizer-logo-mark.svg",
    }
    if request.url.path.startswith("/creatorthon") or request.url.path.startswith("/api/creatorthon"):
        google_user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
        if request.url.path not in public_paths and not google_user:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Google sign-in required"}, status_code=401)
            login_path = "/creatorthon-v2/login" if request.url.path.startswith("/creatorthon-v2") else "/creatorthon/login"
            return RedirectResponse(login_path, status_code=303)
    if request.url.path not in public_paths and request.url.path not in public_login_assets and not is_authenticated(request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Password required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    errors = {
        "password": "Incorrect password. Please try again.",
        "google_state": "Google sign-in expired or could not be verified. Please try again.",
        "google_denied": "Google sign-in was cancelled.",
        "google_failed": "Google sign-in could not be completed. Please try again.",
        "google_not_allowed": "This Google account is not approved for this workspace.",
    }
    message = f'<p class="error">{errors.get(error, "")}</p>' if error else ""
    google_button = '<a class="google" href="/auth/google"><span>G</span> Continue with Google</a>' if google_configured() else '<p class="google-note">Google sign-in will appear after GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are added.</p>'
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Viralizer Studio · Sign in</title><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at top,#29154b,#090611 65%);color:#fff;font-family:Inter,Arial,sans-serif}}
.card{{width:min(420px,calc(100% - 32px));padding:36px;border:1px solid #563483;border-radius:20px;background:rgba(19,13,30,.94);box-shadow:0 24px 80px #0008}}
.mark{{display:block;width:210px;max-width:72%;height:auto;object-fit:contain}}h1{{margin:20px 0 8px;font-size:30px}}p{{color:#bdb2d2;line-height:1.5}}
label{{display:block;margin:24px 0 8px;font-weight:700}}input{{width:100%;padding:14px 16px;border:1px solid #56496a;border-radius:11px;background:#0d0915;color:#fff;font-size:17px;outline:none}}input:focus{{border-color:#a66cff;box-shadow:0 0 0 3px #8b3dff33}}
button{{width:100%;margin-top:16px;padding:14px;border:0;border-radius:11px;background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;font-size:16px;font-weight:800;cursor:pointer}}.google{{display:flex;align-items:center;justify-content:center;gap:11px;width:100%;margin-top:18px;padding:13px;border:1px solid #625873;border-radius:11px;background:#fff;color:#17131d;font-size:16px;font-weight:800;text-decoration:none}}.google span{{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;color:#4285f4;font-size:20px}}.divider{{display:flex;align-items:center;gap:12px;margin:20px 0 0;color:#877d94;font-size:12px}}.divider:before,.divider:after{{content:"";height:1px;flex:1;background:#3d3449}}.google-note{{font-size:12px;color:#8f849d}}.error{{color:#ff9aaf;margin:14px 0 0}}
</style></head><body><main class="card"><img class="mark" src="/static/viralizer-original-logo.png" alt="Viralizer"><h1>Viralizer Video Studio</h1><p>Sign in with Google or use the workspace password.</p>{message}
{google_button}<div class="divider">or use workspace password</div><form method="post" action="/login"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required><button type="submit">Open studio</button></form></main></body></html>""")


@app.get("/auth/google")
async def google_login(request: Request, next: str = "/"):
    if not google_configured():
        return RedirectResponse("/login?error=google_failed", status_code=303)
    state = google_new_state(next)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    callback = google_redirect_uri(scheme, host)
    response = RedirectResponse(google_authorization_url(callback, state), status_code=302)
    response.set_cookie(GOOGLE_STATE_COOKIE, state, max_age=600, httponly=True, secure=scheme == "https", samesite="lax")
    return response


@app.get("/auth/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    expected_state = request.cookies.get(GOOGLE_STATE_COOKIE, "")
    state_payload = read_google_state(state, max_age=600) if state and hmac.compare_digest(state, expected_state) else None
    if error or not code:
        return RedirectResponse("/login?error=google_denied", status_code=303)
    if not state_payload:
        return RedirectResponse("/login?error=google_state", status_code=303)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    try:
        user = await google_exchange_code(code, google_redirect_uri(scheme, host))
    except GoogleAuthError:
        return RedirectResponse("/login?error=google_failed", status_code=303)
    if not google_user_allowed(user):
        return RedirectResponse("/login?error=google_not_allowed", status_code=303)
    response = RedirectResponse(str(state_payload.get("next") or "/"), status_code=303)
    response.set_cookie(AUTH_COOKIE, google_session_token(user), max_age=7 * 86400, httponly=True, secure=scheme == "https", samesite="lax")
    response.delete_cookie(GOOGLE_STATE_COOKIE)
    return response

@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    expected = configured_password()
    if not expected or not hmac.compare_digest(password, expected):
        return RedirectResponse("/login?error=password", status_code=303)
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


@app.api_route("/logout", methods=["GET", "POST"])
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE)
    response.delete_cookie(GOOGLE_STATE_COOKIE)
    return response


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, error: str = ""):
    if is_admin_authenticated(request):
        return RedirectResponse("/admin", status_code=303)
    if not configured_admin_password():
        return HTMLResponse(
            "<h1>Release dashboard is not configured</h1><p>Add ADMIN_PASSWORD to this Render service, then redeploy.</p>",
            status_code=503,
        )
    message = '<p class="error">Incorrect administrator password.</p>' if error else ""
    return HTMLResponse(f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Release Dashboard · Sign in</title><style>
body{{min-height:100vh;margin:0;display:grid;place-items:center;background:#090611;color:#fff;font-family:Inter,Arial,sans-serif}}main{{width:min(430px,calc(100% - 36px));padding:34px;border:1px solid #644490;border-radius:20px;background:#151022}}h1{{margin-top:0}}p{{color:#bdb2d2}}label{{display:block;font-weight:800;margin:22px 0 8px}}input,button{{width:100%;padding:14px;border-radius:11px;font:inherit}}input{{border:1px solid #56496a;background:#0d0915;color:#fff}}button{{margin-top:14px;border:0;background:#8b5cf6;color:#fff;font-weight:800}}.error{{color:#ff9aaf}}
</style></head><body><main><h1>Private release dashboard</h1><p>This area controls release records and rollback previews. Use the separate administrator password.</p>{message}<form method="post" action="/admin/login"><label for="password">Administrator password</label><input id="password" name="password" type="password" required autofocus><button>Open dashboard</button></form></main></body></html>""")


@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    expected = configured_admin_password()
    if not expected or not hmac.compare_digest(password, expected):
        return RedirectResponse("/admin/login?error=1", status_code=303)
    response = RedirectResponse("/admin", status_code=303)
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    response.set_cookie(
        ADMIN_COOKIE, admin_access_token(expected), max_age=3600, httponly=True,
        secure=forwarded_proto == "https", samesite="strict",
    )
    return response


@app.post("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE)
    return response


@app.get("/admin")
async def admin_dashboard(request: Request):
    if not is_admin_authenticated(request):
        return RedirectResponse("/admin/login", status_code=303)
    return FileResponse(ROOT / "static" / "admin.html")


@app.get("/api/admin/releases")
async def admin_releases(request: Request):
    require_admin(request)
    try:
        return {"environment": environment_snapshot(), **load_catalog()}
    except ReleaseDashboardError as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/admin/compare")
async def admin_compare(request: Request, from_version: str, to_version: str):
    require_admin(request)
    try:
        return compare_versions(from_version, to_version)
    except ReleaseDashboardError as exc:
        raise HTTPException(404, str(exc)) from exc


class RollbackPreviewRequest(BaseModel):
    target_version: str = Field(min_length=2, max_length=40)


class ReleaseActionRequest(BaseModel):
    version: str = Field(min_length=2, max_length=40)
    confirmation: str = Field(min_length=2, max_length=80)


@app.post("/api/admin/rollback-preview")
async def admin_rollback_preview(request: Request, payload: RollbackPreviewRequest):
    require_admin(request)
    try:
        return rollback_preview(payload.target_version)
    except ReleaseDashboardError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/admin/publish")
async def admin_publish(request: Request, payload: ReleaseActionRequest):
    require_admin(request)
    catalog = load_catalog()
    if payload.version != catalog.get("beta_version"):
        raise HTTPException(409, "The selected version is not the current approved beta.")
    if payload.confirmation != f"PUBLISH {payload.version}":
        raise HTTPException(422, "Publish confirmation did not match.")
    try:
        return await publish_beta(payload.version)
    except ReleaseActionError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/admin/rollback")
async def admin_rollback(request: Request, payload: ReleaseActionRequest):
    require_admin(request)
    load_catalog()  # Fail closed if the release evidence is unavailable.
    rollback_preview(payload.version)  # Validate that this is a known catalog version.
    if payload.confirmation != f"ROLLBACK {payload.version}":
        raise HTTPException(422, "Rollback confirmation did not match.")
    try:
        return await rollback_production(payload.version)
    except ReleaseActionError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.on_event("startup")
async def start_daily_scheduler():
    asyncio.create_task(daily_trends.scheduler())


@app.get("/health")
async def health():
    return {"status": "ok", "service": "viralizer-video-studio"}


@app.get("/health/pixverse")
async def pixverse_health():
    """Check PixVerse authentication without exposing secrets or spending credits."""
    try:
        await PixVerseClient().balance()
        return {"status": "ok", "authenticated": True}
    except PixVerseError as exc:
        return {"status": "error", "authenticated": False, "detail": str(exc)}


@app.get("/health/pixverse-growth")
async def pixverse_growth_health():
    """Validate the separate Growth Studio bearer credential without generating a billable video."""
    try:
        result = await PixVerseGrowthClient().avatars()
        data = result.get("data") or result
        avatars = data if isinstance(data, list) else data.get("avatars") or data.get("items") or []
        return {"status": "ok", "authenticated": True, "avatars": len(avatars)}
    except PixVerseGrowthError as exc:
        return {"status": "error", "authenticated": False, "detail": str(exc), "code": exc.code}


class GenerateRequest(BaseModel):
    content: dict[str, Any]
    provider: str = "pixverse"
    prompt: str | None = None
    duration: int = Field(default=5, ge=5, le=60)
    quality: str = "720p"
    quality_mode: bool = True
    aspect_ratio: str = "9:16"
    target_platform: str = ""
    narration: str = ""
    avatar_id: str = ""
    voice_id: str = ""
    background: str = "#0B1020"
    generation_type: str = "text_to_video"
    debug_prompt: bool = False
    visual_mode: str = "AUTO"
    captions: bool = False
    heygen_style_id: str = ""
    brand_kit_id: str = ""


class SaveVideoRequest(BaseModel):
    video_url: str
    title: str = "Generated video"
    provider: str = "video"


class LogoSuggestionRequest(BaseModel):
    content: dict[str, Any]

class ImageGenerateRequest(BaseModel):
    content: dict[str, Any]
    prompt: str | None = None
    purpose: str = "instagram"
    provider: str = "openai"


class TopicRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)


class IdeaSmithRequest(BaseModel):
    topic: str = Field(default="", max_length=500)


class SiteUrlVideoRequest(BaseModel):
    url: str = Field(min_length=4, max_length=2000)
    duration: int = Field(default=10, ge=5, le=60)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|3:4|1:1)$")


class CategoryIntelligenceRequest(BaseModel):
    category: str = Field(min_length=2, max_length=120)
    super_category: str = Field(default="", max_length=120)
    categories: list[str] = Field(default_factory=list, max_length=50)
    keyword: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    lens: str = Field(default="", max_length=80)
    reputation: str = Field(default="", max_length=80)


class CreatorthonProfileRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    company: str = Field(default="", max_length=160)
    role: str = Field(default="", max_length=120)
    socials: dict[str, str] = Field(default_factory=dict)
    interests: list[str] = Field(default_factory=list, max_length=4)
    onboarding_complete: bool = False


class CreatorthonTopicsRequest(BaseModel):
    interests: list[str] = Field(min_length=1, max_length=4)


class CreatorthonProjectRequest(BaseModel):
    topic: dict[str, Any]


class CreatorthonProjectUpdateRequest(BaseModel):
    provider: str = Field(default="", max_length=40)
    job_id: str = Field(default="", max_length=160)
    video_url: str = Field(default="", max_length=1000)
    status: str = Field(default="", max_length=40)


class CreatorthonFinishRequest(BaseModel):
    video_url: str = Field(min_length=4, max_length=2000)
    narration: str = Field(default="", max_length=4096)
    voice: str = Field(default="coral", max_length=40)
    official_logo_data: str = Field(default="", max_length=14_000_000)


class CreatorthonHashtagRequest(BaseModel):
    topic: dict[str, Any]


class CreatorthonPublishRequest(BaseModel):
    project_id: str = Field(min_length=8, max_length=64)
    video_url: str = Field(min_length=4, max_length=2000)
    caption: str = Field(default="", max_length=3000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    platforms: list[str] = Field(default_factory=list, max_length=3)


class DailyDiscoveryRequest(BaseModel):
    category: str = Field(default="ALL", max_length=80)
    keyword: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)


class GrowthEditRequest(BaseModel):
    clip_index: int = Field(ge=1, le=40)
    instruction: str = Field(min_length=1, max_length=500)


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
    payload = await full_report_with_fallback(topic)
    return outline_from_full_report(payload, topic)


async def full_report_with_fallback(topic: str):
    cache_key = " ".join(topic.lower().split())
    cached = _viralizer_report_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < REPORT_CACHE_TTL_SECONDS:
        return cached[1]

    lock = _viralizer_report_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _viralizer_report_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < REPORT_CACHE_TTL_SECONDS:
            return cached[1]

        last_error = None
        # One MCP call already polls Viralizer for up to 150 seconds. Use only a
        # concise alternate after failure instead of repeating up to nine tasks.
        for variant in topic_variants(topic)[:2]:
            try:
                payload = await get_full_report_from_mcp(variant)
                _viralizer_report_cache[cache_key] = (time.monotonic(), payload)
                return payload
            except MCPOutlineError as exc:
                last_error = exc
        raise last_error or MCPOutlineError("Viralizer returned no full report for this topic.")


async def category_intelligence_with_retry(request: CategoryIntelligenceRequest):
    category = " ".join(request.category.split()[:8])
    keyword = " ".join(request.keyword.split()[:8])
    description = " ".join(request.description.split()[:10])
    lens = " ".join(request.lens.split()[:4])
    reputation = " ".join(request.reputation.split()[:3])
    base = keyword or category
    primary_parts = [base]
    if keyword and category.lower() not in keyword.lower():
        primary_parts.append(category)
    if description:
        primary_parts.append(description)
    elif lens and lens.lower() != "everything":
        primary_parts.append(lens)
    if reputation and reputation.lower() != "all reputation":
        primary_parts.append(f"{reputation} reputation")
    primary = " ".join(" ".join(primary_parts).split()[:14])
    candidates = list(dict.fromkeys(filter(None, [
        primary,
        " ".join((f"{base} {category} latest trends" if base.lower() != category.lower() else f"{category} latest trends").split()[:12]),
        " ".join((f"{base} {category} news" if base.lower() != category.lower() else f"{category} industry news").split()[:12]),
    ])))[:3]
    last_error = None
    for index, candidate in enumerate(candidates):
        try:
            outline = await get_category_intelligence_from_mcp(candidate)
            returned_topic = re.sub(r"^deep\s+dive\s*:\s*", "", str(outline.get("topic") or candidate), flags=re.I).strip()
            outline["youtube_search_topic"] = returned_topic or candidate
            outline["alternate_topics"] = [item for item in candidates if item != candidate][:2]
            return outline
        except MCPOutlineError as exc:
            last_error = exc
        if index < len(candidates) - 1:
            await asyncio.sleep(2)
    raise last_error or MCPOutlineError("Viralizer returned no category intelligence.")


async def hot_topic_details_with_retry(topic_id: str):
    last_error = None
    for attempt in range(3):
        try:
            return await get_hot_topic_details_from_mcp(topic_id)
        except MCPOutlineError as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
    raise last_error or MCPOutlineError("Viralizer returned no report for this hot topic.")


@app.get("/")
async def index():
    return FileResponse(
        ROOT / "static" / "pixel_ui.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/creatorthon/login", response_class=HTMLResponse)
async def creatorthon_login(request: Request):
    if read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon", status_code=303)
    google_ready = google_configured()
    action = '<a class="google" href="/auth/google?next=/creatorthon"><b>G</b> Continue with Google</a>' if google_ready else '<p class="warning">Google sign-in is not configured yet. Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_SESSION_SECRET to this service.</p>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Viralizer Creatorthon</title><link rel="preload" href="/static/viralizer-login-intro.mp4?v=1" as="video" type="video/mp4"><link rel="preload" href="/static/viralizer-original-logo.png" as="image"><link rel="stylesheet" href="/static/viralizer-intro.css?v=7"><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 18% 12%,#32135f,#080914 46%);color:#fff;font-family:Inter,system-ui,sans-serif}}main.card{{width:min(460px,calc(100% - 32px));padding:38px;border:1px solid #4b326e;border-radius:22px;background:#111324ee;box-shadow:0 30px 90px #0009}}.mark{{display:block;width:230px;max-width:78%;height:auto;object-fit:contain}}h1{{font-size:32px;letter-spacing:-.04em;margin:22px 0 10px}}p{{color:#adb4cf;line-height:1.6}}.google{{margin-top:25px;min-height:52px;border-radius:12px;background:#fff;color:#171824;text-decoration:none;font-weight:850;display:flex;align-items:center;justify-content:center;gap:11px}}.google b{{color:#4285f4;font-size:20px}}.warning{{padding:13px;border:1px solid #774755;border-radius:11px;background:#321722;color:#ffbeca;font-size:13px}}</style></head><body class="intro-active"><main class="card"><img class="mark" src="/static/viralizer-original-logo.png" alt="Viralizer"><h1>Viralizer Creatorthon</h1><p>Choose your interests, discover relevant worldwide topics, and turn one into a finished video through a simple guided journey.</p>{action}</main><script src="/static/viralizer-intro.js?v=7" defer></script></body></html>""")


@app.get("/creatorthon")
async def creatorthon(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon/login", status_code=303)
    return FileResponse(ROOT / "static" / "creatorthon.html", headers={"Cache-Control": "no-store"})


@app.get("/creatorthon-v2/login", response_class=HTMLResponse)
async def creatorthon_v2_login(request: Request):
    if read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon-v2", status_code=303)
    google_ready = google_configured()
    action = '<a class="google" href="/auth/google?next=/creatorthon-v2"><b>G</b><span>Continue with Google</span></a>' if google_ready else '<p class="warning">Google sign-in is not configured yet. Add the Google credentials to this service.</p>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Viralizer Creatorthon</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;min-height:100%;background:#fff;color:#0b0b0d;font-family:Inter,Arial,sans-serif}}body{{display:grid;place-items:center;padding:28px}}main{{width:min(520px,100%)}}.brand{{display:flex;justify-content:center;margin-bottom:64px}}.brand img{{width:210px;height:auto}}.progress{{height:5px;border-radius:99px;background:#ececf0;overflow:hidden;margin-bottom:76px}}.progress:before{{content:"";display:block;width:24%;height:100%;border-radius:inherit;background:#8b2cff}}h1{{font-size:clamp(38px,8vw,58px);line-height:1.02;letter-spacing:-.055em;margin:0 0 18px}}p{{font-size:17px;line-height:1.55;color:#67666d;margin:0}}.google{{display:flex;align-items:center;justify-content:center;gap:12px;min-height:64px;margin-top:38px;border-radius:999px;background:#0b0b0d;color:#fff;text-decoration:none;font-size:17px;font-weight:800}}.google b{{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#fff;color:#4285f4;font-size:19px}}.note{{font-size:12px;color:#9b9aa1;text-align:center;margin-top:18px}}.warning{{margin-top:28px;padding:16px;border-radius:14px;background:#fff1f2;color:#a82035;font-size:14px}}</style></head><body><main><div class="brand"><img src="/static/viralizer-original-logo.png" alt="Viralizer"></div><div class="progress"></div><h1>Create content people stop for.</h1><p>Discover a timely idea, direct the video, add your voice and branding, then publish—all in one guided journey.</p>{action}<p class="note">Secure Google sign-in · Your existing Viralizer account is used</p></main></body></html>""")


@app.get("/creatorthon-v2")
async def creatorthon_v2(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon-v2/login", status_code=303)
    return FileResponse(
        ROOT / "static" / "creatorthon-v2.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


def creatorthon_user(request: Request) -> dict[str, Any]:
    user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
    if not user:
        raise HTTPException(401, "Google sign-in required.")
    return user


@app.get("/api/creatorthon/profile")
async def creatorthon_profile(request: Request):
    user = creatorthon_user(request)
    return {"profile": get_profile(ROOT, user), "projects": list_projects(ROOT, str(user.get("sub", "")))}


@app.put("/api/creatorthon/profile")
async def update_creatorthon_profile(request: Request, payload: CreatorthonProfileRequest):
    user = creatorthon_user(request)
    if payload.onboarding_complete and not payload.interests:
        raise HTTPException(422, "Select at least one interest.")
    return {"profile": save_profile(ROOT, user, payload.model_dump())}


@app.post("/api/creatorthon/topics")
async def creatorthon_topics(request: Request, payload: CreatorthonTopicsRequest):
    creatorthon_user(request)
    interests = list(dict.fromkeys(value.strip() for value in payload.interests if value.strip()))[:4]
    if not interests:
        raise HTTPException(422, "Select at least one interest.")
    queries: list[str] = []
    for interest in interests:
        queries.extend(build_category_discovery_queries(interest, "", "", "Everything", "")[:2])
    try:
        topics = await discover_category_topics(queries, 24)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not discover worldwide topics: {exc}") from exc
    topics = annotate_topic_taxonomy(topics, interests, "Creatorthon", "Everything")
    return {"topics": topics, "count": len(topics), "source": "Worldwide public news sources"}


@app.post("/api/creatorthon/projects")
async def new_creatorthon_project(request: Request, payload: CreatorthonProjectRequest):
    user = creatorthon_user(request)
    if not str(payload.topic.get("topic") or payload.topic.get("title") or "").strip():
        raise HTTPException(422, "Choose a valid topic.")
    return create_project(ROOT, str(user.get("sub", "")), payload.topic)


@app.patch("/api/creatorthon/projects/{project_id}")
async def patch_creatorthon_project(request: Request, project_id: str, payload: CreatorthonProjectUpdateRequest):
    user = creatorthon_user(request)
    result = update_project(ROOT, str(user.get("sub", "")), project_id, payload.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(404, "Creatorthon project not found.")
    return result


@app.get("/api/creatorthon/publishing/status")
async def creatorthon_publishing_status(request: Request):
    creatorthon_user(request)
    return {"platforms": publishing_status(), "mandatory_hashtag": MANDATORY_HASHTAG}


@app.post("/api/creatorthon/hashtags")
async def creatorthon_hashtags(request: Request, payload: CreatorthonHashtagRequest):
    creatorthon_user(request)
    return {"hashtags": build_hashtags(payload.topic), "mandatory_hashtag": MANDATORY_HASHTAG}


@app.post("/api/creatorthon/publish")
async def publish_creatorthon_video(request: Request, payload: CreatorthonPublishRequest):
    user = creatorthon_user(request)
    project = update_project(ROOT, str(user.get("sub", "")), payload.project_id, {})
    if not project:
        raise HTTPException(404, "Creatorthon project not found.")
    match = re.fullmatch(r"/api/finished-video/(viralizer-(?:hybrid-)?[a-f0-9]{32}\.mp4)", payload.video_url)
    if not match:
        raise HTTPException(422, "Only a completed, watermarked Creatorthon video can be published.")
    video_path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / match.group(1)
    if not video_path.is_file():
        raise HTTPException(404, "The completed video could not be found.")
    hashtags = list(dict.fromkeys(value.strip() for value in payload.hashtags if value.strip()))
    if MANDATORY_HASHTAG.lower() not in {value.lower() for value in hashtags}:
        hashtags.insert(0, MANDATORY_HASHTAG)
    try:
        result = await publish_all(video_path, payload.video_url, payload.caption, hashtags, payload.platforms)
    except SocialPublishError as exc:
        raise HTTPException(422, str(exc)) from exc
    update_project(
        ROOT, str(user.get("sub", "")), payload.project_id,
        {"status": "published" if result["all_published"] else "publish-partial"},
    )
    return {**result, "hashtags": hashtags}


@app.get("/legacy")
async def legacy_ui():
    """Compatibility alias for the approved Viralizer interface."""
    return RedirectResponse(url="/?design=viralizer-exact", status_code=302)


@app.get("/studio")
async def full_studio():
    """All production creation and intelligence tools for preview validation."""
    return FileResponse(
        ROOT / "static" / "full_studio.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/redesign")
async def redesign():
    """Alias for the approved Viralizer Video Studio interface."""
    return FileResponse(
        ROOT / "static" / "pixel_ui.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


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
async def daily_run(request: DailyDiscoveryRequest | None = None):
    options = request.model_dump() if request else {}
    started = daily_trends.start(options)
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
        return await outline_with_fallback(request.topic.strip())
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/site-url/analyze")
async def analyze_site_url(request: SiteUrlVideoRequest):
    try:
        analysis = await analyze_website(request.url)
    except WebsiteAnalysisError as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "The public website could not be read right now.") from exc
    content = analysis["content"]
    analysis["prompt"] = build_video_prompt(
        content,
        request.duration,
        quality_mode=True,
        aspect_ratio=request.aspect_ratio,
    )
    analysis["narration"] = build_narration_script(content, request.duration)
    raw_options = [analysis["selected"], *analysis.get("alternatives", [])]
    content_options = []
    for index, option in enumerate(raw_options):
        option_content = dict(content)
        option_title = str(option.get("title") or content["topic"]).strip()
        option_summary = str(option.get("summary") or content.get("summary") or "").strip()
        option_url = str(option.get("url") or analysis["source_url"]).strip()
        option_content.update({
            "topic": option_title,
            "suggested_title": option_title,
            "summary": option_summary,
            "why_it_matters": option_summary,
            "source_url": option_url,
            "source_urls": [option_url],
            "published_at": option.get("published_at", ""),
        })
        content_options.append({
            "id": f"website-option-{index + 1}",
            "title": option_title,
            "summary": option_summary,
            "url": option_url,
            "published_at": option.get("published_at", ""),
            "content": option_content,
            "prompt": build_video_prompt(option_content, request.duration, quality_mode=True, aspect_ratio=request.aspect_ratio),
            "narration": build_narration_script(option_content, request.duration),
        })
    analysis["content_options"] = content_options
    analysis["duration"] = request.duration
    analysis["aspect_ratio"] = request.aspect_ratio
    analysis["transfer_version"] = 2
    return analysis


@app.get("/api/topics/hot")
async def hot_topics():
    try:
        return {"topics": await get_hot_topics_from_mcp(), "source": "Viralizer MCP"}
    except MCPOutlineError as exc:
        try:
            topics = await discover_global_sources()
        except Exception as fallback_exc:
            raise HTTPException(502, str(exc)) from fallback_exc
        return {
            "topics": topics,
            "source": "Worldwide public sources",
            "notice": "Viralizer MCP was unavailable, so current public-source trends are shown.",
        }


@app.get("/api/taxonomy")
async def taxonomy():
    return load_taxonomy()


@app.post("/api/taxonomy/upload")
async def upload_taxonomy(file: UploadFile = File(...)):
    try:
        return save_uploaded_taxonomy(file.filename or "taxonomy.json", await file.read())
    except TaxonomyError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/topics/hot/{topic_id}")
async def hot_topic_details(topic_id: str):
    try:
        return await hot_topic_details_with_retry(topic_id)
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/ideas/smith")
async def idea_smith(request: IdeaSmithRequest):
    try:
        return await get_idea_smith_from_mcp(request.topic)
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/category/intelligence")
async def category_intelligence(request: CategoryIntelligenceRequest):
    try:
        return await category_intelligence_with_retry(request)
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/category/topics")
async def category_topics(request: CategoryIntelligenceRequest):
    category = " ".join(request.category.split()[:8])
    super_category = " ".join(request.super_category.split()[:10])
    categories = [" ".join(value.split()[:8]) for value in request.categories if value.strip()][:50]
    keyword = " ".join(request.keyword.split()[:8])
    description = " ".join(request.description.split()[:10])
    lens = " ".join(request.lens.split()[:4])
    reputation = " ".join(request.reputation.split()[:3])
    if categories:
        # Search every category in the selected super category, grouped to keep
        # worldwide discovery responsive and within provider query limits.
        queries = []
        for start in range(0, len(categories), 4):
            batch = categories[start:start + 4]
            grouped_category = "(" + " OR ".join(f'\"{name}\"' for name in batch) + ")"
            queries.extend(build_category_discovery_queries(grouped_category, keyword, description, lens, reputation))
    else:
        queries = build_category_discovery_queries(category, keyword, description, lens, reputation)
    try:
        topics = await discover_category_topics(queries, 30)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not discover worldwide category topics: {exc}") from exc
    topics = annotate_topic_taxonomy(topics, categories or [category], super_category or category, lens)
    return {"queries": queries, "count": len(topics), "topics": topics, "source": "Worldwide public news sources", "categories_searched": categories or [category]}


@app.get("/api/heygen/avatars")
async def heygen_avatars():
    try:
        data = await HeyGenClient().avatars()
        return {"avatars": data.get("avatars") or data.get("items") or []}
    except HeyGenError as exc:
        raise HTTPException(502, str(exc)) from exc

@app.get("/api/heygen/voices")
async def heygen_voices():
    try:
        data = await HeyGenClient().voices()
        return {"voices": data.get("voices") or data.get("items") or []}
    except HeyGenError as exc:
        raise HTTPException(502, str(exc)) from exc
@app.get("/api/heygen/styles")
async def heygen_styles():
    try:
        data = await HeyGenClient().agent_styles()
        styles = data if isinstance(data, list) else data.get("styles") or data.get("items") or []
        return {"styles": styles}
    except HeyGenError as exc:
        raise HTTPException(502, str(exc)) from exc
@app.post("/api/video/generate")
async def generate_video(request: GenerateRequest):
    content = await prepare_article_intelligence(request.content, request.duration, request.aspect_ratio)
    selected_provider = request.provider
    if selected_provider == "auto":
        routing_text = " ".join(str(content.get(key) or "") for key in ("topic", "category", "video_idea", "creator_angle")).lower()
        presenter_intent = any(word in routing_text for word in ("presenter", "spokesperson", "talking", "host", "explainer", "news anchor"))
        selected_provider = "heygen" if presenter_intent and request.aspect_ratio in {"9:16", "16:9"} and bool(os.getenv("HEYGEN_API_KEY", "").strip()) else "pixverse"
    production = prepare_production(content, request.duration, request.prompt or "", quality_mode=request.quality_mode, aspect_ratio=request.aspect_ratio, quality=request.quality, generation_type="text_to_video")
    prompt = production["prompt"]
    if not prompt:
        raise HTTPException(422, "The selected content did not produce a usable video direction.")
    if selected_provider == "hybrid":
        script = request.narration or build_heygen_script(content, request.duration)
        job_id = start_hybrid_video(content, request.duration, request.quality, script, request.avatar_id, request.voice_id, request.background, request.quality_mode)
        production.update(job_id=job_id, provider="hybrid", status="processing", generation_mode="hybrid", motion_prompt=build_presenter_direction(content, request.duration))
        record_production(production, Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))))
        return {"job_id": job_id, "provider": "hybrid", "status": "processing", "prompt": prompt, "quality_mode": request.quality_mode, "stage": "Planning presenter and content visuals"}
    if selected_provider == "pixverse" and (request.duration > 15 or request.quality_mode):
        if selected_provider != "pixverse":
            raise HTTPException(422, "Long multi-clip videos currently require PixVerse.")
        job_id = start_long_video(content, request.duration, request.quality, quality_mode=request.quality_mode, production=production)
        production.update(job_id=job_id, provider="viralizer", status="processing")
        record_production(production, Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))))
        return {"job_id": job_id, "provider": "viralizer", "status": "processing", "prompt": prompt, "multi_clip": True, "quality_mode": request.quality_mode, "stage": "Preparing scenes"}
    try:
        job_id = await generate_with_provider(
            selected_provider,
            prompt,
            content=content,
            duration=request.duration,
            quality=request.quality,
            narration=request.narration or (build_heygen_script(content, request.duration) if selected_provider == "heygen" else build_narration_script(content, request.duration)),
            avatar_id=request.avatar_id,
            voice_id=request.voice_id,
            background=request.background,
            aspect_ratio=request.aspect_ratio,
            visual_mode=request.visual_mode,
            captions=request.captions,
            style_id=request.heygen_style_id,
            brand_kit_id=request.brand_kit_id,
        )
        production.update(job_id=job_id, provider=selected_provider, status="processing")
        record_production(production, Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))))
        return {"job_id": job_id, "provider": selected_provider, "status": "processing", "prompt": prompt, "quality_mode": request.quality_mode, "stage": "Generating video"}
    except VideoProviderError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/video/image/generate")
async def generate_image_video(
    content_json: str = Form(...),
    prompt: str = Form(""),
    image_url: str = Form(""),
    duration: int = Form(5),
    quality: str = Form("720p"),
    allow_text: bool = Form(False),
    image: UploadFile | None = File(None),
    person_images: list[UploadFile] | None = File(None),
    product_images: list[UploadFile] | None = File(None),
    ad_images: list[UploadFile] | None = File(None),
    logo_images: list[UploadFile] | None = File(None),
):
    try:
        content = json.loads(content_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "The selected topic content is invalid.") from exc
    if not isinstance(content, dict):
        raise HTTPException(422, "The selected topic content is invalid.")
    role_uploads = {
        "person": person_images or [],
        "product": product_images or [],
        "advertising style": ad_images or [],
        "logo": logo_images or [],
    }
    role_counts = {role: len(files) for role, files in role_uploads.items() if files}
    role_direction = "; ".join(f"{count} {role} reference{'s' if count != 1 else ''}" for role, count in role_counts.items())
    video_prompt = (prompt or build_video_prompt(content, duration, generation_type="image_to_video", quality_mode=True)).strip()
    if role_direction:
        video_prompt += f" References: {role_direction}. Preserve their exact identity and design."
    video_prompt += " Text is allowed only if requested." if allow_text else " No text."
    if not video_prompt:
        raise HTTPException(422, "The selected topic did not produce a usable video prompt.")
    image_bytes = None
    filename = "thumbnail.png"
    content_type = "image/png"
    all_role_files = [(role, upload) for role, uploads in role_uploads.items() for upload in uploads]
    if len(all_role_files) > 12:
        raise HTTPException(422, "Upload no more than 12 reference images in total.")
    if all_role_files:
        opened: list[Image.Image] = []
        for role, upload in all_role_files:
            raw = await upload.read(20 * 1024 * 1024 + 1)
            if len(raw) > 20 * 1024 * 1024:
                raise HTTPException(422, f"A {role} reference is larger than 20 MB.")
            if (upload.content_type or "") not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
                raise HTTPException(422, "Reference images must be PNG, JPG, JPEG, or WebP.")
            try:
                opened.append(Image.open(io.BytesIO(raw)).convert("RGB"))
            except Exception as exc:
                raise HTTPException(422, f"A {role} reference could not be read as an image.") from exc
        canvas = Image.new("RGB", (1080, 1920), (18, 18, 22))
        columns = 2
        rows = (len(opened) + columns - 1) // columns
        cell_width, cell_height = 540, 1920 // max(1, rows)
        for index, source in enumerate(opened):
            fitted = ImageOps.fit(source, (cell_width, cell_height), method=Image.Resampling.LANCZOS)
            canvas.paste(fitted, ((index % columns) * cell_width, (index // columns) * cell_height))
        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        image_bytes = output.getvalue()
        filename = "reference-board.png"
        content_type = "image/png"
    elif image is not None:
        image_bytes = await image.read(20 * 1024 * 1024 + 1)
        if len(image_bytes) > 20 * 1024 * 1024:
            raise HTTPException(422, "The uploaded thumbnail must be smaller than 20 MB.")
        content_type = image.content_type or "image/png"
        if content_type not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
            raise HTTPException(422, "Upload a PNG, JPG, JPEG, or WebP thumbnail.")
        filename = image.filename or filename
    elif not image_url.startswith(("http://", "https://")):
        raise HTTPException(422, "Select a topic thumbnail or upload your own thumbnail.")
    try:
        client = PixVerseClient()
        image_id = await client.upload_image(
            image_url=image_url.strip(),
            image_bytes=image_bytes,
            filename=filename,
            content_type=content_type,
        )
        video_id = await client.generate_from_image(
            image_id,
            video_prompt,
            duration=max(5, min(15, duration)),
            quality=quality,
        )
    except PixVerseError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"job_id": video_id, "provider": "pixverse", "status": "processing", "prompt": video_prompt}


@app.post("/api/video/prepare-topic")
async def prepare_exact_video_topic(request: TopicRequest):
    selected_topic = " ".join(request.topic.split())
    if not selected_topic:
        raise HTTPException(422, "Choose a topic first.")
    # Refresh restoration must be immediate and deterministic. The discovery page
    # already fetched the full MCP report before transfer; calling MCP again here
    # caused cold-start delays and could return an unrelated cached report.
    outline = {
        "topic": selected_topic,
        "suggested_title": selected_topic,
        "video_idea": f"Create a focused video about {selected_topic}.",
        "why_it_matters": f"Show the most useful and visually meaningful aspect of {selected_topic}.",
    }
    prompt = build_video_prompt(outline, 5)
    return {"selected_topic": selected_topic, "outline": outline, "prompt": prompt, "narration": build_narration_script(outline, 5), "transfer_version": 2}

@app.post("/api/video/logo-suggestions")
async def video_logo_suggestions(request: LogoSuggestionRequest):
    try:
        logos = await suggest_logos_for_content(request.content)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not look up logo suggestions.") from exc
    return {"logos": logos}

@app.get("/api/site-logo")
async def site_logo(url: str):
    try:
        image, content_type = await fetch_public_image(url)
    except WebsiteAnalysisError as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "The website logo could not be fetched.") from exc
    return Response(content=image, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/video/providers")
async def video_providers():
    return {"providers": provider_catalog()}
@app.post("/api/video/prompt")
async def video_prompt(request: GenerateRequest):
    content = await prepare_article_intelligence(request.content, request.duration, request.aspect_ratio)
    prompt_result = build_video_prompt(
        content,
        request.duration,
        generation_type=request.generation_type,
        quality_mode=request.quality_mode,
        user_prompt=request.prompt or "",
        include_debug=request.debug_prompt,
        aspect_ratio=request.aspect_ratio,
    )
    prompt, motion_debug = prompt_result if request.debug_prompt else (prompt_result, None)
    platform = " ".join(request.target_platform.split()[:4]).strip()
    if platform:
        safe_areas = {
            "9:16": "Keep essential subjects inside the central 80%; leave the top 10% and bottom 20% visually quiet for platform controls.",
            "3:4": "Keep essential subjects and brand elements inside the central 84% with clean margins on every edge.",
            "1:1": "Use centered square-safe composition with essential subjects inside the central 82%.",
            "16:9": "Use landscape-safe composition with essential subjects inside the central 86% and clean lower-third space.",
        }
        prompt = f"{prompt} Delivery target: {platform}, {request.aspect_ratio}. {safe_areas.get(request.aspect_ratio, safe_areas['9:16'])} Do not render platform logos or platform interface elements."
    heygen_plan = build_heygen_plan(content, request.duration, visual_mode=request.visual_mode, aspect_ratio=request.aspect_ratio, captions=request.captions, user_direction=request.prompt or "")
    heygen_payload = compile_heygen_request(heygen_plan, avatar_id=request.avatar_id, voice_id=request.voice_id, style_id=request.heygen_style_id, brand_kit_id=request.brand_kit_id)
    response = {"prompt": prompt, "narration": build_narration_script(content, request.duration), "heygen_script": heygen_plan["script"], "heygen_direction": heygen_plan["compiled_prompt"], "heygen_plan": heygen_plan, "heygen_request": heygen_payload, "content": content, "article_intelligence": content.get("article_intelligence", {})}
    if motion_debug is not None:
        response["motion_director"] = motion_debug
    return response

@app.get("/api/video/{provider}/{job_id}")
async def video_status(provider: str, job_id: str):
    if provider == "hybrid":
        result = hybrid_video_status(job_id)
        if result is None: raise HTTPException(404, "Hybrid video job not found.")
        return {"job_id": job_id, "provider": provider, **result}
    if provider == "viralizer":
        result = long_video_status(job_id)
        if result is None:
            raise HTTPException(404, "Long video job not found.")
        return {"job_id": job_id, "provider": provider, **result}
    try:
        result = await provider_video_status(provider, job_id)
    except VideoProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"job_id": job_id, "provider": provider, **result}


@app.get("/api/videos/saved")
async def saved_video_library():
    return {"videos": list_saved_videos(ROOT)}


@app.post("/api/videos/save")
async def save_generated_video(request: SaveVideoRequest):
    try:
        return await save_video(ROOT, request.video_url, request.title, request.provider)
    except SavedVideoError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/video/finish")
async def finish_generated_video(video_url: str = Form(...), narration: str = Form(""), voice: str = Form("coral"), logo: UploadFile | None = File(None), logo_url: str = Form(""), overlay_number: str = Form(""), overlay_text: str = Form(""), overlay_position: str = Form("bottom-center"), overlay_color: str = Form("white")):
    narration = narration.strip()
    if len(narration) > 4096:
        raise HTTPException(422, "Narration must be 4,096 characters or fewer.")
    logo_bytes = None
    if logo is not None:
        if (logo.content_type or "") not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
            raise HTTPException(422, "Logo must be PNG, JPG, JPEG, or WebP.")
        logo_bytes = await logo.read(10 * 1024 * 1024 + 1)
        if len(logo_bytes) > 10 * 1024 * 1024:
            raise HTTPException(422, "Logo must be smaller than 10 MB.")
    overlay_number = overlay_number.strip()
    overlay_text = overlay_text.strip()
    if len(overlay_number) > 80 or len(overlay_text) > 240:
        raise HTTPException(422, "Overlay number or text is too long.")
    if overlay_position not in {"top-left", "top-center", "top-right", "center", "bottom-left", "bottom-center", "bottom-right"}:
        raise HTTPException(422, "The selected text position is not supported.")
    if overlay_color not in {"white", "yellow", "black", "red", "lime", "cyan"}:
        raise HTTPException(422, "The selected text color is not supported.")
    combined_overlay = "\n".join(value for value in (overlay_number, overlay_text) if value)
    logo_url = logo_url.strip()
    if logo_bytes is None and logo_url:
        parsed_logo = httpx.URL(logo_url)
        if logo_url.startswith("/api/site-logo?"):
            source_logo = str(parsed_logo.params.get("url") or "")
            if not source_logo:
                raise HTTPException(422, "The selected website logo is invalid.")
            try:
                logo_bytes, _ = await fetch_public_image(source_logo)
            except WebsiteAnalysisError as exc:
                raise HTTPException(422, str(exc)) from exc
            except httpx.HTTPError as exc:
                raise HTTPException(502, "Could not retrieve the selected website logo.") from exc
        else:
            allowed_logo_hosts = {"www.google.com", "commons.wikimedia.org", "upload.wikimedia.org"}
            if parsed_logo.scheme != "https" or parsed_logo.host not in allowed_logo_hosts:
                raise HTTPException(422, "Select a verified Viralizer logo or upload your own.")
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    logo_response = await client.get(logo_url)
                    logo_response.raise_for_status()
                final_logo_host = str(logo_response.url.host or "")
                trusted_google_favicon = bool(re.fullmatch(r"t\d+\.gstatic\.com", final_logo_host)) and logo_response.url.path == "/faviconV2"
                if final_logo_host not in allowed_logo_hosts and not trusted_google_favicon:
                    raise HTTPException(422, "The logo source redirected to an unsupported website.")
                if len(logo_response.content) > 10 * 1024 * 1024:
                    raise HTTPException(422, "Suggested logo must be smaller than 10 MB.")
                logo_bytes = logo_response.content
            except HTTPException:
                raise
            except httpx.HTTPError as exc:
                raise HTTPException(502, "Could not retrieve the selected logo.") from exc
    if not narration and not logo_bytes and not combined_overlay:
        raise HTTPException(422, "Add narration, a logo, or a text overlay.")
    try:
        output = await finish_video(video_url, narration, voice, logo_bytes, combined_overlay, overlay_position, overlay_color)
    except MediaFinisherError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"url": f"/api/finished-video/{output.name}"}


@app.post("/api/creatorthon/finish")
async def finish_creatorthon_video(request: Request, payload: CreatorthonFinishRequest):
    creatorthon_user(request)
    # Creatorthon branding is server-enforced. The client cannot omit or move it.
    logo_bytes = (ROOT / "static" / "viralizer-original-logo.png").read_bytes()
    official_logo_bytes = None
    if payload.official_logo_data:
        match = re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\r\n]+)", payload.official_logo_data)
        if not match:
            raise HTTPException(422, "Official logo must be a PNG, JPG, JPEG, or WebP image.")
        try:
            official_logo_bytes = base64.b64decode(match.group(1), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(422, "Official logo data is invalid.") from exc
        if len(official_logo_bytes) > 10 * 1024 * 1024:
            raise HTTPException(422, "Official logo must be smaller than 10 MB.")
    try:
        output = await finish_video(payload.video_url, payload.narration, payload.voice, logo_bytes, secondary_logo_bytes=official_logo_bytes)
    except MediaFinisherError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"url": f"/api/finished-video/{output.name}"}


@app.get("/api/finished-video/{filename}")
async def finished_video(filename: str):
    if not re.fullmatch(r"viralizer-(?:hybrid-)?[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(404, "Finished video not found.")
    path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / filename
    if not path.is_file():
        raise HTTPException(404, "Finished video not found.")
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )

@app.get("/api/video/reference/{job_id}/{scene_index}")
async def video_reference_image(job_id: str, scene_index: int):
    if not re.fullmatch(r"long-[a-f0-9]{32}", job_id) or scene_index < 0 or scene_index > 20:
        raise HTTPException(404, "Reference image not found.")
    filename = f"reference-{job_id}-{scene_index}.png"
    path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / filename
    if not path.is_file():
        raise HTTPException(404, "Reference image not found.")
    return FileResponse(path, media_type="image/png", headers={"Content-Disposition": f'inline; filename="{filename}"'})

def growth_http_error(exc: PixVerseGrowthError) -> HTTPException:
    status_code = {
        "INVALID_REQUEST": 422, "INVALID_API_KEY": 401, "INSUFFICIENT_BALANCE": 402,
        "WORKSPACE_ACCESS_DENIED": 403, "VIDEO_NOT_FOUND": 404,
        "VIDEO_EDIT_UNAVAILABLE": 409, "PAYLOAD_TOO_LARGE": 413,
        "UNSUPPORTED_MEDIA_TYPE": 415, "PRODUCT_FETCH_FAILED": 422,
        "MEDIA_PROCESSING_FAILED": 422, "RATE_LIMIT_EXCEEDED": 429,
    }.get(exc.code, 503 if exc.retryable else 502)
    detail = str(exc)
    if exc.request_id:
        detail += f" (request_id={exc.request_id})"
    return HTTPException(status_code, detail)


@app.get("/api/growth/avatars")
async def growth_avatars():
    try:
        return await PixVerseGrowthClient().avatars()
    except PixVerseGrowthError as exc:
        raise growth_http_error(exc) from exc


@app.post("/api/growth/videos")
async def create_growth_video(
    source_url: str = Form(""),
    title: str = Form(""),
    description: str = Form(""),
    brand: str = Form(""),
    price_amount: str = Form(""),
    price_currency: str = Form("USD"),
    aspect_ratio: str = Form("9:16"),
    duration_seconds: int = Form(30),
    resolution: str = Form("1080p"),
    language: str = Form("en-US"),
    voiceover: bool = Form(True),
    captions: bool = Form(True),
    background_music: bool = Form(True),
    avatar_mode: str = Form("auto"),
    avatar_url: str = Form(""),
    product_images: list[UploadFile] | None = File(None),
    avatar_image: UploadFile | None = File(None),
):
    source_url, title = source_url.strip(), title.strip()
    if source_url and not source_url.startswith(("http://", "https://")):
        raise HTTPException(422, "Product URL must begin with http:// or https://.")
    uploads = product_images or []
    if len(uploads) > 6:
        raise HTTPException(422, "Upload no more than six product images.")
    if not source_url and (not title or not uploads):
        raise HTTPException(422, "Without a product URL, provide a product title and at least one product image.")
    if duration_seconds not in {15, 30, 45, 60}:
        raise HTTPException(422, "Growth Studio duration must be 15, 30, 45, or 60 seconds.")
    if resolution.lower() not in {"480p", "720p", "1080p"}:
        raise HTTPException(422, "Growth Studio resolution must be 480p, 720p, or 1080p.")
    if avatar_mode not in {"auto", "custom", "disabled"}:
        raise HTTPException(422, "Avatar mode must be auto, custom, or disabled.")
    try:
        client = PixVerseGrowthClient()
    except PixVerseGrowthError as exc:
        raise growth_http_error(exc) from exc

    async def upload(upload_file: UploadFile) -> str:
        content_type = (upload_file.content_type or "").lower()
        if content_type not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
            raise HTTPException(415, "Growth Studio images must be JPEG, PNG, or WebP.")
        raw = await upload_file.read(20 * 1024 * 1024 + 1)
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "Each Growth Studio image must be 20 MiB or smaller.")
        try:
            result = await client.upload_image(raw, upload_file.filename or "image.png", content_type)
        except PixVerseGrowthError as exc:
            raise growth_http_error(exc) from exc
        data = result.get("data") or result
        return str(data.get("url") or data.get("image_url") or "")

    image_urls = [await upload(image) for image in uploads]
    if any(not value for value in image_urls):
        raise HTTPException(502, "Growth Studio did not return a URL for an uploaded product image.")
    if avatar_image is not None:
        avatar_url = await upload(avatar_image)
        avatar_mode = "custom"
    if avatar_mode == "custom" and not avatar_url.startswith("https://"):
        raise HTTPException(422, "Choose a system Avatar or upload a custom Avatar image.")

    product: dict[str, Any] = {}
    if source_url:
        product["source_url"] = source_url[:2048]
    if title:
        product["title"] = title[:255]
    if description.strip():
        product["description"] = description.strip()[:5120]
    if brand.strip():
        product["brand"] = brand.strip()[:255]
    if price_amount.strip():
        product["price"] = {"amount": price_amount.strip(), "currency": price_currency.strip().upper()[:3]}
    if image_urls:
        product["images"] = [{"url": value} for value in image_urls]
    video = {
        "aspect_ratio": aspect_ratio, "duration_seconds": duration_seconds,
        "resolution": resolution.lower(), "language": language,
        "voiceover": voiceover, "captions": captions, "background_music": background_music,
        "avatar": {"mode": avatar_mode},
    }
    if avatar_mode == "custom":
        video["avatar"]["url"] = avatar_url
    try:
        return await client.create_video({"product": product, "video": video, "metadata": {"source": "viralizer-studio"}})
    except PixVerseGrowthError as exc:
        raise growth_http_error(exc) from exc


@app.get("/api/growth/videos")
async def list_growth_videos(limit: int = 20, cursor: str = "", status: str = ""):
    if status and status not in {"queued", "processing", "succeeded", "failed", "canceled"}:
        raise HTTPException(422, "Invalid Growth Studio status filter.")
    try:
        return await PixVerseGrowthClient().list_videos(limit=limit, cursor=cursor, status=status)
    except PixVerseGrowthError as exc:
        raise growth_http_error(exc) from exc


@app.get("/api/growth/videos/{video_id}")
async def growth_video_details(video_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", video_id):
        raise HTTPException(422, "Invalid Growth Studio video ID.")
    try:
        return await PixVerseGrowthClient().video_details(video_id)
    except PixVerseGrowthError as exc:
        raise growth_http_error(exc) from exc


@app.post("/api/growth/videos/{video_id}/edit")
async def edit_growth_video(video_id: str, request: GrowthEditRequest):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", video_id):
        raise HTTPException(422, "Invalid Growth Studio video ID.")
    try:
        return await PixVerseGrowthClient().edit_video(video_id, request.clip_index, request.instruction)
    except PixVerseGrowthError as exc:
        raise growth_http_error(exc) from exc


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


@app.post("/api/image/generate")
async def generate_image(request: ImageGenerateRequest):
    try:
        if request.provider == "cloudflare":
            image = await generate_cloudflare_image(request.content, request.prompt, request.purpose)
        else:
            image = await generate_instagram_image(request.content, request.prompt, request.purpose)
    except (OpenAIImageError, CloudflareImageError) as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(content=image, media_type="image/png")


@app.post("/api/image/reference/generate")
async def generate_image_from_reference(
    prompt: str = Form(...),
    image_url: str = Form(""),
    image: UploadFile | None = File(None),
    person_images: list[UploadFile] | None = File(None),
    product_images: list[UploadFile] | None = File(None),
    ad_images: list[UploadFile] | None = File(None),
    logo_images: list[UploadFile] | None = File(None),
):
    role_groups = (
        ("person", person_images or []),
        ("product", product_images or []),
        ("ad reference", ad_images or []),
        ("logo", logo_images or []),
    )
    role_files = [
        upload
        for _, uploads in role_groups
        for upload in uploads
    ]
    if len(role_files) > 12:
        raise HTTPException(422, "Upload no more than 12 reference images in total.")
    reference_bytes = None
    content_type = "image/png"
    if role_files:
        opened: list[Image.Image] = []
        for upload in role_files:
            raw = await upload.read(20 * 1024 * 1024 + 1)
            if len(raw) > 20 * 1024 * 1024:
                raise HTTPException(422, "Each reference image must be smaller than 20 MB.")
            try:
                opened.append(Image.open(io.BytesIO(raw)).convert("RGB"))
            except Exception as exc:
                raise HTTPException(422, "A reference file could not be read as an image.") from exc
        canvas = Image.new("RGB", (1024, 1024), (18, 18, 22))
        rows = (len(opened) + 1) // 2
        for index, source in enumerate(opened):
            fitted = ImageOps.fit(source, (512, 1024 // max(1, rows)), method=Image.Resampling.LANCZOS)
            canvas.paste(fitted, ((index % 2) * 512, (index // 2) * (1024 // max(1, rows))))
        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        reference_bytes = output.getvalue()
        supplied_roles = ", ".join(
            f"{len(uploads)} {name}{'' if len(uploads) == 1 else ' images'}"
            for name, uploads in role_groups
            if uploads
        )
        prompt = (
            f"{prompt.strip()} Use the actual uploaded references ({supplied_roles}). "
            "Preserve the people's identity, product appearance, ad styling, and logo exactly where supplied. "
            "Do not replace them with invented alternatives."
        )
    elif image is not None:
        reference_bytes = await image.read(20 * 1024 * 1024 + 1)
        if len(reference_bytes) > 20 * 1024 * 1024:
            raise HTTPException(422, "The uploaded image must be smaller than 20 MB.")
        content_type = image.content_type or content_type
        prompt = (
            f"{prompt.strip()} Use the actual uploaded image as the primary reference. "
            "Preserve its main subject, identity, product details, and branding, but create a clearly different "
            "scene, camera angle, background, pose, and composition. Do not copy the original layout."
        )
    elif image_url.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(image_url)
                response.raise_for_status()
                reference_bytes = response.content
                content_type = response.headers.get("content-type", "image/png").split(";", 1)[0]
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Could not download the selected thumbnail.") from exc
        if len(reference_bytes) > 20 * 1024 * 1024:
            raise HTTPException(422, "The selected thumbnail is larger than 20 MB.")
        prompt = (
            f"{prompt.strip()} Use the selected thumbnail as the primary reference. "
            "Preserve its main subject, identity, product details, and branding, but create a clearly different "
            "scene, camera angle, background, pose, and composition. Do not copy the original layout."
        )
    else:
        raise HTTPException(422, "Select or upload a reference image first.")
    try:
        generated = await generate_reference_image(reference_bytes, prompt, content_type)
        return Response(content=generated, media_type="image/png")
    except OpenAIImageError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/image/prompt")
async def image_prompt(request: ImageGenerateRequest):
    return {"prompt": await prepare_image_prompt(request.content, request.purpose)}


@app.post("/api/thumbnail/prompts")
async def thumbnail_prompts(
    content_json: str = Form("{}"),
    image_url: str = Form(""),
    use_topic_context: bool = Form(False),
    duration: int = Form(5),
    image: UploadFile | None = File(None),
    person_images: list[UploadFile] | None = File(None),
    product_images: list[UploadFile] | None = File(None),
    ad_images: list[UploadFile] | None = File(None),
    logo_images: list[UploadFile] | None = File(None),
):
    try:
        content = json.loads(content_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "The selected topic content is invalid.") from exc
    image_bytes = None
    content_type = "image/png"
    role_groups = (
        ("person", person_images or []),
        ("product", product_images or []),
        ("ad reference", ad_images or []),
        ("logo", logo_images or []),
    )
    role_files = [
        upload
        for _, uploads in role_groups
        for upload in uploads
    ]
    if len(role_files) > 12:
        raise HTTPException(422, "Upload no more than 12 reference images in total.")
    if role_files:
        opened: list[Image.Image] = []
        for upload in role_files:
            raw = await upload.read(20 * 1024 * 1024 + 1)
            if len(raw) > 20 * 1024 * 1024:
                raise HTTPException(422, "Each reference image must be smaller than 20 MB.")
            try:
                opened.append(Image.open(io.BytesIO(raw)).convert("RGB"))
            except Exception as exc:
                raise HTTPException(422, "A reference file could not be read as an image.") from exc
        canvas = Image.new("RGB", (1024, 1024), (18, 18, 22))
        columns = 2
        rows = (len(opened) + 1) // 2
        cell_width, cell_height = 512, 1024 // max(1, rows)
        for index, source in enumerate(opened):
            fitted = ImageOps.fit(source, (cell_width, cell_height), method=Image.Resampling.LANCZOS)
            canvas.paste(fitted, ((index % columns) * cell_width, (index // columns) * cell_height))
        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        image_bytes = output.getvalue()
    elif image is not None:
        image_bytes = await image.read(20 * 1024 * 1024 + 1)
        if len(image_bytes) > 20 * 1024 * 1024:
            raise HTTPException(422, "The uploaded thumbnail must be smaller than 20 MB.")
        content_type = image.content_type or content_type
        if content_type not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
            raise HTTPException(422, "Upload a PNG, JPG, JPEG, or WebP thumbnail.")
    elif not image_url.startswith(("http://", "https://")):
        raise HTTPException(422, "Select or upload a thumbnail first.")
    try:
        description = await analyze_reference_image(image_url, image_bytes, content_type)
        prompt_content = dict(content) if use_topic_context and isinstance(content, dict) else {"topic": "Reference image"}
        prompt_content["video_idea"] = " ".join(filter(None, [
            str(prompt_content.get("video_idea") or "").strip(),
            f"Reference-image details: {description}",
        ]))
        prompt_content["reference_description"] = description
        if role_files:
            supplied_roles = ", ".join(name for name, uploads in role_groups if uploads)
            image_prompt_value = (
                f"Use the uploaded {supplied_roles} images as the actual visual references. "
                "Preserve the people, products, branding, and logo exactly where supplied. "
                "Create one polished vertical composition. No added text."
            )
        else:
            image_prompt_value = (
                "Use the selected or uploaded image as the actual main reference. "
                "Preserve its subject, identity, product details, and branding. Create a clearly different "
                "scene, camera angle, background, pose, and vertical composition. Do not copy the original layout. "
                "No added text."
            )
        short_description = " ".join(description.split()[:35])
        video_prompt_value = (
            f"Animate this image for {max(5, min(15, duration))} seconds. Preserve the subject and composition. "
            f"{short_description} Natural motion, subtle background movement, smooth camera push-in, no text."
        )
        if use_topic_context and prompt_content.get("topic"):
            video_prompt_value += f" The animation must support this selected topic: {prompt_content['topic']}."
        return {"image_prompt": image_prompt_value, "video_prompt": video_prompt_value, "analysis": description}
    except OpenAIImageError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/image/openai/album")
async def generate_openai_album(request: ImageGenerateRequest):
    try:
        images = await generate_instagram_album(request.content, 5, request.prompt)
    except OpenAIImageError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "images": [f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}" for image in images]
    }


@app.post("/api/image/album")
async def generate_image_album(request: ImageGenerateRequest):
    try:
        if request.provider == "cloudflare":
            images = await generate_cloudflare_album(request.content, 5, request.prompt)
        else:
            images = await generate_instagram_album(request.content, 5, request.prompt)
    except (OpenAIImageError, CloudflareImageError) as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"images": [f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}" for image in images]}
