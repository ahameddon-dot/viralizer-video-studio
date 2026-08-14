import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import httpx
import io
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from PIL import Image, ImageOps

from pixverse_client import PixVerseClient, PixVerseError, build_video_prompt
from openai_image_client import OpenAIImageError, analyze_reference_image, generate_instagram_album, generate_instagram_image, generate_reference_image, prepare_image_prompt
from cloudflare_image_client import CloudflareImageError, generate_cloudflare_album, generate_cloudflare_image
from video_providers import (
    VideoProviderError,
    generate_video as generate_with_provider,
    provider_catalog,
    video_status as provider_video_status,
)
from daily_trends import daily_trends
from global_sources import discover_category_topics
from mcp_outline_client import (
    MCPOutlineError,
    get_full_report_from_mcp,
    get_hot_topic_details_from_mcp,
    get_hot_topics_from_mcp,
    get_idea_smith_from_mcp,
    get_category_intelligence_from_mcp,
    get_outline_from_mcp,
)
from viralizer_pdf import build_viralizer_pdf
from betting_topics import betting_report
from regional_trends import regional_report
from taxonomy import TaxonomyError, load_taxonomy, save_uploaded_taxonomy


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
    provider: str = "openai"


class TopicRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)


class IdeaSmithRequest(BaseModel):
    topic: str = Field(default="", max_length=500)


class CategoryIntelligenceRequest(BaseModel):
    category: str = Field(min_length=2, max_length=120)
    keyword: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    lens: str = Field(default="", max_length=80)
    reputation: str = Field(default="", max_length=80)


class DailyDiscoveryRequest(BaseModel):
    category: str = Field(default="ALL", max_length=80)
    keyword: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)


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
    variants = topic_variants(topic)
    for attempt in range(3):
        for variant in variants:
            try:
                return await get_outline_from_mcp(variant)
            except MCPOutlineError as exc:
                last_error = exc
        if attempt < 2:
            await asyncio.sleep(2 * (attempt + 1))
    raise last_error or MCPOutlineError("Viralizer returned no report for this topic.")


async def full_report_with_fallback(topic: str):
    last_error = None
    variants = topic_variants(topic)
    for attempt in range(3):
        for variant in variants:
            try:
                return await get_full_report_from_mcp(variant)
            except MCPOutlineError as exc:
                last_error = exc
        if attempt < 2:
            await asyncio.sleep(2 * (attempt + 1))
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


@app.get("/api/topics/hot")
async def hot_topics():
    try:
        return {"topics": await get_hot_topics_from_mcp()}
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


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
    keyword = " ".join(request.keyword.split()[:8])
    description = " ".join(request.description.split()[:10])
    lens = " ".join(request.lens.split()[:4])
    reputation = " ".join(request.reputation.split()[:3])
    parts = [keyword or category]
    if keyword and category.lower() not in keyword.lower():
        parts.append(category)
    if description:
        parts.append(description)
    elif lens and lens.lower() != "everything":
        parts.append(lens)
    if reputation and reputation.lower() != "all reputation":
        parts.append(reputation)
    query = " ".join(" ".join(parts).split()[:18])
    try:
        topics = await discover_category_topics(query, 30)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not discover worldwide category topics: {exc}") from exc
    return {"query": query, "count": len(topics), "topics": topics, "source": "Worldwide public news sources"}


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
    video_prompt = (prompt or build_video_prompt(content, duration)).strip()
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


@app.get("/api/video/providers")
async def video_providers():
    return {"providers": provider_catalog()}


@app.post("/api/video/prompt")
async def video_prompt(request: GenerateRequest):
    return {"prompt": build_video_prompt(request.content, request.duration)}


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
