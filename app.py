import asyncio
import base64
import binascii
import hashlib
import hmac
import html
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import httpx
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
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
from google_auth import GoogleAuthError, authorization_url as google_authorization_url, configured as google_configured, exchange_code as google_exchange_code, new_state as google_new_state, read_session as read_google_session, read_signed_payload as read_google_state, redirect_uri as google_redirect_uri, session_token as google_session_token, signed_payload as google_signed_payload, user_allowed as google_user_allowed
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
from creatorthon_store import (
    accept_event_generation, add_asset, claim_event_seat, create_project, delete_project, delete_project_video,
    delete_youtube_connection, generation_entitlement, get_profile, get_youtube_connection,
    event_admin_state, event_capacity, event_is_frozen, grant_event_admission, grant_extra_generation, remove_event_user,
    reset_event_roster, set_event_capacity, set_event_frozen, set_generation_allowance,
    list_assets, list_participant_videos, list_projects, list_reports, release_event_generation, reserve_event_generation,
    get_workflow_state, save_profile, save_report, save_workflow_state, save_youtube_connection, update_project, workspace,
    claim_next_insight_job, delete_insight_job, enqueue_insight_job, finish_insight_job, list_insight_jobs, retry_insight_job,
    get_cached_category_topics, get_cached_topic_insight,
    save_cached_category_topics, save_cached_topic_insight,
)
from social_publisher import MANDATORY_HASHTAG, SocialPublishError, build_hashtags, publish_all, publishing_status
from website_to_video import WebsiteAnalysisError, analyze_website, fetch_public_image
from article_intelligence import openai_story_analysis_complete, prepare_article_intelligence
from object_store import ObjectStoreError, delete_file as delete_object_file, restore_file as restore_object_file, share_url as object_share_url, upload_file as upload_object_file
from durable_media_pipeline import enqueue as enqueue_durable_media_job, get as get_durable_media_job
from youtube_oauth import YouTubeOAuthError, authorization_url as youtube_authorization_url, configured as youtube_oauth_configured, decrypt_refresh_token, exchange_connection as exchange_youtube_connection, redirect_uri as youtube_redirect_uri
from channel_automation import CATEGORIES as CHANNEL_AUTOMATION_CATEGORIES, ChannelAutomationError, ViralChannelAutomation, youtube_frame_auth_configured

# Short-lived, authenticated V1 post-production jobs. Keeping media finishing out
# of the browser request prevents proxy timeouts while narration is rendered.
CREATORTHON_FINISH_JOBS: dict[str, dict[str, Any]] = {}
CREATORTHON_INSIGHT_TASKS: dict[str, asyncio.Task] = {}
CREATORTHON_PREFETCH_TASK: asyncio.Task | None = None
PREDICTION_MARKET_PREFETCH_TASK: asyncio.Task | None = None
PREDICTION_MARKET_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
PREDICTION_COVERAGE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CHANNEL_AUTOMATION_TASK: asyncio.Task | None = None
YOUTUBE_STATE_COOKIE = "viralizer_youtube_oauth_state"
LOGGER = logging.getLogger("uvicorn.error")


async def prepare_article_intelligence_safely(
    content: dict[str, Any],
    duration: int,
    aspect_ratio: str,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Keep prompt preparation usable when a live publisher edge case fails."""
    try:
        work = prepare_article_intelligence(content, duration, aspect_ratio)
        if timeout_seconds is not None:
            return await asyncio.wait_for(work, timeout=max(0.05, timeout_seconds))
        return await work
    except Exception as exc:
        fallback = dict(content)
        fallback["article_intelligence"] = {
            "version": 3,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "extraction_state": "failed",
            "extraction_note": "The full story pipeline could not complete; available discovery metadata was used.",
            "analysis_model": "safe-discovery-metadata-fallback",
            "approved_for_media_generation": False,
            "fallback_reason": f"{type(exc).__name__}: {str(exc)[:240]}",
        }
        return fallback


def _provider_safe_product_prompt(prompt: str) -> str:
    """Keep cultural visuals while removing identity-sensitive provider trigger wording."""
    safe = str(prompt or "")
    replacements = {
        r"Tamil Muslim wedding(?:-style)?": "traditional Tamil wedding-service",
        r"Muslim wedding(?:-style)?": "traditional wedding-service",
        r"Beef where locally appropriate": "regional meat biryani",
    }
    for pattern, replacement in replacements.items():
        safe = re.sub(pattern, replacement, safe, flags=re.IGNORECASE)
    return safe


def _provider_safe_product_retry_prompt(content: dict[str, Any], duration: int, aspect_ratio: str) -> str:
    """Build a short visual-only retry after an upstream sensitive-text rejection."""
    product = str(content.get("product") or "").strip().casefold()
    aspect = {"9:16": "vertical", "16:9": "landscape", "1:1": "square"}.get(aspect_ratio, "vertical")
    if product == "biryani":
        return (
            f"Create a {duration}-second {aspect} commercial food video. Show one consistent serving of "
            "freshly cooked aromatic biryani at a clean street-food stall. Shot one: a food server rhythmically "
            "taps a large rice ladle on a steaming metal cooking vessel and opens the lid. Shot two: realistic hands "
            "fold the rice from the bottom, lift a generous portion, place it on a plate or banana leaf, and add one "
            "boiled egg. Shot three: add onion yogurt sauce and a savoury side, hand the plate to a customer, then "
            "finish on an appetising close-up with visible steam and separate rice grains. Natural food physics, "
            "accurate hands, hygienic service, warm documentary lighting, no text, no logos, no unrelated food."
        )
    subtype = _provider_safe_product_prompt(str(content.get("product_subtype") or content.get("topic") or "product"))
    return (
        f"Create a {duration}-second {aspect} commercial for one consistent {subtype}. Show a clear product reveal, "
        "one realistic use by a customer, and a polished final hero view. Natural movement, accurate hands, premium "
        "commercial lighting, no text, no logos, no unrelated objects."
    )


def _creatorthon_product_prompt(content: dict[str, Any], duration: int, aspect_ratio: str) -> str:
    """Compile a literal product commercial without editorial-topic reinterpretation."""
    clean = lambda value, limit=120: " ".join(str(value or "").split()[:limit])
    product = clean(content.get("product") or content.get("topic"), 24)
    subtype = clean(content.get("product_subtype") or product, 24)
    industry = clean(content.get("category"), 12)
    style = clean(content.get("creative_style"), 20) or "Product showcase"
    style_direction = clean(content.get("style_direction"), 50)
    attributes = content.get("product_attributes") if isinstance(content.get("product_attributes"), dict) else {}
    attribute_locks = [f"{clean(key, 8)}: {clean(value, 20)}" for key, value in attributes.items() if clean(value, 20)]
    custom_requirement = clean(attributes.get("custom"), 60)
    goal = clean(content.get("campaign_goal"), 12)
    audience = clean(content.get("target_audience"), 16)
    mood = clean(content.get("visual_mood"), 12)
    platform = clean(content.get("target_platform"), 12)
    human_interaction = clean(content.get("human_interaction"), 80)
    spec = content.get("product_visual_spec") if isinstance(content.get("product_visual_spec"), dict) else {}
    subject = clean(spec.get("subject"), 60) or f"the real {subtype} product"
    environment = clean(spec.get("environment"), 60) or "a realistic professional setting appropriate to the product"
    category_continuity = {
        "Food": "same dish, kitchen or counter, cookware, chef and serving vessel from preparation through service",
        "Real Estate": "same property, architecture, floor plan, finishes, agent and viewers from exterior through interior",
        "Dental": "same adult patient, clinician, clinic, teeth and treatment stage throughout",
        "Fashion": "same garment, fabric, colour, construction, adult model, styling and studio throughout",
        "Beauty": "same product, packaging, adult model or client, professional and treatment setting throughout",
        "Automotive": "same vehicle, body, paint, wheels, cabin, driver and physical location throughout",
        "Technology": "same device or software task, user, workspace and interaction flow throughout",
        "Travel": "same destination, property, landscape, travellers, wardrobe, weather and time of day throughout",
    }.get(industry, "same product, customer, environment, lighting and time of day throughout")
    sequence_mode = clean(spec.get("sequence_mode"), 40) or "single continuous product story in one coherent setting"
    beats = [clean(value, 60) for value in spec.get("beats", []) if clean(value, 60)][:3]
    if not beats:
        beats = [f"establish {subject}", f"show one believable use of {subject}", f"finish on a clean hero view of {subject}"]
    avoid = [clean(value, 20) for value in spec.get("avoid", []) if clean(value, 20)]
    campaign = [
        clean(content.get("brand"), 12), clean(content.get("offer"), 16),
        clean(content.get("location"), 12), clean(content.get("cta"), 16),
    ]
    aspect = {"9:16": "vertical 9:16", "16:9": "landscape 16:9", "1:1": "square 1:1"}.get(aspect_ratio, "vertical 9:16")
    prompt = " ".join([
        f"Create one coherent {duration}-second {aspect} {style.lower()} commercial for {subtype}, a {industry} product.",
        f"PRODUCT IDENTITY LOCK: {subject}. This exact product is the sole hero subject in every shot and must never be reinterpreted as another object.",
        ("MANDATORY PRODUCT ATTRIBUTES: " + "; ".join(attribute_locks) + ". Preserve every attribute without substitution in all shots.") if attribute_locks else "",
        (f"MANDATORY CUSTOM REQUIREMENT: {custom_requirement}. This is part of the product identity, not optional styling or background decoration. It must be visibly present in the opening, demonstration and final hero shot.") if custom_requirement else "",
        f"SETTING: {environment}.",
        f"ADVERTISING ART DIRECTION: {style_direction or style}. Make every frame feel intentionally art-directed for a premium paid social campaign, never like generic stock footage.",
        f"CAMPAIGN: objective {goal or 'conversion'}; target audience {audience or 'relevant customers'}; visual mood {mood or 'premium'}; delivery {platform or aspect}.",
        f"HUMAN PRESENTATION: {human_interaction}" if human_interaction else "Show believable, natural interaction by the intended adult customer whenever people improve the product demonstration.",
        "For fashion, swimwear, lingerie, innerwear, sheer or transparent garments: use clearly adult professional models only, preserve the garment's real material and transparency, and use selected opaque undergarments, a coverage garment, bodysuit, layering, strategic commercial coverage, or mannequin presentation. Never expose nipples or genitals; never use erotic posing, fetish framing, voyeuristic angles, or an ambiguous-age model.",
        "CONVERSION ARC: use the first 2 seconds for an unmistakable scroll-stopping product hook; demonstrate one concrete customer benefit through visible action; build aspiration or appetite; finish on the exact same product in a polished hero composition with clean negative space for a separately added call to action.",
        (f"SEQUENCE RULE: {sequence_mode}. Treat the clip as one continuous event with natural temporal and spatial continuity." if sequence_mode else ""),
        f"CATEGORY CONTINUITY LOCK: preserve the {category_continuity}. Do not jump to a second location, replace the subject, change a person's identity or wardrobe, or reset the time of day.",
        "SHOT PROGRESSION: " + " Then, ".join(beats) + ".",
        (f"FINAL CUSTOM-REQUIREMENT CHECK: every relevant shot must visibly prove '{custom_requirement}'. If it describes colours or layers, show them on the product itself, keep them distinct and never replace them with lighting, scenery, packaging or a muddy blended colour.") if custom_requirement else "",
        f"Maintain identical product shape, scale, material, color and function throughout. Use realistic physics, accurate human interaction, deliberate foreground-background separation, rich but natural color contrast, tactile macro detail, motivated premium camera movement, and commercially polished lighting.",
        ("Campaign context for narration only, not generated typography: " + "; ".join(value for value in campaign if value) + ".") if any(campaign) else "",
        ("ABSOLUTELY DO NOT SHOW: " + ", ".join(avoid) + ".") if avoid else "",
        "No unrelated products, metaphorical substitutions, electronics unless explicitly requested, readable text, labels, captions, UI, fake logos, morphing, duplicated objects, deformed hands, or anatomical distortion.",
    ]).strip()[:3500]
    return _provider_safe_product_prompt(prompt)


def _creatorthon_product_narration(content: dict[str, Any], duration: int) -> str:
    clean = lambda value, limit=30: " ".join(str(value or "").split()[:limit])
    product = clean(content.get("product_subtype") or content.get("product") or content.get("topic"), 10)
    brand, offer, cta = clean(content.get("brand"), 8), clean(content.get("offer"), 10), clean(content.get("cta"), 8)
    industry = clean(content.get("category"), 8).casefold()
    language = clean(content.get("narration_language") or "English", 4).casefold()
    localized = {
        "tamil": {
            "food": f"உண்மையான {product} சுவையை அனுபவியுங்கள். {offer}. {cta or 'இன்றே ஆர்டர் செய்யுங்கள்.'}",
            "real estate": f"உங்கள் கனவு வாழ்க்கைக்கான {product}. {offer}. {cta or 'இன்றே விசாரிக்கவும்.'}",
            "dental": f"{product} மூலம் நம்பிக்கையான புன்னகையைப் பெறுங்கள். உங்களுக்கான நிபுணத்துவ பராமரிப்பு. {cta or 'ஆலோசனைக்கு முன்பதிவு செய்யுங்கள்.'}",
            "travel": f"மறக்க முடியாத உங்கள் அடுத்த பயணம் {product} உடன் தொடங்குகிறது. {offer}. {cta or 'இன்றே உங்கள் பயணத்தை முன்பதிவு செய்யுங்கள்.'}",
            "default": f"உங்கள் ஒவ்வொரு தருணத்தையும் சிறப்பாக்கும் {product}. {offer}. {cta or 'இன்றே அறிந்துகொள்ளுங்கள்.'}",
            "presents": "வழங்குகிறது",
        },
        "hindi": {"default": f"हर पल को बेहतर बनाने वाला {product}. {offer}. {cta or 'आज ही जानें.'}", "presents": "प्रस्तुत करता है"},
        "malayalam": {"default": f"ഓരോ നിമിഷവും മികച്ചതാക്കുന്ന {product}. {offer}. {cta or 'ഇന്നുതന്നെ അറിയൂ.'}", "presents": "അവതരിപ്പിക്കുന്നു"},
        "telugu": {"default": f"ప్రతి క్షణాన్ని మెరుగుపరిచే {product}. {offer}. {cta or 'ఈరోజే తెలుసుకోండి.'}", "presents": "సమర్పిస్తోంది"},
        "kannada": {"default": f"ಪ್ರತಿ ಕ್ಷಣವನ್ನೂ ಉತ್ತಮಗೊಳಿಸುವ {product}. {offer}. {cta or 'ಇಂದೇ ತಿಳಿಯಿರಿ.'}", "presents": "ಪ್ರಸ್ತುತಪಡಿಸುತ್ತದೆ"},
        "bengali": {"default": f"প্রতিটি মুহূর্তকে আরও সুন্দর করে {product}. {offer}. {cta or 'আজই জানুন.'}", "presents": "উপস্থাপন করছে"},
        "arabic": {"default": f"اكتشف {product} المصمم ليجعل كل لحظة أفضل. {offer}. {cta or 'اكتشفه اليوم.'}", "presents": "تقدم"},
    }
    if language in localized:
        phrases = localized[language]
        copy = phrases.get(industry, phrases["default"])
        if brand:
            copy = f"{brand} {phrases['presents']}. {copy}"
    elif industry == "food":
        copy = f"Crave the authentic taste of {product}. {offer}. {cta or 'Order yours today.'}"
    elif industry == "real estate":
        copy = f"Step into {product}, designed for the way you want to live. {offer}. {cta or 'Enquire today.'}"
    elif industry == "dental":
        copy = f"Discover a more confident smile with {product}. Professional care, planned for you. {cta or 'Book a consultation.'}"
    elif industry == "travel":
        copy = f"Your next unforgettable experience starts with {product}. {offer}. {cta or 'Book your journey.'}"
    else:
        copy = f"Meet {product}, created to make every moment better. {offer}. {cta or 'Discover it today.'}"
    if brand and language not in localized:
        copy = f"{brand} presents. {copy}"
    words = " ".join(copy.replace(" .", ".").split()).split()
    text = " ".join(words[:max(8, round(duration * 2.0))]).strip(" ,;:-")
    return text + ("" if not text or text[-1] in ".!?" else ".")


def _creatorthon_prediction_prompt(content: dict[str, Any], duration: int, aspect_ratio: str) -> str:
    """Build a factual, source-aware prediction promo with a coherent visual story."""
    clean = lambda value, limit=80: " ".join(str(value or "").split()[:limit])
    title = clean(content.get("topic") or content.get("title") or "the selected event", 28)
    subject = clean(content.get("subject") or content.get("player_team") or "the featured participant", 20)
    probability = clean(content.get("probability"), 5)
    previous = clean(content.get("previous_probability"), 5)
    status = clean(content.get("status") or "Reported concern", 24)
    evidence = clean(content.get("evidence") or "No additional verified detail supplied", 55)
    source = clean(content.get("source_name") or content.get("market_source") or "Market update", 12)
    reference = clean(content.get("reference_description"), 80)
    confirmed = bool(content.get("confirmed_status"))
    aspect = {"9:16": "vertical 9:16", "16:9": "landscape 16:9", "1:1": "square 1:1"}.get(aspect_ratio, "vertical 9:16")
    probability_line = f"Current market probability: {probability}%." if probability else "Do not invent a probability."
    movement_line = f"It moved from {previous}% to {probability}%." if previous and probability else "Do not invent market movement."
    claim_rule = "The status is confirmed by the supplied source." if confirmed else "The status is not confirmed; frame it as reported, questionable, or uncertain, never as established fact."
    return _provider_safe_product_prompt(" ".join([
        f"Create a stunning, conversion-focused {duration}-second {aspect} sports and prediction-market promo about: {title}.",
        (f"IDENTITY AND EVENT LOCK: follow the same {subject} and event throughout. Reference guidance: {reference}." if reference else f"EVENT LOCK: follow the same {subject} and event throughout; do not substitute a different person, team, sport, venue, or matchup."),
        f"FACT LOCK: {probability_line} {movement_line} Status: {status}. Evidence supplied: {evidence}. Source: {source}. {claim_rule}",
        "VISUAL STORY: open with premium event atmosphere and anticipation. Then show the featured adult athlete or participant experiencing a believable non-graphic physical setback, receiving sideline attention, or being unable to continue only when supported by the supplied status. Use body language, medical staff interaction, bench absence, equipment being set aside, or a lineup gap instead of explanatory injury text.",
        "Reveal the probability as one bold, legible broadcast-style number with a restrained data graphic. Show what the uncertainty means through a tense team or audience reaction and tactical implication. Finish with a premium event hero composition, probability, source attribution, and clean call-to-action space.",
        "SHOT ARC: 0–3 seconds event hook and identity; 3–7 seconds visible problem or availability uncertainty; 7–11 seconds probability reveal and implication; final seconds branded premium payoff. Use fast coherent rhythm, motivated camera movement, selective slow motion, realistic event lighting, tactile detail, authentic reactions and polished sound-design moments.",
        "Major sports-network promo quality: photorealistic faces, accurate anatomy, consistent uniform and jersey number, plausible movement, cinematic contrast, volumetric atmosphere, crisp subject separation and premium commercial composition.",
        "SAFETY AND TRUTH: adults only. No blood, exposed wounds, graphic impact, medical diagnosis, invented score, quote, award, opponent, source, financial promise, betting instruction, guaranteed outcome, or celebration of injury. Do not state an unconfirmed absence as fact. Probability is market sentiment, not a confirmed outcome or financial advice.",
        "No paragraphs, subtitles, watermarks or fake logos inside footage. Only the supplied probability and short source/status wording may appear as minimal broadcast graphics; leave space for final typography.",
    ]).strip()[:3500])


def _creatorthon_prediction_narration(content: dict[str, Any], duration: int) -> str:
    clean = lambda value, limit=30: " ".join(str(value or "").split()[:limit])
    title = clean(content.get("topic") or content.get("title") or "this event", 18)
    subject = clean(content.get("subject") or content.get("player_team") or "The key participant", 10)
    probability = clean(content.get("probability"), 4)
    status = clean(content.get("status") or "a reported availability concern", 12)
    language = clean(content.get("narration_language") or "English", 3).casefold()
    scripts = {
        "tamil": f"{subject} குறித்து {status}. இப்போது {title} நிகழ்வின் சந்தை வாய்ப்பு {probability or 'புதிய'} சதவீதம். இது சந்தை கருத்து மட்டுமே; உறுதியான முடிவு அல்ல.",
        "hindi": f"{subject} पर {status} की खबर है। {title} की बाज़ार संभावना अब {probability or 'नई'} प्रतिशत है। यह बाज़ार की राय है, पक्का नतीजा नहीं।",
        "malayalam": f"{subject} സംബന്ധിച്ച് {status}. {title} ന്റെ വിപണി സാധ്യത ഇപ്പോൾ {probability or 'പുതിയ'} ശതമാനം. ഇത് വിപണി വിലയിരുത്തൽ മാത്രം; ഉറപ്പായ ഫലം അല്ല.",
    }
    pct = f"{probability} percent" if probability else "the latest market probability"
    return scripts.get(language, f"{subject}: {status}. The market now puts {title} at {pct}. The situation changes the outlook—but probability is market sentiment, not a guaranteed result.")


def apply_selected_alternate_direction(content: dict[str, Any], user_direction: str = "") -> dict[str, Any]:
    """Turn a selected V3 alternate into an authoritative shot without changing story facts."""
    concept = " ".join(str(content.get("selected_alternate_concept") or "").split())[:80]
    direction = " ".join(str(user_direction or content.get("creator_angle") or "").split())[:1000]
    if not concept or not direction:
        return content
    updated = dict(content)
    plan = content.get("visual_story_plan") if isinstance(content.get("visual_story_plan"), dict) else {}
    story = content.get("story_understanding") if isinstance(content.get("story_understanding"), dict) else {}
    camera_by_concept = {
        "hero reveal": "Begin on one article-specific close detail, then use one slow controlled pullback to reveal the complete sourced subject and result.",
        "human impact": "Use one restrained eye-level tracking move that stays with the sourced person through the visible action and reaction.",
        "before and after": "Use one locked composition with a motivated foreground transition from the sourced before state to the sourced after state.",
        "process in motion": "Use one controlled lateral tracking move that follows the sourced process from cause through visible result.",
        "editorial spotlight": "Use one slow editorial push-in that reveals the article-specific subject, evidence, and final consequence in a single coherent scene.",
    }
    camera = camera_by_concept.get(concept.lower(), "Use one controlled camera move that clearly executes the selected concept.")
    must_show = plan.get("must_show") if isinstance(plan.get("must_show"), list) else []
    must_avoid = list(dict.fromkeys(
        (plan.get("must_avoid") if isinstance(plan.get("must_avoid"), list) else [])
        + (story.get("unsupported_visuals") if isinstance(story.get("unsupported_visuals"), list) else [])
    ))
    core = str(plan.get("core_visual_subject") or content.get("core_visual_subject") or content.get("topic") or "the selected story")
    updated["current_story_beat"] = f"{concept}: {direction}"
    updated["alternate_camera_direction"] = camera
    updated["alternate_must_show"] = must_show[:5] or [core]
    updated["alternate_must_avoid"] = must_avoid[:8]
    updated["selected_creative_concept"] = concept
    return updated


def _creatorthon_user_variation(user_id: str, content: dict[str, Any]) -> dict[str, Any]:
    """Create a stable, factual creative lens for one user/topic pair."""
    title = " ".join(str(content.get("topic") or content.get("title") or "Selected topic").split())
    digest = hashlib.sha256(f"{user_id.strip()}|{title.casefold()}".encode("utf-8")).digest()
    concepts = ("Hero reveal", "Human impact", "Before and after", "Process in motion", "Editorial spotlight")
    focuses = (
        "campaign reveal", "human reaction", "behind-the-scenes process", "signature design detail",
        "audience perspective", "business significance", "cultural context", "craft and preparation",
        "real-world impact", "future implication",
    )
    openings = (
        "one article-specific close detail", "the clearest real person or subject", "the visible result before its cause",
        "a grounded environmental context", "one decisive action already beginning",
    )
    endings = (
        "a clean hero view", "a natural human reaction", "the completed process", "the strongest sourced detail",
        "a clear visual consequence",
    )
    concept, focus, opening, ending = (
        concepts[digest[0] % len(concepts)], focuses[digest[1] % len(focuses)],
        openings[digest[2] % len(openings)], endings[digest[3] % len(endings)],
    )
    updated = dict(content)
    updated.update({
        "selected_alternate_concept": concept,
        "creator_angle": (
            f"Use a {focus} angle for {title}. Open with {opening}, develop one factual action supported by the topic, "
            f"and end on {ending}. Keep every person, product, place, and claim grounded in the supplied story."
        ),
        "variation_label": focus.title(),
        "variation_hashtags": [
            "#" + "".join(word.title() for word in focus.replace("-", " ").split()),
            "#" + "".join(word.title() for word in concept.split()),
        ],
        "variation_key": digest[:8].hex(),
    })
    return updated


def _creatorthon_variation_narration(narration: str, content: dict[str, Any]) -> str:
    """Replace the generic opening with a stable angle-specific hook without lengthening the script."""
    original = " ".join(str(narration or "").split())
    focus = str(content.get("variation_label") or "the story").casefold()
    concept = str(content.get("selected_alternate_concept") or "editorial spotlight").casefold()
    hooks = {
        "hero reveal": f"Watch the {focus} take shape.",
        "human impact": f"See the human side of {focus}.",
        "before and after": f"See what changes through {focus}.",
        "process in motion": f"Follow the {focus} in motion.",
        "editorial spotlight": f"Look closer at the {focus}.",
    }
    hook = hooks.get(concept, f"Look closer at the {focus}.")
    if not original:
        return hook
    words, hook_words = original.split(), hook.split()
    return " ".join((hook_words + words[min(len(words), len(hook_words)):])[:len(words)])


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="Viralizer Video Studio")
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


def _is_creatorthon_v3_host(request: Request) -> bool:
    configured = os.getenv("CREATORTHON_V3_HOST", "v3.viralizer.ai").strip().casefold()
    return bool(configured and (request.url.hostname or "").casefold() == configured)


def _creatorthon_frozen_response(request: Request, signed_in: bool = False) -> HTMLResponse:
    destination = "/creatorthon/admin"
    organizer_action = (
        '<a class="button" href="/logout?next=/creatorthon/login">Sign out and use an organizer account</a>'
        if signed_in else
        f'<a class="button" href="/auth/google?next={quote(destination, safe="/")}">Organizer sign in</a>'
    )
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Creatorthon temporarily unavailable</title>
<style>*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at top,#f4edff,#fff 58%);font-family:Inter,system-ui,sans-serif;color:#11101a}}main{{width:min(560px,100%);padding:42px;border:1px solid #dfd2f5;border-radius:24px;background:#ffffffed;box-shadow:0 28px 80px #5e3a8d20;text-align:center}}img{{width:190px;max-width:70%;height:auto}}.tag{{display:inline-block;margin-top:26px;padding:7px 11px;border-radius:999px;background:#f1e7ff;color:#7c2ed4;font-size:11px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}}h1{{margin:15px 0 10px;font-size:clamp(30px,6vw,46px);letter-spacing:-.045em}}p{{margin:0 auto;color:#665e70;line-height:1.65;max-width:440px}}.button{{display:inline-flex;margin-top:25px;padding:13px 18px;border-radius:12px;background:#171221;color:#fff;text-decoration:none;font-weight:850}}</style>
</head><body><main><img src="/static/viralizer-logo-black.png" alt="Viralizer"><div class="tag">Event paused</div><h1>Creatorthon is temporarily unavailable</h1><p>The organizer has frozen participant access. Your profile, projects and videos remain safe. Please contact the organizer for assistance.</p>{organizer_action}</main></body></html>""", status_code=423)


@app.middleware("http")
async def require_password(request: Request, call_next):
    if request.url.path.startswith("/api/prototype/video"):
        configured_origins = os.getenv(
            "PROTOTYPE_ALLOWED_ORIGIN",
            "https://viralizer-onboarding-demo.intuition-in-7630.chatgpt.site",
        )
        allowed_origins = {
            value.strip().rstrip("/")
            for value in configured_origins.split(",")
            if value.strip()
        }
        origin = request.headers.get("origin", "").strip().rstrip("/")
        if not origin or origin not in allowed_origins:
            return JSONResponse({"detail": "Prototype origin is not allowed."}, status_code=403)
        cors_headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-Prototype-Request-Id",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
            "Cache-Control": "no-store",
        }
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=cors_headers)
        response = await call_next(request)
        for key, value in cors_headers.items():
            response.headers[key] = value
        return response
    public_paths = {"/login", "/about", "/privacy", "/terms", "/creatorthon/login", "/creatorthon-v2/login", "/creatorthon-v3/login", "/auth/google", "/auth/google/callback", "/health", "/health/storage", "/health/media", "/health/pixverse", "/health/pixverse-growth"}
    public_login_assets = {
        "/static/viralizer-intro.css",
        "/static/viralizer-intro.js",
        "/static/viralizer-login-intro.mp4",
        "/static/viralizer-original-logo.png",
        "/static/viralizer-logo-black.png",
        "/static/viralizer-logo-white.png",
        "/static/viralizer-v3-favicon.png",
        "/static/viralizer-v3-favicon-v2.png",
        "/static/final/viralizer-logo-mark.svg",
    }
    creatorthon_request = (
        request.url.path.startswith("/creatorthon")
        or request.url.path.startswith("/api/creatorthon")
        or request.url.path.startswith("/auth/youtube")
        or (request.url.path == "/" and _is_creatorthon_v3_host(request))
    )
    if creatorthon_request and event_is_frozen(ROOT):
        google_user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
        if not google_user or not _creatorthon_admin_user(google_user):
            if request.url.path.startswith("/api/"):
                return JSONResponse(
                    {"detail": "Creatorthon is temporarily unavailable. Please contact the organizer.", "frozen": True},
                    status_code=423,
                )
            return _creatorthon_frozen_response(request, signed_in=bool(google_user))
    # The V3 custom domain is the product itself. Every clean browser route must
    # use the Google session (rather than falling through to the legacy password
    # middleware), otherwise refreshing a nested URL sends users to the wrong app.
    v3_clean_roots = {"/", "/profile", "/product", "/prediction-video", "/workspace", "/concept", "/admin"}
    v3_clean_prefixes = ("/topics/", "/markets/", "/create/", "/review/", "/generating/", "/result/", "/project/", "/product/", "/prediction-video/", "/workspace/")
    is_v3_clean_route = request.url.path in v3_clean_roots or request.url.path.startswith(v3_clean_prefixes)
    if _is_creatorthon_v3_host(request) and is_v3_clean_route:
        if request.url.path != "/" and not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
            destination = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse("/creatorthon-v3/login?next=" + quote(destination, safe="/?=&%"), status_code=303)
        return await call_next(request)
    if request.url.path.startswith("/creatorthon") or request.url.path.startswith("/api/creatorthon"):
        google_user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
        if request.url.path not in public_paths and not google_user:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Google sign-in required"}, status_code=401)
            if request.url.path.startswith("/creatorthon-v3"):
                login_path = "/creatorthon-v3/login"
            elif request.url.path.startswith("/creatorthon-v2"):
                login_path = "/creatorthon-v2/login"
            else:
                login_path = "/creatorthon/login?next=" + quote(request.url.path + (f"?{request.url.query}" if request.url.query else ""), safe="/?=&%")
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
</style></head><body><main class="card"><img class="mark" src="/static/viralizer-logo-white.png" alt="Viralizer"><h1>Viralizer Video Studio</h1><p>Sign in with Google or use the workspace password.</p>{message}
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
async def logout(next: str = "/login"):
    destination = next if next.startswith("/") and not next.startswith("//") else "/login"
    response = RedirectResponse(destination, status_code=303)
    response.delete_cookie(AUTH_COOKIE)
    response.delete_cookie(GOOGLE_STATE_COOKIE)
    return response


@app.get("/auth/youtube/connect")
async def connect_youtube_account(request: Request):
    user = creatorthon_user(request)
    if not youtube_oauth_configured():
        raise HTTPException(503, "YouTube OAuth is not configured in Render.")
    state = google_signed_payload({"sub": str(user.get("sub", "")), "iat": int(time.time())})
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    callback = youtube_redirect_uri(scheme, host)
    response = RedirectResponse(
        youtube_authorization_url(callback, state, str(user.get("email") or "")),
        status_code=302,
    )
    response.set_cookie(YOUTUBE_STATE_COOKIE, state, max_age=600, httponly=True, secure=scheme == "https", samesite="lax")
    return response


@app.get("/auth/youtube/callback")
async def youtube_oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    user = creatorthon_user(request)
    expected_state = request.cookies.get(YOUTUBE_STATE_COOKIE, "")
    state_payload = read_google_state(state, max_age=600) if state and hmac.compare_digest(state, expected_state) else None
    if error or not code:
        return RedirectResponse("/workspace?youtube=denied", status_code=303)
    if not state_payload or str(state_payload.get("sub") or "") != str(user.get("sub") or ""):
        return RedirectResponse("/workspace?youtube=state", status_code=303)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    try:
        connection = await exchange_youtube_connection(
            code, youtube_redirect_uri(scheme, host), str(user.get("email") or "")
        )
        save_youtube_connection(ROOT, str(user.get("sub", "")), connection)
    except YouTubeOAuthError:
        return RedirectResponse("/workspace?youtube=failed", status_code=303)
    response = RedirectResponse("/workspace?youtube=connected", status_code=303)
    response.delete_cookie(YOUTUBE_STATE_COOKIE)
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
    if _is_creatorthon_v3_host(request):
        user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
        if not user:
            return RedirectResponse("/creatorthon-v3/login?next=/admin", status_code=303)
        if not _creatorthon_admin_user(user):
            raise HTTPException(403, "Creatorthon organizer access required.")
        return FileResponse(
            ROOT / "static" / "creatorthon-admin.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )
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
    global CREATORTHON_PREFETCH_TASK, PREDICTION_MARKET_PREFETCH_TASK, CHANNEL_AUTOMATION_TASK
    if os.getenv("CREATORTHON_PREFETCH_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}:
        CREATORTHON_PREFETCH_TASK = asyncio.create_task(_creatorthon_prefetch_scheduler())
    PREDICTION_MARKET_PREFETCH_TASK = asyncio.create_task(_prefetch_prediction_market_topics())
    if os.getenv("CHANNEL_AUTOMATION_SCHEDULER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}:
        CHANNEL_AUTOMATION_TASK = asyncio.create_task(CHANNEL_AUTOMATION.scheduler())


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "viralizer-video-studio",
        "release": os.getenv("RENDER_GIT_COMMIT", os.getenv("APP_VERSION", "local")),
    }


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
    allow_standard_fallback: bool = False
    aspect_ratio: str = "9:16"
    target_platform: str = ""
    narration: str = ""
    avatar_id: str = ""
    voice_id: str = ""
    background: str = "#0B1020"
    generation_type: str = "text_to_video"
    debug_prompt: bool = False
    creator_concept: bool = False
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


class VideoReferenceAnalyzeRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    instruction: str = Field(default="Create an original premium short inspired by the pacing and storytelling structure.", max_length=1200)
    language: str = Field(default="English", max_length=40)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9)$")


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


class CreatorthonObjectiveRequest(BaseModel):
    topic: dict[str, Any]
    objective: str = Field(min_length=2, max_length=300)


class CreatorthonWorkflowRequest(BaseModel):
    step: str = Field(pattern=r"^(profile|interests|topics|create)$")
    topics: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    selected_topic: dict[str, Any] = Field(default_factory=dict)


class CreatorthonAdminEmailRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class CreatorthonAdminCapacityRequest(BaseModel):
    capacity: int = Field(ge=1, le=10000)


class CreatorthonAdminFreezeRequest(BaseModel):
    frozen: bool


class CreatorthonAdminAllowanceRequest(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=1000)
    total_allowance: int = Field(ge=1, le=1000)


class ChannelAutomationSettingsRequest(BaseModel):
    enabled: bool
    categories: list[str] = Field(default_factory=list, max_length=40)


class ChannelAutomationRunRequest(BaseModel):
    categories: list[str] = Field(default_factory=list, max_length=40)


class ChannelAutomationDraftRequest(BaseModel):
    status: str = Field(pattern=r"^(approved|rejected|awaiting_approval)$")


class CreatorthonInsightsRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)


class CreatorthonPredictionCoverageRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)
    context: str = Field(default="", max_length=500)


class CreatorthonInsightQueueRequest(BaseModel):
    topic: dict[str, Any]


class CreatorthonProjectRequest(BaseModel):
    topic: dict[str, Any]
    prompt: dict[str, Any] | str = Field(default_factory=dict)
    narration: dict[str, Any] | str = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)
    article_intelligence: dict[str, Any] = Field(default_factory=dict)
    provider: str = Field(default="", max_length=40)
    aspect_ratio: str = Field(default="", max_length=20)
    quality: str = Field(default="", max_length=20)


class CreatorthonProjectUpdateRequest(BaseModel):
    provider: str = Field(default="", max_length=40)
    job_id: str = Field(default="", max_length=160)
    video_url: str = Field(default="", max_length=1000)
    status: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=500)
    thumbnail_url: str = Field(default="", max_length=2000)
    aspect_ratio: str = Field(default="", max_length=20)
    quality: str = Field(default="", max_length=20)
    topic: dict[str, Any] | None = None
    prompt: dict[str, Any] | str | None = None
    narration: dict[str, Any] | str | None = None
    configuration: dict[str, Any] | None = None
    article_intelligence: dict[str, Any] | None = None
    production: dict[str, Any] | None = None
    qc: dict[str, Any] | None = None


class CreatorthonReportRequest(BaseModel):
    id: str = Field(default="", max_length=64)
    project_id: str = Field(default="", max_length=64)
    title: str = Field(min_length=1, max_length=500)
    report_type: str = Field(default="topic-research", max_length=80)
    source_url: str = Field(default="", max_length=2000)
    content: dict[str, Any]


class CreatorthonFinishRequest(BaseModel):
    video_url: str = Field(default="", max_length=2000)
    narration: str = Field(default="", max_length=4096)
    voice: str = Field(default="coral", max_length=40)
    official_logo_data: str = Field(default="", max_length=14_000_000)
    project_id: str = Field(default="", max_length=64)
    provider: str = Field(default="", max_length=40)
    provider_job_id: str = Field(default="", max_length=160)


class CreatorthonConceptGenerateRequest(GenerateRequest):
    """Start a creator video and immediately hand its provider job to durable finishing."""
    project_id: str = Field(min_length=8, max_length=64)
    official_logo_data: str = Field(default="", max_length=14_000_000)
    custom_prompt_confirmed: bool = False
    speech_script_reviewed: bool = False
    hashtags_reviewed: bool = False
    topic_mismatch_acknowledged: bool = False


class CreatorthonPrepareRequest(GenerateRequest):
    project_id: str = Field(default="", max_length=64)
    prompt_mode: str = Field(default="viralizer", pattern=r"^(viralizer|alternate|custom)$")


class CreatorthonHashtagRequest(BaseModel):
    topic: dict[str, Any]


class CreatorthonPublishRequest(BaseModel):
    project_id: str = Field(min_length=8, max_length=64)
    video_url: str = Field(min_length=4, max_length=2000)
    caption: str = Field(default="", max_length=3000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    platforms: list[str] = Field(default_factory=list, max_length=4)
    viralizer_youtube_consent: bool = False


class PrototypeStoryboardScene(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    visual: str = Field(min_length=3, max_length=1200)
    camera: str = Field(default="Smooth cinematic movement", max_length=300)
    on_screen_text: str = Field(default="", max_length=300)
    duration_seconds: int = Field(default=3, ge=1, le=8)


class PrototypeVideoStartRequest(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    category: str = Field(default="General", max_length=120)
    creative_style: str = Field(default="Premium cinematic", max_length=160)
    source_description: str = Field(default="", max_length=1200)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1)$")
    narration: str = Field(default="", max_length=3000)
    custom_prompt: str = Field(default="", max_length=6000)
    scenes: list[PrototypeStoryboardScene] = Field(min_length=3, max_length=8)


class PrototypeVideoRevisionRequest(BaseModel):
    original_video_url: str = Field(min_length=20, max_length=4000)
    title: str = Field(min_length=2, max_length=240)
    scene_index: int = Field(ge=1, le=8)
    scene_start_seconds: float = Field(ge=0, le=120)
    scene_duration_seconds: float = Field(gt=0, le=8)
    revision_prompt: str = Field(min_length=8, max_length=3000)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1)$")


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
async def index(request: Request):
    if _is_creatorthon_v3_host(request):
        if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
            return await creatorthon_v3_login(request, next="/")
        return FileResponse(
            ROOT / "static" / "creatorthon-v3.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )
    return FileResponse(
        ROOT / "static" / "pixel_ui.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/creatorthon/login", response_class=HTMLResponse)
async def creatorthon_login(request: Request, next: str = "/creatorthon"):
    destination = next if next.startswith("/") and not next.startswith("//") else "/creatorthon"
    if read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse(destination, status_code=303)
    google_ready = google_configured()
    action = ('<a class="google" href="/auth/google?next='+quote(destination, safe='/')+'"><b>G</b> Continue with Google</a>') if google_ready else '<p class="warning">Google sign-in is not configured yet. Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_SESSION_SECRET to this service.</p>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Viralizer Creatorthon</title><link rel="preload" href="/static/viralizer-login-intro.mp4?v=1" as="video" type="video/mp4"><link rel="preload" href="/static/viralizer-logo-white.png" as="image"><link rel="stylesheet" href="/static/viralizer-intro.css?v=7"><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 18% 12%,#32135f,#080914 46%);color:#fff;font-family:Inter,system-ui,sans-serif}}main.card{{width:min(460px,calc(100% - 32px));padding:38px;border:1px solid #4b326e;border-radius:22px;background:#111324ee;box-shadow:0 30px 90px #0009}}.mark{{display:block;width:230px;max-width:78%;height:auto;object-fit:contain}}h1{{font-size:32px;letter-spacing:-.04em;margin:22px 0 10px}}p{{color:#adb4cf;line-height:1.6}}.google{{margin-top:25px;min-height:52px;border-radius:12px;background:#fff;color:#171824;text-decoration:none;font-weight:850;display:flex;align-items:center;justify-content:center;gap:11px}}.google b{{color:#4285f4;font-size:20px}}.warning{{padding:13px;border:1px solid #774755;border-radius:11px;background:#321722;color:#ffbeca;font-size:13px}}</style></head><body class="intro-active"><main class="card"><img class="mark" src="/static/viralizer-logo-white.png" alt="Viralizer"><h1>Viralizer Creatorthon</h1><p>Choose your interests, discover relevant worldwide topics, and turn one into a finished video through a simple guided journey.</p>{action}</main><script src="/static/viralizer-intro.js?v=7" defer></script></body></html>""")


@app.get("/creatorthon")
async def creatorthon(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon/login", status_code=303)
    creatorthon_user(request)
    return FileResponse(ROOT / "static" / "creatorthon.html", headers={"Cache-Control": "no-store"})


@app.get("/creatorthon/login", response_class=HTMLResponse)
async def creatorthon_v1_login(request: Request):
    if read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon", status_code=303)
    google_ready = google_configured()
    action = '<a class="google" href="/auth/google?next=/creatorthon"><b>G</b><span>Continue with Google</span></a>' if google_ready else '<p class="warning">Google sign-in is not configured yet.</p>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Creatorthon · Viralizer</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;min-height:100%;background:radial-gradient(circle at top,#29154b,#090611 65%);color:#fff;font-family:Inter,system-ui,sans-serif}}body{{display:grid;place-items:center;padding:24px}}main{{width:min(520px,100%);padding:46px;border:1px solid #563483;border-radius:28px;background:#12101ccc;box-shadow:0 30px 90px #0008}}img{{width:188px;height:auto}}.tag{{display:inline-block;margin-top:42px;padding:8px 12px;border-radius:99px;background:#31194e;color:#d8b5ff;font-size:12px;font-weight:850}}h1{{font-size:clamp(42px,8vw,64px);line-height:.98;letter-spacing:-.06em;margin:18px 0}}p{{color:#c1b6d2;line-height:1.6}}.google{{display:flex;align-items:center;justify-content:center;gap:12px;min-height:64px;margin-top:32px;border-radius:18px;background:#fff;color:#16111c;text-decoration:none;font-weight:850}}.google b{{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#fff;color:#4285f4;font-size:20px}}.warning{{padding:14px;border-radius:14px;background:#fff1f2;color:#a82035}}</style></head><body><main><img src="/static/viralizer-logo-white.png" alt="Viralizer"><span class="tag">CREATORTHON</span><h1>Start Viral Content Creation</h1><p>Discover timely topics, direct your video, add speech and branding, then publish—all in one guided journey.</p>{action}</main></body></html>""")

@app.get("/creatorthon/concept")
async def creatorthon_concept(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon/login?next=/creatorthon/concept", status_code=303)
    creatorthon_user(request)
    return FileResponse(ROOT / "static" / "creatorthon-concept.html", headers={"Cache-Control": "no-store"})


@app.get("/creatorthon/product")
async def creatorthon_product(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon/login?next=/creatorthon/product", status_code=303)
    creatorthon_user(request)
    return FileResponse(ROOT / "static" / "creatorthon-product.html", headers={"Cache-Control": "no-store"})

@app.get("/creatorthon-v2/login", response_class=HTMLResponse)
async def creatorthon_v2_login(request: Request):
    if read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon-v2", status_code=303)
    google_ready = google_configured()
    action = '<a class="google" href="/auth/google?next=/creatorthon-v2"><b>G</b><span>Continue with Google</span></a>' if google_ready else '<p class="warning">Google sign-in is not configured yet. Add the Google credentials to this service.</p>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Viralizer Creatorthon</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;min-height:100%;background:#fff;color:#0b0b0d;font-family:Inter,Arial,sans-serif}}body{{display:grid;place-items:center;padding:28px}}main{{width:min(520px,100%)}}.brand{{display:flex;justify-content:center;margin-bottom:64px}}.brand img{{width:210px;height:auto}}.progress{{height:5px;border-radius:99px;background:#ececf0;overflow:hidden;margin-bottom:76px}}.progress:before{{content:"";display:block;width:24%;height:100%;border-radius:inherit;background:#8b2cff}}h1{{font-size:clamp(38px,8vw,58px);line-height:1.02;letter-spacing:-.055em;margin:0 0 18px}}p{{font-size:17px;line-height:1.55;color:#67666d;margin:0}}.google{{display:flex;align-items:center;justify-content:center;gap:12px;min-height:64px;margin-top:38px;border-radius:999px;background:#0b0b0d;color:#fff;text-decoration:none;font-size:17px;font-weight:800}}.google b{{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#fff;color:#4285f4;font-size:19px}}.note{{font-size:12px;color:#9b9aa1;text-align:center;margin-top:18px}}.warning{{margin-top:28px;padding:16px;border-radius:14px;background:#fff1f2;color:#a82035;font-size:14px}}</style></head><body><main><div class="brand"><img src="/static/viralizer-logo-black.png" alt="Viralizer"></div><div class="progress"></div><h1>Create content people stop for.</h1><p>Discover a timely idea, direct the video, add your voice and branding, then publish—all in one guided journey.</p>{action}<p class="note">Secure Google sign-in · Your existing Viralizer account is used</p></main></body></html>""")


@app.get("/creatorthon-v2")
async def creatorthon_v2(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon-v2/login", status_code=303)
    return FileResponse(
        ROOT / "static" / "creatorthon-v2.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/creatorthon-v3/login", response_class=HTMLResponse)
async def creatorthon_v3_login(request: Request, next: str = "/creatorthon-v3"):
    destination = next if next.startswith("/") and not next.startswith("//") else "/creatorthon-v3"
    if read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse(destination, status_code=303)
    google_ready = google_configured()
    action = f'<a class="google" href="/auth/google?next={quote(destination, safe="/")}"><b>G</b><span>Login or sign up with Google</span></a>' if google_ready else '<p class="warning">Google sign-in is not configured yet.</p>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" type="image/png" href="/static/viralizer-v3-favicon-v2.png?v=2"><link rel="apple-touch-icon" href="/static/viralizer-v3-favicon-v2.png?v=2"><title>Creatorthon V3 · Viralizer</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;min-height:100%;background:#f5f5f7;color:#121216;font-family:Inter,system-ui,sans-serif}}body{{display:grid;place-items:center;padding:24px}}main{{width:min(520px,100%);padding:46px;border:1px solid #e1e1e6;border-radius:30px;background:#fff;box-shadow:0 30px 90px #1111}}img{{width:188px;height:auto}}.tag{{display:inline-block;margin-top:45px;padding:8px 12px;border-radius:99px;background:#f0e7ff;color:#7425d7;font-size:12px;font-weight:850}}h1{{font-size:clamp(42px,8vw,64px);line-height:.98;letter-spacing:-.06em;margin:18px 0}}p{{color:#6d6c73;line-height:1.6}}.google{{display:flex;align-items:center;justify-content:center;gap:12px;min-height:64px;margin-top:32px;border-radius:18px;background:#111;color:#fff;text-decoration:none;font-weight:850}}.google b{{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#fff;color:#4285f4;font-size:20px}}.warning{{padding:14px;border-radius:14px;background:#fff1f2;color:#a82035}}</style></head><body><main><img src="/static/viralizer-logo-black.png" alt="Viralizer"><span class="tag">CREATORTHON V3</span><h1>Start Viral Content Creation</h1><p>Choose what matters to you, discover timely topics, and create with the right video engine.</p>{action}</main></body></html>""")


@app.get("/creatorthon-v3")
async def creatorthon_v3(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon-v3/login", status_code=303)
    return FileResponse(
        ROOT / "static" / "creatorthon-v3.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


def _v3_app_response() -> FileResponse:
    return FileResponse(
        ROOT / "static" / "creatorthon-v3.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/profile")
@app.get("/topics/{category_slug:path}")
@app.get("/markets/{source}")
@app.get("/create/{topic_slug:path}")
@app.get("/review/{project_id}")
@app.get("/generating/{project_id}")
@app.get("/result/{project_id}")
@app.get("/project/{project_id}")
async def creatorthon_v3_clean_route(request: Request, category_slug: str = "", source: str = "", topic_slug: str = "", project_id: str = ""):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        destination = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse("/creatorthon-v3/login?next=" + quote(destination, safe="/?=&%"), status_code=303)
    return _v3_app_response()


@app.get("/product")
@app.get("/product/{step:path}")
async def creatorthon_product_clean(request: Request, step: str = ""):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        destination = request.url.path
        return RedirectResponse("/creatorthon-v3/login?next=" + quote(destination, safe="/"), status_code=303)
    creatorthon_user(request)
    return FileResponse(ROOT / "static" / "creatorthon-product.html", headers={"Cache-Control": "no-store"})


@app.get("/prediction-video")
@app.get("/prediction-video/{step:path}")
async def creatorthon_prediction_video(request: Request, step: str = ""):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        destination = request.url.path
        return RedirectResponse("/creatorthon-v3/login?next=" + quote(destination, safe="/"), status_code=303)
    creatorthon_user(request)
    return FileResponse(ROOT / "static" / "creatorthon-prediction-video.html", headers={"Cache-Control": "no-store"})


@app.get("/concept")
async def creatorthon_concept_clean(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon-v3/login?next=/concept", status_code=303)
    creatorthon_user(request)
    return FileResponse(ROOT / "static" / "creatorthon-concept.html", headers={"Cache-Control": "no-store"})


@app.get("/workspace")
@app.get("/workspace/{view}")
async def creatorthon_workspace_clean(request: Request, view: str = ""):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        destination = request.url.path
        return RedirectResponse("/creatorthon-v3/login?next=" + quote(destination, safe="/"), status_code=303)
    creatorthon_user(request)
    return FileResponse(
        ROOT / "static" / "creatorthon-workspace.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/creatorthon/workspace")
async def creatorthon_workspace_page(request: Request):
    if not read_google_session(request.cookies.get(AUTH_COOKIE, "")):
        return RedirectResponse("/creatorthon/login", status_code=303)
    creatorthon_user(request)
    return FileResponse(
        ROOT / "static" / "creatorthon-workspace.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/creatorthon/admin")
async def creatorthon_admin_page(request: Request):
    user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
    if not user:
        return RedirectResponse("/creatorthon/login?next=/creatorthon/admin", status_code=303)
    if not _creatorthon_admin_user(user):
        raise HTTPException(403, "Creatorthon organizer access required.")
    return FileResponse(
        ROOT / "static" / "creatorthon-admin.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/admin/channel-engine")
async def channel_engine_admin_page(request: Request):
    """Private, organizer-only home for autonomous channel research."""
    user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
    if not user:
        return RedirectResponse("/creatorthon/login?next=/admin/channel-engine", status_code=303)
    if not _creatorthon_admin_user(user):
        raise HTTPException(403, "Viralizer organizer access required.")
    return FileResponse(
        ROOT / "static" / "channel-engine-admin.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/creatorthon/admin/channel-engine")
async def legacy_channel_engine_admin_page(request: Request):
    return RedirectResponse("/admin/channel-engine", status_code=308)


@app.get("/health/storage")
async def storage_health():
    """Secret-free readiness check for the persistent Creatorthon database."""
    from creatorthon_store import database_health

    result = database_health(ROOT)
    return JSONResponse(result, status_code=200 if result["ready"] else 503)


@app.get("/health/media")
async def media_pipeline_health():
    """Secret-free readiness for the persistent media worker and R2."""
    from creatorthon_store import database_health
    from durable_media_pipeline import worker_health
    from object_store import health as object_store_health

    database = database_health(ROOT)
    try:
        worker = await asyncio.to_thread(worker_health, ROOT)
    except Exception:
        worker = {"ready": False, "state": "unavailable", "age_seconds": None}
    storage = await object_store_health()
    result = {"ready": bool(database["ready"] and worker["ready"] and storage["ready"]), "database": database, "worker": worker, "r2": storage}
    return JSONResponse(result, status_code=200 if result["ready"] else 503)


CREATORTHON_UNLIMITED_EMAILS = frozenset({
    "ahamed.don@gmail.com",
    "yusufiid@gmail.com",
    "ansariarif1@gmail.com",
})
CREATORTHON_ADMIN_EMAILS = frozenset({
    "ahamed.don@gmail.com",
    "ansariarif1@gmail.com",
})


def _unlimited_creatorthon_user(user: dict[str, Any]) -> bool:
    email = str(user.get("email") or "").strip().lower()
    configured = {
        value.strip().lower()
        for value in os.getenv("CREATORTHON_UNLIMITED_EMAILS", "").split(",")
        if value.strip()
    }
    return email in CREATORTHON_UNLIMITED_EMAILS or email in configured


def _creatorthon_admin_user(user: dict[str, Any]) -> bool:
    return str(user.get("email") or "").strip().lower() in CREATORTHON_ADMIN_EMAILS


def creatorthon_admin_user(request: Request) -> dict[str, Any]:
    user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
    if not user:
        raise HTTPException(401, "Google sign-in required.")
    if not _creatorthon_admin_user(user):
        raise HTTPException(403, "Creatorthon organizer access required.")
    return user


def creatorthon_user(request: Request) -> dict[str, Any]:
    user = read_google_session(request.cookies.get(AUTH_COOKIE, ""))
    if not user:
        raise HTTPException(401, "Google sign-in required.")
    if _unlimited_creatorthon_user(user):
        return user
    try:
        claim_event_seat(ROOT, str(user.get("sub", "")), int(os.getenv("CREATORTHON_EVENT_USER_LIMIT", "50")), str(user.get("email") or ""))
    except RuntimeError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _english_topic(item: dict[str, Any]) -> bool:
    language = str(item.get("language") or item.get("lang") or "").strip().lower()
    if language and language not in {"en", "en-us", "en-gb", "english"}:
        return False
    text = " ".join(str(item.get(key) or "") for key in ("topic", "title", "summary", "description"))
    return not bool(re.search(r"[\u0400-\u052f\u0600-\u06ff\u0750-\u077f\u0900-\u0dff\u3040-\u30ff\u3400-\u9fff]", text))


def _report_values(value: Any, found: dict[str, Any] | None = None) -> dict[str, Any]:
    if found is None:
        found = {}
    if isinstance(value, dict):
        label = str(value.get("key") or value.get("label") or value.get("title") or "").strip().casefold()
        data = value.get("data")
        if label and data not in (None, "", [], {}):
            found[label] = data
        for key, child in value.items():
            normalized = str(key).replace("_", " ").strip().casefold()
            if child not in (None, "", [], {}) and normalized not in {"data", "key", "label", "title"}:
                found.setdefault(normalized, child)
            _report_values(child, found)
    elif isinstance(value, list):
        for child in value:
            _report_values(child, found)
    return found


def _first_report_value(values: dict[str, Any], *names: str) -> Any:
    for name in names:
        wanted = name.casefold()
        for key, value in values.items():
            if key == wanted or wanted in key:
                if value not in (None, "", [], {}):
                    return value
    return ""


def _plain_report_text(value: Any) -> str:
    """Convert MCP rich-text/report values into readable text, never JSON."""
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(filter(None, (_plain_report_text(item) for item in value)))
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"].strip()
        lines: list[str] = []
        ignored = {"type", "style", "id", "key", "label", "title"}
        for key, child in value.items():
            if str(key).casefold() in ignored or child in (None, "", [], {}):
                continue
            text = _plain_report_text(child)
            if not text:
                continue
            readable_key = re.sub(r"(?<!^)(?=[A-Z])", " ", str(key)).replace("_", " ").strip()
            if isinstance(child, (str, int, float, bool)) and readable_key.casefold() not in {"data", "value", "content", "sections"}:
                lines.append(f"{readable_key.title()}: {text}")
            else:
                lines.append(text)
        return "\n".join(lines)
    return str(value).strip()


def _usable_insight(text: str, heading: str) -> str:
    cleaned = re.sub(rf"^\s*{re.escape(heading)}\s*[:\-]?\s*", "", text.strip(), flags=re.IGNORECASE)
    lowered = cleaned.casefold()
    unavailable = ("currently not available", "currently unavailable", "not available for this topic", "no insight available")
    return "" if not cleaned or any(marker in lowered for marker in unavailable) else cleaned


def _report_insight(report: Any, heading: str) -> str:
    """Find the best named insight in MCP report fields or rich-text sections."""
    wanted = heading.casefold()
    candidates: list[str] = []
    peer_headings = {
        "audience insight", "sponsor insight", "creator insight", "market research",
        "overview", "performance", "related content ideas", "related thumbnails",
        "related caption hooks", "example content idea", "hashtags",
    }

    def normalized_key(value: Any) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", " ", str(value)).replace("_", " ").strip().casefold()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            label = normalized_key(value.get("key") or value.get("label") or value.get("title") or "")
            if label == wanted or wanted in label:
                data = value.get("data", value.get("value", value.get("content", value)))
                candidates.append(_plain_report_text(data))
            for key, child in value.items():
                normalized = normalized_key(key)
                if normalized == wanted or wanted in normalized:
                    candidates.append(_plain_report_text(child))
                visit(child)
        elif isinstance(value, list):
            blocks: list[tuple[str, bool]] = []
            for item in value:
                if not isinstance(item, dict) or not isinstance(item.get("sections"), list):
                    continue
                sections = item["sections"]
                text = " ".join(
                    str(section.get("text") or "").strip()
                    for section in sections
                    if isinstance(section, dict) and str(section.get("text") or "").strip()
                ).strip()
                bold = any(str(section.get("type") or "").upper() == "BOLD" for section in sections if isinstance(section, dict))
                if text:
                    blocks.append((text, bold))
            for index, (text, _) in enumerate(blocks):
                if text.strip().casefold().rstrip(":") != wanted:
                    continue
                body: list[str] = []
                for following, is_heading in blocks[index + 1:]:
                    following_heading = following.strip().casefold().rstrip(":")
                    # Rich reports frequently bold Themes, Countries and Languages inside
                    # Creator Insight. Only a real peer section heading ends the insight.
                    if following_heading in peer_headings or (is_heading and following_heading.endswith(" insight")):
                        break
                    body.append(following)
                candidates.append("\n".join(body))
            for child in value:
                visit(child)

    visit(report)
    usable = [_usable_insight(candidate, heading) for candidate in candidates]
    usable = [candidate for candidate in usable if candidate]
    return max(usable, key=len, default="")


def _report_hashtags(report: Any, outline: dict[str, Any]) -> list[str]:
    """Return the MCP report's hashtags as clean, display-ready tags."""
    values = _report_values(report)
    raw: Any = outline.get("hashtags") or _first_report_value(
        values, "hashtags and keywords", "hashtags", "hashtag"
    )


    if not raw:
        raw = _report_insight(report, "Hashtags") or _report_insight(report, "Hashtags and Keywords")
    if isinstance(raw, dict):
        raw = raw.get("data", raw.get("value", raw.get("content", raw)))
    entries = raw if isinstance(raw, list) else re.split(r"[,\n]+", _plain_report_text(raw))
    tags: list[str] = []
    for entry in entries:
        text = _plain_report_text(entry).strip()
        text = re.sub(r"^hashtags?(?:\s+and\s+keywords)?\s*:\s*", "", text, flags=re.IGNORECASE)
        fragments = re.findall(r"#[A-Za-z0-9_.]+", text)
        if not fragments and text:
            words = re.findall(r"[A-Za-z0-9]+", text)
            if words:
                fragments = ["#" + "".join(word[:1].upper() + word[1:] for word in words)[:64]]
        for tag in fragments:
            if tag != "#" and tag.casefold() not in {item.casefold() for item in tags}:
                tags.append(tag)
    return tags[:20]


@app.get("/privacy")
async def privacy_policy():
    return FileResponse(ROOT / "static" / "privacy.html")


@app.get("/about")
async def public_homepage():
    return FileResponse(ROOT / "static" / "about.html")


@app.get("/terms")
async def terms_of_service():
    return FileResponse(ROOT / "static" / "terms.html")


def _public_project(project: dict[str, Any]) -> dict[str, Any]:
    """Remove proprietary production prompts from every browser-facing project payload."""
    result = dict(project)
    stored = project.get("prompt") if isinstance(project.get("prompt"), dict) else {}
    concept = str(stored.get("concept") or (project.get("topic") or {}).get("topic") or (project.get("topic") or {}).get("title") or "Video concept")
    result["prompt"] = {"concept": concept, "text": concept[:180], "secured": True}
    return result


def _public_workspace(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    result["projects"] = [_public_project(project) for project in data.get("projects", [])]
    return result


def _creatorthon_generation_prompt(project: dict[str, Any], submitted_prompt: str | None) -> tuple[str, bool]:
    """Use an explicit participant prompt when supplied; otherwise keep the secured server prompt."""
    custom = str(submitted_prompt or "").strip()
    stored = project.get("prompt") if isinstance(project.get("prompt"), dict) else {}
    stored_text = str(stored.get("text") or "").strip()
    if custom:
        # The concept creator saves its generated prompt before starting the
        # provider job, then submits the same value again.  An identical value
        # is still the secured Viralizer prompt, not a participant override.
        if stored_text and custom == stored_text:
            return stored_text, False
        return custom, True
    return stored_text, False


def _creatorthon_prompt_matches_topic(topic: dict[str, Any], prompt: str) -> bool:
    """Conservatively flag custom prompts with no meaningful lexical connection to the chosen topic."""
    stop = {
        "about", "after", "before", "best", "campaign", "celebration", "commercial", "create", "during",
        "featuring", "from", "into", "latest", "make", "news", "premium", "scene", "seconds", "short",
        "show", "that", "their", "this", "through", "topic", "video", "with",
    }
    title = str(topic.get("topic") or topic.get("title") or "").casefold()
    custom = str(prompt or "").casefold()
    words = lambda value: {word for word in re.findall(r"[a-z0-9]+", value) if len(word) >= 3 and word not in stop}
    topic_words, prompt_words = words(title), words(custom)
    if not topic_words or not prompt_words:
        return False
    if title.strip() and title.strip() in custom:
        return True
    overlap = topic_words & prompt_words
    required = 1 if len(topic_words) <= 2 else 2
    return len(overlap) >= required


@app.get("/api/creatorthon/profile")
async def creatorthon_profile(request: Request):
    user = creatorthon_user(request)
    return {"profile": get_profile(ROOT, user), "projects": [_public_project(item) for item in list_projects(ROOT, str(user.get("sub", "")))]}


@app.get("/api/creatorthon/workspace")
async def creatorthon_workspace(request: Request):
    """Return the signed-in user's complete, account-scoped creation history."""
    return _public_workspace(workspace(ROOT, creatorthon_user(request)))


@app.get("/api/creatorthon/projects/{project_id}")
async def get_creatorthon_project(request: Request, project_id: str):
    user = creatorthon_user(request)
    result = update_project(ROOT, str(user.get("sub", "")), project_id, {})
    if not result:
        raise HTTPException(404, "Creatorthon project not found.")
    return _public_project(result)


@app.get("/creatorthon/projects/{project_id}/video")
async def view_creatorthon_project_video_page(request: Request, project_id: str):
    """A browser-friendly, authenticated entry point for a saved video."""
    user = creatorthon_user(request)
    result = update_project(ROOT, str(user.get("sub", "")), project_id, {})
    if not result:
        raise HTTPException(404, "Creatorthon project not found.")
    video_url = str(result.get("video_url") or "").strip()
    if not video_url:
        raise HTTPException(409, "This project's narrated video is still being prepared.")
    if not video_url.startswith("/api/finished-video/"):
        raise HTTPException(409, "This project does not have a permanent finished-video link yet.")
    return RedirectResponse(video_url, status_code=307)

def _creatorthon_media_keys(project: dict[str, Any]) -> set[str]:
    """Return only Viralizer-owned R2 keys attached to a project."""
    keys: set[str] = set()
    urls = [str(project.get("video_url") or "")]
    urls.extend(str(asset.get("url") or "") for asset in project.get("assets") or [])
    for url in urls:
        match = re.fullmatch(r"/api/finished-video/(viralizer-(?:hybrid-)?[a-f0-9]{32}\.mp4)", url.strip())
        if match:
            keys.add(f"finished_videos/{match.group(1)}")
    production = project.get("production") if isinstance(project.get("production"), dict) else {}
    raw_key = str(production.get("raw_object_key") or "").strip().lstrip("/")
    if re.fullmatch(r"raw_videos/[A-Za-z0-9._-]+\.mp4", raw_key):
        keys.add(raw_key)
    return keys


async def _delete_creatorthon_media(project: dict[str, Any]) -> list[str]:
    keys = sorted(_creatorthon_media_keys(project))
    for key in keys:
        await delete_object_file(key)
        if key.startswith("finished_videos/"):
            filename = key.split("/", 1)[1]
            local = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / filename
            local.unlink(missing_ok=True)
    return keys


@app.delete("/api/creatorthon/projects/{project_id}/video")
async def delete_creatorthon_project_video(request: Request, project_id: str):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    project = update_project(ROOT, user_id, project_id, {})
    if not project:
        raise HTTPException(404, "Creatorthon project not found.")
    project["assets"] = [asset for asset in list_assets(ROOT, user_id) if asset.get("project_id") == project_id]
    try:
        deleted_keys = await _delete_creatorthon_media(project)
    except ObjectStoreError as exc:
        raise HTTPException(502, str(exc)) from exc
    deleted = delete_project_video(ROOT, user_id, project_id)
    if not deleted:
        raise HTTPException(404, "Creatorthon project not found.")
    return {"deleted": True, "project_id": project_id, "media_deleted": len(deleted_keys)}


@app.delete("/api/creatorthon/projects/{project_id}")
async def delete_creatorthon_project(request: Request, project_id: str):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    project = update_project(ROOT, user_id, project_id, {})
    if not project:
        raise HTTPException(404, "Creatorthon project not found.")
    project["assets"] = [asset for asset in list_assets(ROOT, user_id) if asset.get("project_id") == project_id]
    try:
        deleted_keys = await _delete_creatorthon_media(project)
    except ObjectStoreError as exc:
        raise HTTPException(502, str(exc)) from exc
    deleted = delete_project(ROOT, user_id, project_id)
    if not deleted:
        raise HTTPException(404, "Creatorthon project not found.")
    return {"deleted": True, "project_id": project_id, "media_deleted": len(deleted_keys)}

@app.get("/api/creatorthon/projects/{project_id}/share")
async def share_creatorthon_project_video(request: Request, project_id: str):
    """Redirect the owner to a seven-day, no-password R2 video share link."""
    user = creatorthon_user(request)
    result = update_project(ROOT, str(user.get("sub", "")), project_id, {})
    if not result:
        raise HTTPException(404, "Creatorthon project not found.")
    video_url = str(result.get("video_url") or "").strip()
    match = re.fullmatch(r"/api/finished-video/(viralizer-(?:hybrid-)?[a-f0-9]{32}\.mp4)", video_url)
    if not match:
        raise HTTPException(409, "This project's finished video is not available for sharing yet.")
    try:
        return RedirectResponse(object_share_url(f"finished_videos/{match.group(1)}"), status_code=307)
    except ObjectStoreError as exc:
        raise HTTPException(502, str(exc)) from exc

def _video_byte_range(range_header: str, size: int) -> tuple[int, int] | None:
    """Parse one RFC 7233 byte range for iPhone/Safari media playback."""
    if not range_header:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip(), re.I)
    if not match or size <= 0:
        raise HTTPException(416, "Requested video range is not satisfiable.", headers={"Content-Range": f"bytes */{size}"})
    first, last = match.groups()
    if not first and not last:
        raise HTTPException(416, "Requested video range is not satisfiable.", headers={"Content-Range": f"bytes */{size}"})
    if not first:
        suffix = int(last)
        if suffix <= 0:
            raise HTTPException(416, "Requested video range is not satisfiable.", headers={"Content-Range": f"bytes */{size}"})
        start, end = max(0, size - suffix), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise HTTPException(416, "Requested video range is not satisfiable.", headers={"Content-Range": f"bytes */{size}"})
    return start, end


def _video_file_response(
    request: Request,
    path: Path,
    filename: str,
    *,
    download: bool = False,
) -> Response:
    """Stream an MP4 with explicit byte ranges required by mobile Safari."""
    size = path.stat().st_size
    selected = _video_byte_range(request.headers.get("range", ""), size)
    start, end = selected or (0, max(0, size - 1))
    length = max(0, end - start + 1)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": (
            f'attachment; filename="{filename}"' if download else f'inline; filename="{filename}"'
        ),
        "X-Content-Type-Options": "nosniff",
    }
    if selected:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    def content():
        remaining = length
        with path.open("rb") as source:
            source.seek(start)
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        content(),
        status_code=206 if selected else 200,
        media_type="video/mp4",
        headers=headers,
    )


@app.get("/api/creatorthon/projects/{project_id}/video")
async def view_creatorthon_project_video(request: Request, project_id: str, download: bool = False):
    """Open a signed-in user's finished video without exposing another user's media."""
    user = creatorthon_user(request)
    result = update_project(ROOT, str(user.get("sub", "")), project_id, {})
    if not result:
        raise HTTPException(404, "Creatorthon project not found.")
    video_url = str(result.get("video_url") or "").strip()
    if not video_url:
        raise HTTPException(409, "This project's narrated video is still being prepared.")
    if not video_url.startswith("/api/finished-video/"):
        raise HTTPException(409, "This project does not have a permanent finished-video link yet.")
    filename = video_url.removeprefix("/api/finished-video/")
    if not re.fullmatch(r"viralizer-(?:hybrid-)?[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(404, "Finished video not found.")
    try:
        signed_url = object_share_url(
            f"finished_videos/{filename}",
            expires_in=3600,
            disposition="attachment" if download else "inline",
            filename=f"viralizer-video-{project_id}.mp4" if download else filename,
        )
        return RedirectResponse(
            signed_url,
            status_code=307,
            headers={"Cache-Control": "private, no-store"},
        )
    except ObjectStoreError:
        # Local development and temporary storage outages retain proxy playback.
        pass
    path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / filename
    if not path.is_file() and not await restore_object_file(path, f"finished_videos/{filename}"):
        raise HTTPException(404, "Finished video not found.")
    return _video_file_response(
        request,
        path,
        f"viralizer-video-{project_id}.mp4" if download else filename,
        download=download,
    )


@app.post("/api/creatorthon/reports")
async def store_creatorthon_report(request: Request, payload: CreatorthonReportRequest):
    user = creatorthon_user(request)
    return save_report(ROOT, str(user.get("sub", "")), payload.model_dump())


@app.put("/api/creatorthon/profile")
async def update_creatorthon_profile(request: Request, payload: CreatorthonProfileRequest):
    user = creatorthon_user(request)
    if payload.onboarding_complete and not payload.interests:
        raise HTTPException(422, "Select at least one interest.")
    return {"profile": save_profile(ROOT, user, payload.model_dump())}


@app.get("/api/creatorthon/workflow")
async def get_creatorthon_workflow(request: Request):
    user = creatorthon_user(request)
    return {"workflow": get_workflow_state(ROOT, str(user.get("sub", "")))}


@app.put("/api/creatorthon/workflow")
async def update_creatorthon_workflow(request: Request, payload: CreatorthonWorkflowRequest):
    user = creatorthon_user(request)
    return {"workflow": save_workflow_state(ROOT, str(user.get("sub", "")), payload.model_dump())}


_CREATOR_ROLE_TOPIC_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CREATOR_ROLE_TOPIC_TASKS: dict[str, asyncio.Task] = {}


def _creator_role_topic_cache_key(
    topics: list[dict[str, Any]], role: str, user_type: str, category: str
) -> str:
    signature = json.dumps(
        {"role": role, "user_type": user_type, "category": category,
         "topics": [_topic_title_value(topic) for topic in topics]},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _fallback_role_topic_match(topic: dict[str, Any], role: str, user_type: str, index: int) -> dict[str, Any]:
    """Provide a safe role-aware result when the ranking model is unavailable."""
    original = _topic_title_value(topic)
    clean_role = role.strip() or "Content Creator"
    role_lower = clean_role.casefold()
    if any(value in role_lower for value in ("reviewer", "affiliate")):
        content_format, angle = "Review / comparison", "Evaluate what changed, who should consider it, and the practical buying decision."
    elif any(value in role_lower for value in ("educator", "education", "trainer", "coach", "consultant")):
        content_format, angle = "Explainer", "Teach the development clearly, explain why it matters, and give the audience one useful takeaway."
    elif any(value in role_lower for value in ("news", "journalist", "writer", "blogger")):
        content_format, angle = "News analysis", "Lead with the verified development, add concise context, and explain the consequence without inventing claims."
    elif any(value in role_lower for value in ("instagram", "tiktok", "meme", "comedy")):
        content_format, angle = "Short-form social", "Open with a visual hook, communicate one clear development, and end with a discussion-worthy takeaway."
    elif any(value in role_lower for value in ("business", "entrepreneur", "founder", "marketing", "linkedin")):
        content_format, angle = "Business insight", "Explain the commercial meaning, the audience affected, and the decision or opportunity creators should watch."
    else:
        content_format, angle = "Creator commentary", "Turn the verified story into a concise role-relevant narrative with a strong hook and practical audience value."
    score = max(100, 132 - index * 2)
    updated = dict(topic)
    updated.update({
        "source_title": original, "role_focused_title": f"{original} — {content_format}"[:140],
        "creator_role": clean_role, "profile_type": user_type,
        "role_match_index": score, "role_match_label": "Strong role match",
        "role_match_reason": f"Selected for a {clean_role} using a {content_format.lower()} angle.",
        "recommended_format": content_format,
        "creator_angle": f"For this {clean_role}, {angle}",
    })
    return updated


async def _personalize_topics_for_role(
    topics: list[dict[str, Any]], role: str, user_type: str, category: str
) -> list[dict[str, Any]]:
    """Rank verified stories for a creator role without changing their source facts."""
    candidates = [dict(topic) for topic in topics if _topic_title_value(topic)][:20]
    role = role.strip() or "Content Creator"
    user_type = user_type.strip() or "Individual"
    cache_key = _creator_role_topic_cache_key(candidates, role, user_type, category)
    cached = _CREATOR_ROLE_TOPIC_CACHE.get(cache_key)
    if cached and cached[0] > time.time():
        return [dict(topic) for topic in cached[1]]
    fallback = [_fallback_role_topic_match(topic, role, user_type, index) for index, topic in enumerate(candidates)]
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or not candidates:
        return fallback[:10]
    instruction = """You are Viralizer's Creator Opportunity Engine. Rank source-backed news stories for one creator profile.
Return JSON only with this shape: {"matches":[{"index":0,"role_match_index":100,"role_focused_title":"...","creator_angle":"...","role_match_reason":"...","recommended_format":"..."}]}.
Requirements:
- Score from 0 to 200. Return only candidates scoring 100 or higher.
- 100-124 Strong, 125-149 Excellent, 150-174 Exceptional, 175-200 Perfect opportunity.
- Judge direct role relevance, content-format suitability, audience alignment, platform usefulness, creator objective, monetization potential, freshness, and production feasibility.
- Never change, invent, or exaggerate the source facts, entity, event, date, product, or claim.
- role_focused_title must remain faithful to the original story while making the creator opportunity explicit.
- creator_angle must give a concrete content direction tailored to the role.
- Keep role_match_reason under 22 words and role_focused_title under 100 characters.
- Return the strongest matches first. Each source index may appear once."""
    model = os.getenv("OPENAI_ROLE_MATCH_MODEL", "").strip() or os.getenv("OPENAI_MODEL", "").strip() or "gpt-4.1-mini"
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": instruction}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps({
                "creator_role": role, "profile_type": user_type, "selected_category": category,
                "candidates": [{"index": index, "title": _topic_title_value(topic),
                                "summary": str(topic.get("summary") or topic.get("description") or "")[:500]}
                               for index, topic in enumerate(candidates)],
            }, ensure_ascii=False)}]},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post("https://api.openai.com/v1/responses",
                                         headers={"Authorization": f"Bearer {key}"}, json=payload)
        response.raise_for_status()
        parsed = json.loads(_openai_response_text(response.json()))
        ranked: list[dict[str, Any]] = []
        seen: set[int] = set()
        for match in parsed.get("matches") or []:
            index = int(match.get("index", -1))
            score = int(match.get("role_match_index", 0))
            if index in seen or not 0 <= index < len(candidates) or score < 100:
                continue
            seen.add(index)
            updated = dict(candidates[index])
            updated.update({
                "source_title": _topic_title_value(candidates[index]),
                "role_focused_title": str(match.get("role_focused_title") or _topic_title_value(candidates[index]))[:140],
                "creator_role": role, "profile_type": user_type,
                "role_match_index": min(200, score),
                "role_match_label": "Perfect creator opportunity" if score >= 175 else "Exceptional opportunity" if score >= 150 else "Excellent match" if score >= 125 else "Strong role match",
                "role_match_reason": str(match.get("role_match_reason") or "Directly relevant to this creator role.")[:220],
                "recommended_format": str(match.get("recommended_format") or "Creator commentary")[:80],
                "creator_angle": str(match.get("creator_angle") or fallback[index]["creator_angle"])[:700],
            })
            ranked.append(updated)
        if ranked:
            result = ranked[:10]
            _CREATOR_ROLE_TOPIC_CACHE[cache_key] = (time.time() + 21600, result)
            return result
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError, KeyError):
        pass
    return fallback[:10]


def _personalize_topics_fast(
    topics: list[dict[str, Any]], role: str, user_type: str, category: str
) -> list[dict[str, Any]]:
    """Return role-aware topics immediately and warm the stronger LLM ranking in the background."""
    candidates = [dict(topic) for topic in topics if _topic_title_value(topic)][:20]
    normalized_role = role.strip() or "Content Creator"
    normalized_type = user_type.strip() or "Individual"
    cache_key = _creator_role_topic_cache_key(candidates, normalized_role, normalized_type, category)
    cached = _CREATOR_ROLE_TOPIC_CACHE.get(cache_key)
    if cached and cached[0] > time.time():
        return [dict(topic) for topic in cached[1]]
    fallback = [
        _fallback_role_topic_match(topic, normalized_role, normalized_type, index)
        for index, topic in enumerate(candidates)
    ][:10]
    if os.getenv("OPENAI_API_KEY", "").strip() and cache_key not in _CREATOR_ROLE_TOPIC_TASKS:
        task = asyncio.create_task(
            _personalize_topics_for_role(candidates, normalized_role, normalized_type, category)
        )
        _CREATOR_ROLE_TOPIC_TASKS[cache_key] = task
        task.add_done_callback(lambda _task, key=cache_key: _CREATOR_ROLE_TOPIC_TASKS.pop(key, None))
    return fallback


def _objective_format(value: str) -> str:
    lowered = value.casefold()
    formats = (
        (("product review", "review", "verdict"), "Product review"),
        (("tutorial", "how to", "step by step"), "Tutorial"),
        (("presentation", "present"), "Presentation"),
        (("comparison", "compare", "versus", " vs "), "Comparison"),
        (("promotional", "promotion", "advert", "sell"), "Promotional video"),
        (("education", "educational", "explain", "teach"), "Educational explainer"),
        (("opinion", "commentary", "reaction"), "Opinion / commentary"),
        (("news", "update"), "News explanation"),
    )
    return next((label for terms, label in formats if any(term in lowered for term in terms)), "Creator-directed video")


async def _refine_creator_objective(topic: dict[str, Any], objective: str, role: str) -> dict[str, Any]:
    original = " ".join(objective.split())
    fallback_format = _objective_format(original)
    fallback = {
        "original_objective": original,
        "refined_objective": f"Create a {fallback_format.lower()} that follows this direction: {original}",
        "video_format": fallback_format,
        "objective_match": 100,
    }
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return fallback
    instruction = """Refine a creator's short objective into a precise video-production objective.
Return JSON only: {"refined_objective":"...","video_format":"...","objective_match":0}.
Rules:
- Preserve the user's intent; do not replace it with a different objective.
- Ground the objective in the supplied source topic and creator role without inventing facts.
- refined_objective must say what the video should accomplish, its structure, and intended ending in at most 55 words.
- video_format should be a short label such as Product review, Tutorial, Presentation, Comparison, News explanation, Educational explainer, Promotional video, or Opinion/commentary.
- objective_match is 0-100 and measures how faithfully the refinement follows the user's objective.
- Do not write the full video prompt or script here."""
    payload = {
        "model": os.getenv("OPENAI_OBJECTIVE_MODEL", "").strip() or os.getenv("OPENAI_MODEL", "").strip() or "gpt-4.1-mini",
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": instruction}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps({
                "source_topic": _topic_title_value(topic), "topic_summary": str(topic.get("summary") or topic.get("description") or "")[:600],
                "creator_role": role, "user_objective": original,
            }, ensure_ascii=False)}]},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post("https://api.openai.com/v1/responses",
                                         headers={"Authorization": f"Bearer {key}"}, json=payload)
        response.raise_for_status()
        result = json.loads(_openai_response_text(response.json()))
        refined = " ".join(str(result.get("refined_objective") or "").split())
        if not refined:
            return fallback
        return {
            "original_objective": original,
            "refined_objective": refined[:500],
            "video_format": " ".join(str(result.get("video_format") or fallback_format).split())[:80],
            "objective_match": max(0, min(100, int(result.get("objective_match") or 100))),
        }
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
        return fallback


@app.post("/api/creatorthon/topics")
async def creatorthon_topics(request: Request, payload: CreatorthonTopicsRequest):
    user = creatorthon_user(request)
    profile = get_profile(ROOT, user)
    role = str(profile.get("role") or "Content Creator")
    user_type = str((profile.get("socials") or {}).get("user_type") or "Individual")
    interests = list(dict.fromkeys(value.strip() for value in payload.interests if value.strip()))[:4]
    if not interests:
        raise HTTPException(422, "Select at least one interest.")
    cached_topics: list[dict[str, Any]] = []
    cached_keys: set[str] = set()
    all_categories_cached = True
    minimum_topics = max(3, int(os.getenv("CREATORTHON_TOPICS_PER_CATEGORY", "10")))
    for interest in interests:
        category_topics = get_cached_category_topics(
            ROOT,
            interest,
            allow_stale=True,
            stale_max_age_seconds=int(os.getenv("CREATORTHON_PREFETCH_STALE_SECONDS", "86400")),
        )
        if len(category_topics) < minimum_topics:
            all_categories_cached = False
        for topic in category_topics:
            key = _topic_title_value(topic).casefold()
            if key and key not in cached_keys:
                cached_keys.add(key)
                cached_topics.append(topic)
    if all_categories_cached and cached_topics:
        personalized = _personalize_topics_fast(cached_topics, role, user_type, interests[0])
        return {
            "topics": personalized, "count": len(personalized),
            "source": "Viralizer role-matched intelligence cache", "cached": True,
            "creator_role": role, "role_match_scale": 200,
        }
    queries: list[str] = []
    for interest in interests:
        queries.extend(build_category_discovery_queries(interest, "", "", "Everything", "")[:4])
    try:
        topics = await discover_category_topics(queries, max(40, minimum_topics * 3))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not discover worldwide topics: {exc}") from exc
    discovered = [item for item in annotate_topic_taxonomy(topics, interests, "Creatorthon", "Everything") if _english_topic(item)]
    combined: list[dict[str, Any]] = []
    combined_keys: set[str] = set()
    for item in [*cached_topics, *discovered]:
        key = _topic_title_value(item).casefold()
        if key and key not in combined_keys:
            combined_keys.add(key)
            combined.append(item)
    personalized = _personalize_topics_fast(combined, role, user_type, interests[0])
    return {"topics": personalized, "count": len(personalized), "source": "Worldwide public news sources",
            "creator_role": role, "role_match_scale": 200}


def _prediction_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _prediction_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _kalshi_market_topic(market: dict[str, Any]) -> dict[str, Any] | None:
    title = " ".join(str(market.get("title") or market.get("subtitle") or "").split())
    if not title:
        return None
    raw_price = _prediction_number(market.get("last_price") or market.get("yes_bid") or market.get("yes_ask"))
    probability = raw_price if raw_price <= 1 else raw_price / 100
    movement = _prediction_number(market.get("price_change_24h") or market.get("change_24h"))
    if abs(movement) >= 1:
        movement /= 100
    volume = _prediction_number(market.get("volume_24h") or market.get("volume") or market.get("liquidity_dollars"))
    ticker = str(market.get("event_ticker") or market.get("ticker") or "").strip()
    return {
        "topic": title, "title": title, "category": "Prediction Markets", "prediction_source": "Kalshi",
        "probability": round(max(0, min(1, probability)) * 100, 1), "movement_24h": round(movement * 100, 1),
        "volume": volume, "closes_at": market.get("close_time") or market.get("expected_expiration_time") or market.get("expiration_time"),
        "market_url": f"https://kalshi.com/markets/{quote(ticker)}" if ticker else "https://kalshi.com/",
        "summary": "Kalshi market-implied probability. This is market sentiment, not a confirmed prediction or financial advice.",
        "source": "Kalshi", "source_name": "Kalshi", "source_platforms": ["Kalshi"], "source_count": 1,
        "creator_angle": f"Explain what could move this market from its current {round(probability * 100)}% implied probability without recommending a trade.",
    }


def _kalshi_event_topic(event: dict[str, Any]) -> dict[str, Any] | None:
    title = " ".join(str(event.get("title") or "").split())
    markets = [item for item in event.get("markets", []) if isinstance(item, dict) and item.get("status") in {"active", "open"}]
    if not title or not markets:
        return None
    def market_price(item: dict[str, Any]) -> float:
        return max(0, min(1, _prediction_number(item.get("last_price_dollars") or item.get("yes_bid_dollars") or item.get("yes_ask_dollars"))))
    def market_volume(item: dict[str, Any]) -> float:
        return _prediction_number(item.get("volume_24h_fp") or item.get("volume_fp") or item.get("volume_24h") or item.get("volume"))
    markets.sort(key=market_volume, reverse=True)
    primary = markets[0]
    probability = market_price(primary)
    previous = _prediction_number(primary.get("previous_price_dollars"))
    movement = probability - previous if previous else 0
    outcomes = []
    for item in markets[:6]:
        label = " ".join(str(item.get("yes_sub_title") or item.get("subtitle") or item.get("title") or "Yes").split())
        outcomes.append({"label": label[:110], "probability": round(market_price(item) * 100, 1)})
    rules = " ".join(str(primary.get("rules_primary") or primary.get("early_close_condition") or "").split())
    subtitle = " ".join(str(event.get("sub_title") or "").split())
    event_ticker = str(event.get("event_ticker") or primary.get("event_ticker") or primary.get("ticker") or "").strip()
    settlement_sources = [
        {"name": str(item.get("name") or "").strip(), "url": str(item.get("url") or "").strip()}
        for item in event.get("settlement_sources", []) if isinstance(item, dict) and item.get("name")
    ][:3]
    total_volume = sum(market_volume(item) for item in markets)
    close_times = [str(item.get("close_time") or item.get("expected_expiration_time") or "") for item in markets]
    close_time = min((value for value in close_times if value), default="")
    return {
        "topic": title, "title": title, "category": "Prediction Markets", "market_category": event.get("category") or "Other",
        "prediction_source": "Kalshi", "probability": round(probability * 100, 1), "movement_24h": round(movement * 100, 1),
        "leading_outcome": outcomes[0]["label"] if outcomes else "Yes", "outcomes": outcomes,
        "market_context": subtitle, "what_yes_means": rules[:900], "settlement_sources": settlement_sources,
        "volume": total_volume, "closes_at": close_time,
        "market_url": f"https://kalshi.com/markets/{quote(event_ticker)}" if event_ticker else "https://kalshi.com/",
        "summary": (f"{subtitle}. " if subtitle else "") + (f"A Yes outcome resolves when: {rules}" if rules else "Review the official Kalshi resolution rules."),
        "source": "Kalshi", "source_name": "Kalshi", "source_platforms": ["Kalshi"], "source_count": 1,
        "creator_angle": f"Explain in plain language what this Kalshi event asks, what Yes means, and what evidence could move its current implied probability without recommending a trade.",
    }


def _polymarket_topic(market: dict[str, Any]) -> dict[str, Any] | None:
    title = " ".join(str(market.get("question") or market.get("title") or "").split())
    if not title:
        return None
    outcomes, prices = _prediction_json_list(market.get("outcomes")), _prediction_json_list(market.get("outcomePrices"))
    numeric_prices = [_prediction_number(value) for value in prices]
    lead_index = max(range(len(numeric_prices)), key=numeric_prices.__getitem__) if numeric_prices else 0
    probability = numeric_prices[lead_index] if numeric_prices else _prediction_number(market.get("lastTradePrice"))
    leading = str(outcomes[lead_index]) if lead_index < len(outcomes) else "Leading outcome"
    movement = _prediction_number(market.get("oneDayPriceChange") or market.get("priceChange24h"))
    volume = _prediction_number(market.get("volume24hr") or market.get("volume") or market.get("liquidity"))
    slug = str(market.get("slug") or market.get("eventSlug") or "").strip()
    return {
        "topic": title, "title": title, "category": "Prediction Markets", "prediction_source": "Polymarket",
        "leading_outcome": leading, "probability": round(max(0, min(1, probability)) * 100, 1),
        "movement_24h": round(movement * 100, 1), "volume": volume,
        "closes_at": market.get("endDate") or market.get("end_date_iso"),
        "market_url": f"https://polymarket.com/event/{quote(slug)}" if slug else "https://polymarket.com/",
        "summary": "Polymarket market-implied probability. This is market sentiment, not a confirmed prediction or financial advice.",
        "source": "Polymarket", "source_name": "Polymarket", "source_platforms": ["Polymarket"], "source_count": 1,
        "creator_angle": f"Explain the evidence behind {leading} at {round(probability * 100)}% without recommending a trade.",
    }


async def _fetch_prediction_market_topics(source: str, *, limit: int = 30) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Viralizer/3.0 market-topic reader"}) as client:
        if source == "kalshi":
            response = await client.get("https://api.elections.kalshi.com/trade-api/v2/events", params={"limit": 200, "status": "open", "with_nested_markets": "true"})
            response.raise_for_status()
            raw = response.json().get("events", [])
            topics = [topic for item in raw if (topic := _kalshi_event_topic(item))]
        else:
            response = await client.get("https://gamma-api.polymarket.com/markets", params={"active": "true", "closed": "false", "limit": 100, "order": "volume24hr", "ascending": "false"})
            response.raise_for_status()
            raw = response.json()
            topics = [topic for item in (raw if isinstance(raw, list) else []) if (topic := _polymarket_topic(item))]
    topics.sort(key=lambda item: (_prediction_number(item.get("volume")), abs(_prediction_number(item.get("movement_24h")))), reverse=True)
    return topics[:max(1, min(200, limit))]


def _search_prediction_market_topics(topics: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    terms = [term for term in re.findall(r"[\w'-]+", query.casefold()) if len(term) > 1]
    if not terms:
        return topics
    matches = []
    for topic in topics:
        outcome_text = " ".join(str(item.get("label") or "") for item in topic.get("outcomes", []) if isinstance(item, dict))
        haystack = " ".join(str(topic.get(key) or "") for key in ("title", "topic", "market_context", "market_category", "summary", "what_yes_means"))
        haystack = f"{haystack} {outcome_text}".casefold()
        if all(term in haystack for term in terms):
            matches.append(topic)
    return matches


async def _search_kalshi_topics(query: str, *, result_limit: int = 30, page_limit: int = 20) -> list[dict[str, Any]]:
    """Search later Kalshi cursor pages as well as nested outcome names."""
    matches: list[dict[str, Any]] = []
    cursor = ""
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "Viralizer/3.0 market-topic search"}) as client:
        for _ in range(max(1, page_limit)):
            params = {"limit": 200, "status": "open", "with_nested_markets": "true"}
            if cursor:
                params["cursor"] = cursor
            response = None
            for attempt in range(3):
                try:
                    response = await client.get("https://api.elections.kalshi.com/trade-api/v2/events", params=params)
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt == 2:
                        if matches:
                            return matches[:result_limit]
                        raise
                    await asyncio.sleep(0.35 * (attempt + 1))
            payload = response.json()
            page_topics = [topic for item in payload.get("events", []) if (topic := _kalshi_event_topic(item))]
            matches.extend(_search_prediction_market_topics(page_topics, query))
            if len(matches) >= result_limit:
                break
            cursor = str(payload.get("cursor") or "")
            if not cursor:
                break
    matches.sort(key=lambda item: (_prediction_number(item.get("volume")), abs(_prediction_number(item.get("movement_24h")))), reverse=True)
    return matches[:result_limit]


async def _prefetch_prediction_market_topics() -> None:
    """Warm both market feeds and persist MCP reports before presentation traffic."""
    await asyncio.sleep(max(0, int(os.getenv("PREDICTION_MARKET_PREFETCH_DELAY_SECONDS", "2"))))
    ttl_seconds = int(os.getenv("CREATORTHON_PREFETCH_TTL_SECONDS", "86400"))
    report_limit = max(0, min(12, int(os.getenv("PREDICTION_MARKET_PREFETCH_REPORTS_PER_SOURCE", "6"))))
    LOGGER.info("Prediction market prefetch started sources=2 reports_per_source=%d", report_limit)

    async def warm(source: str) -> dict[str, int]:
        try:
            topics = await _fetch_prediction_market_topics(source)
        except Exception as exc:
            LOGGER.exception("Prediction market prefetch failed source=%s: %s", source, exc)
            return {"topics": 0, "reports": 0, "failed": 1}
        PREDICTION_MARKET_CACHE[source] = (time.time(), topics)
        saved = 0
        failed = 0
        for topic in topics[:report_limit]:
            title = _topic_title_value(topic)
            if not title:
                continue
            cached = get_cached_topic_insight(ROOT, title, stale_max_age_seconds=ttl_seconds)
            if cached and int(cached.get("query_refiner_version") or 0) >= MCP_QUERY_REFINER_VERSION:
                saved += 1
                continue
            try:
                result = await _proprietary_insight_payload(title)
                save_cached_topic_insight(ROOT, title, result, ttl_seconds)
                saved += 1
            except Exception as exc:
                failed += 1
                LOGGER.exception("Prediction market MCP prefetch failed source=%s topic=%r: %s", source, title, exc)
        LOGGER.info("Prediction market source ready source=%s topics=%d reports=%d failed=%d", source, len(topics), saved, failed)
        return {"topics": len(topics), "reports": saved, "failed": failed}

    results = await asyncio.gather(warm("kalshi"), warm("polymarket"))
    LOGGER.info(
        "Prediction market prefetch complete topics=%d reports=%d failures=%d",
        sum(item["topics"] for item in results), sum(item["reports"] for item in results), sum(item["failed"] for item in results),
    )


@app.get("/api/creatorthon/prediction-markets/{source}")
async def creatorthon_prediction_markets(request: Request, source: str):
    creatorthon_user(request)
    source = source.strip().casefold()
    query = " ".join(str(request.query_params.get("q") or "").split())[:120]
    if source not in {"kalshi", "polymarket"}:
        raise HTTPException(404, "Choose Kalshi or Polymarket.")
    cached = PREDICTION_MARKET_CACHE.get(source)
    if not query and cached and time.time() - cached[0] < 300:
        return {"source": source.title(), "topics": cached[1], "count": len(cached[1]), "cached": True}
    try:
        topics = await (_search_kalshi_topics(query) if query and source == "kalshi" else _fetch_prediction_market_topics(source, limit=200 if query else 30))
        if query and source != "kalshi":
            topics = _search_prediction_market_topics(topics, query)[:30]
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
        LOGGER.warning("Prediction market fetch failed source=%s error=%s", source, exc)
        if cached and not query:
            return {"source": source.title(), "topics": cached[1], "count": len(cached[1]), "cached": True, "stale": True}
        raise HTTPException(502, f"{source.title()} markets are temporarily unavailable.") from exc
    if not query:
        PREDICTION_MARKET_CACHE[source] = (time.time(), topics)
    return {"source": source.title(), "topics": topics, "count": len(topics), "cached": False, "query": query, "refresh_seconds": 300}


@app.post("/api/creatorthon/prediction-coverage")
async def creatorthon_prediction_coverage(request: Request, payload: CreatorthonPredictionCoverageRequest):
    creatorthon_user(request)
    topic = " ".join(payload.topic.split())
    context = " ".join(payload.context.split())
    cache_key = f"{topic.casefold()}|{context.casefold()}"
    cached = PREDICTION_COVERAGE_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < 1800:
        return {"topic": topic, "articles": cached[1], "cached": True}
    stopwords = {"will", "would", "could", "should", "the", "a", "an", "be", "been", "being", "is", "are", "was", "were", "when", "where", "what", "which", "who", "how", "any", "before", "after", "during", "by", "in", "on", "at", "to", "of", "for", "and", "or"}
    topic_terms = {word for word in re.findall(r"[a-z0-9]+", topic.casefold()) if len(word) > 2 and word not in stopwords}
    proper_phrases = re.findall(r"(?:[A-Z][\w'-]+(?:\s+|$)){2,6}", topic)
    core_phrase = max((" ".join(value.split()) for value in proper_phrases), key=len, default="")
    queries = [topic, f"latest news {topic}"]
    if core_phrase and core_phrase.casefold() != topic.casefold():
        queries.insert(0, f'"{core_phrase}"')
    try:
        discovered = await asyncio.wait_for(
            discover_category_topics(queries[:3], 12, fast=True, enrich=False),
            timeout=12,
        )
    except asyncio.TimeoutError:
        LOGGER.warning("Prediction coverage discovery timed out topic=%r", topic)
        discovered = []
    except Exception as exc:
        LOGGER.warning("Prediction coverage discovery failed topic=%r error=%s", topic, exc)
        return {"topic": topic, "articles": [], "cached": False}
    ranked_articles = []
    for item in discovered:
        article_terms = set(re.findall(r"[a-z0-9]+", _topic_title_value(item).casefold()))
        overlap = len(topic_terms & article_terms)
        if topic_terms and overlap < min(2, len(topic_terms)):
            continue
        ranked_articles.append((overlap, str(item.get("published_at") or ""), item))
    ranked_articles.sort(key=lambda value: (value[0], value[1]), reverse=True)
    articles = []
    seen_urls: set[str] = set()
    for _, _, item in ranked_articles:
        urls = [str(value).strip() for value in item.get("source_urls", []) if str(value).startswith(("http://", "https://"))]
        url = str(item.get("canonical_url") or item.get("discovery_url") or (urls[0] if urls else "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        publisher = str(item.get("publisher_name") or item.get("publisher_domain") or "").strip()
        if not publisher:
            platforms = item.get("source_platforms") if isinstance(item.get("source_platforms"), list) else []
            publisher = str(platforms[0] if platforms else "News coverage")
        articles.append({
            "title": _topic_title_value(item),
            "url": url,
            "publisher": publisher,
            "published_at": str(item.get("published_at") or ""),
            "summary": str(item.get("summary") or "")[:360],
            "image": str(item.get("image") or ""),
        })
        if len(articles) >= 3:
            break
    PREDICTION_COVERAGE_CACHE[cache_key] = (time.time(), articles)
    return {"topic": topic, "articles": articles, "cached": False}


@app.post("/api/creatorthon/refine-objective")
async def refine_creatorthon_objective(request: Request, payload: CreatorthonObjectiveRequest):
    user = creatorthon_user(request)
    objective = " ".join(payload.objective.split())
    if len(objective.split()) > 25:
        raise HTTPException(422, "Your objective must be 25 words or fewer.")
    profile = get_profile(ROOT, user)
    return await _refine_creator_objective(payload.topic, objective, str(profile.get("role") or "Content Creator"))


def _refine_mcp_search_term(topic: str) -> str:
    """Turn an editorial headline into a concise, entity-rich MCP search phrase."""
    text = " ".join(str(topic).replace("–", " ").replace("—", " ").split())
    # A quoted product, title, event, or franchise name is normally the strongest
    # search entity. Prefer it over release-language surrounding the quotation.
    quoted = re.search(r"[‘’'\"]([^‘’'\"]{3,100})[’'\"]", text)
    if quoted:
        entity_words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", quoted.group(1).replace(":", " "))
        if 3 <= len(entity_words) <= 5:
            return " ".join(entity_words)
    # Convert market-opportunity headlines into the underlying searchable subject.
    # News headlines often lead with a number and end with a rhetorical question;
    # neither describes the entity/industry/market relationship MCP should search.
    if (
        re.search(r"\bafrica(?:'s|’s|n)?\b", text, re.I)
        and re.search(r"\bsmes?\b", text, re.I)
        and re.search(r"\bapparel\b", text, re.I)
        and re.search(r"\b(?:us|u\.s\.|united states)\b", text, re.I)
    ):
        return "African SME Apparel US Exports"
    # Apply the same intent cleanup to other sectors and regions: discard
    # headline-sized figures and rhetorical tails, then express "window" as the
    # underlying market opportunity that an intelligence search can resolve.
    text = re.sub(
        r"\s*[:|]\s*(?:what(?:'s|’s| is)|why|how|who|where|when)\b.*$",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b(?:[$£€₹]\s*)?\d+(?:[.,]\d+)?\s*(?:bn|billion|mn|million|trillion)\b", " ", text, flags=re.I)
    text = re.sub(r"\bwindow\b", "market opportunity", text, flags=re.I)
    if re.search(r"\bfestiv(?:e|al)\b", text, re.I) and re.search(r"\bfashion\b", text, re.I) and re.search(r"\b(?:growth|accelerat\w*|surge\w*|rise|jump\w*)\b", text, re.I):
        brand_part = re.split(r"\bfashion\b", text, maxsplit=1, flags=re.I)[0]
        brand_words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’&.-]*", brand_part)
        brand = " ".join(brand_words[:3]).strip()
        if brand:
            return f"{brand} Festive Fashion Surge"
    filler_phrases = (
        r"\bin (?:the )?spotlight\b", r"\btakes? cent(?:er|re) stage\b", r"\bset to\b",
        r"\bfeaturing\b", r"\ba celebration of\b", r"\bnew report says\b", r"\bwhat to know\b",
        r"\bunveils?\b", r"\bannounces?\b", r"\bhighlights?\b", r"\breveals?\b",
        r"\blaunches? (?:its |the )?new\b", r"\bputs? .*? in focus\b",
        r"\bdebuts?\b.*$", r"\bday and date\b.*$", r"\bwide release\b.*$",
        r"\b(?:gaming |news )?roundup\b.*$",
    )
    for phrase in filler_phrases:
        text = re.sub(phrase, " ", text, flags=re.I)
    disposable = {
        "industry", "latest", "major", "officially", "new", "are", "sees", "its", "the", "at", "in", "on", "for", "of",
        "and", "with", "from", "a", "an", "spotlight", "campaign", "featuring", "celebration",
    }
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", text)
    compact = [word for word in words if word.casefold() not in disposable]
    compact = [
        word for index, word in enumerate(compact)
        if not (
            0 < index < len(compact) - 1
            and compact[index - 1].isupper() and 2 <= len(compact[index - 1]) <= 8
            and word[:1].isupper() and word[1:].islower()
            and re.fullmatch(r"20\d{2}", compact[index + 1])
        )
    ]
    # YouTube/MCP queries work best as short entity phrases, not clipped headlines.
    return " ".join(compact[:5]).strip() or " ".join(words[:5]).strip()


def _valid_mcp_search_term(value: Any) -> str:
    """Accept only compact search phrases; never send unchecked model text to MCP."""
    text = " ".join(str(value or "").replace("–", " ").replace("—", " ").split()).strip(" .,:;!?\"'‘’")
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’&.-]*", text)
    if not 3 <= len(words) <= 5:
        return ""
    if len(" ".join(words)) > 80:
        return ""
    return " ".join(words)


def _search_term_matches_topic(term: str, topic: str) -> bool:
    """Reject fluent but unrelated model output while allowing light inflection changes."""
    ignored = {"about", "after", "from", "into", "market", "news", "with", "year"}
    term_words = {word.casefold().rstrip("s") for word in re.findall(r"[A-Za-z0-9]{4,}", term)} - ignored
    topic_words = {word.casefold().rstrip("s") for word in re.findall(r"[A-Za-z0-9]{4,}", topic)} - ignored
    return bool(term_words and topic_words and any(
        left == right or (len(left) >= 5 and len(right) >= 5 and (left.startswith(right) or right.startswith(left)))
        for left in term_words for right in topic_words
    ))


def _openai_response_text(payload: dict[str, Any]) -> str:
    text = str(payload.get("output_text") or "").strip()
    if text:
        return text
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                text = str(block.get("text") or "").strip()
                if text:
                    return text
    raise ValueError("The query-refinement model returned no text.")


async def _request_llm_search_terms(topic: str) -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = (
        os.getenv("OPENAI_QUERY_REFINER_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip()
        or os.getenv("OPENAI_STORY_MODEL", "").strip()
        or "gpt-4.1-mini"
    )
    instruction = """Convert one news headline into semantic search phrases for Viralizer MCP and YouTube research.
Return JSON only: {"primary":"...","fallbacks":["...","..."]}.
Rules:
- Every phrase must contain exactly 3 to 5 English words.
- Preserve the central named entity, product, company, event, market, or relationship.
- Express search intent, not the first five words of the headline.
- Remove editorial filler such as news, roundup, debuts, unveils, launches, day-and-date, wide release, what's holding it back, and large headline statistics unless essential.
- Do not invent facts or add unrelated entities.
- Make fallbacks meaningfully different but semantically faithful.
Example: “Star Wars: Galactic Racer Debuts on Amazon Luna Day and Date With Wide Release” -> {"primary":"Star Wars Galactic Racer","fallbacks":["Galactic Racer Amazon Luna","Star Wars Racing Game"]}.
Example: “Africa's 1.69 bn SME US apparel window: What's holding it back?” -> {"primary":"African SME Apparel US Exports","fallbacks":["Africa Apparel SMEs US Market"]}."""
    request_payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": instruction}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps({"headline": topic}, ensure_ascii=False)}]},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    refinement_timeout = max(2.0, min(15.0, float(os.getenv("OPENAI_QUERY_REFINER_TIMEOUT_SECONDS", "6"))))
    async with httpx.AsyncClient(timeout=refinement_timeout) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}"},
            json=request_payload,
        )
    response.raise_for_status()
    return json.loads(_openai_response_text(response.json()))


async def _llm_refined_search_terms(topic: str) -> tuple[str, list[str], str]:
    """Return validated model terms, falling back safely when AI is unavailable."""
    rule_term = _valid_mcp_search_term(_refine_mcp_search_term(topic))
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return rule_term, [], "rules"
    try:
        payload = await _request_llm_search_terms(topic)
        primary = _valid_mcp_search_term(payload.get("primary"))
        if primary and not _search_term_matches_topic(primary, topic):
            primary = ""
        raw_fallbacks = payload.get("fallbacks") if isinstance(payload.get("fallbacks"), list) else []
        fallbacks = [
            term for term in (_valid_mcp_search_term(value) for value in raw_fallbacks)
            if term and _search_term_matches_topic(term, topic) and term.casefold() not in {primary.casefold(), rule_term.casefold()}
        ][:2]
        if primary:
            return primary, fallbacks, "llm"
    except (httpx.HTTPError, RuntimeError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return rule_term, [], "rules"


def _mcp_search_candidates(topic: str, preferred: str = "", fallbacks: list[str] | None = None) -> list[str]:
    primary = " ".join(str(preferred).split()) or _refine_mcp_search_term(topic)
    candidates = [primary, *(fallbacks or [])]
    if primary.casefold() == "african sme apparel us exports":
        candidates.extend([
            "Africa Apparel SMEs US Market",
            "African Fashion Exports United States",
            "Africa US Apparel Trade SMEs",
        ])
    if re.search(r"\bsurge\b", primary, re.I):
        candidates.extend([re.sub(r"\bsurge\b", "Growth", primary, flags=re.I), re.sub(r"\bsurge\b", "", primary, flags=re.I)])
    without_year = " ".join(word for word in primary.split() if not re.fullmatch(r"20\d{2}", word))
    if 3 <= len(without_year.split()) <= 5:
        candidates.append(without_year)
    return list(dict.fromkeys(" ".join(value.split()[:5]) for value in candidates if 3 <= len(" ".join(value.split()).split()) <= 5))[:4]


async def _proprietary_insight_payload(topic: str, mcp_search_term: str = "") -> dict[str, Any]:
    report = None
    search_term = ""
    attempted_terms: list[str] = []
    last_error: MCPOutlineError | None = None
    llm_term, llm_fallbacks, refiner = await _llm_refined_search_terms(topic)
    preferred = _valid_mcp_search_term(mcp_search_term) or llm_term
    max_attempts = max(1, min(3, int(os.getenv("CREATORTHON_MCP_SEARCH_MAX_ATTEMPTS", "2"))))
    for candidate in _mcp_search_candidates(topic, preferred, llm_fallbacks)[:max_attempts]:
        attempted_terms.append(candidate)
        try:
            report = await get_full_report_from_mcp(candidate)
            search_term = candidate
            break
        except MCPOutlineError as exc:
            last_error = exc
    if report is None:
        raise last_error or MCPOutlineError("Viralizer returned no report for the refined topic searches.")
    try:
        outline = outline_from_full_report(report, topic)
    except MCPOutlineError:
        # Insights reports are valid even when the optional video-outline section is absent.
        outline = {}
    values = _report_values(report)
    audience = _report_insight(report, "Audience Insight") or _plain_report_text(_first_report_value(values, "audience detected"))
    creator = _report_insight(report, "Creator Insight")
    hashtags = _report_hashtags(report, outline)
    metrics = {
        "viral_topic_rank": outline.get("viral_rank") or _first_report_value(values, "viral topic rank"),
        "total_audience": outline.get("total_audience") or _first_report_value(values, "total audience"),
        "estimated_remaining_views": outline.get("remaining_reach") or _first_report_value(values, "estimated remaining views", "est. remaining views", "est remaining views", "remaining views", "remaining reach"),
        "boost": _first_report_value(values, "boost"),
        "resonance": _first_report_value(values, "resonance") or outline.get("estimated_resonance", ""),
    }
    return {
        "topic": topic,
        "display_topic": topic,
        "mcp_search_term": search_term,
        "mcp_search_terms_attempted": attempted_terms,
        "mcp_search_refiner": refiner,
        "query_refiner_version": MCP_QUERY_REFINER_VERSION,
        "parser_version": 2,
        "metrics": {key: value for key, value in metrics.items() if value not in (None, "", [], {})},
        "audience_insight": audience,
        "creator_insight": creator,
        "hashtags": hashtags,
        "source": "Viralizer MCP",
    }


# Private, approval-gated research automation for the central Viralizer channel.
# Instantiated after the MCP scorer is defined so the agent can reuse the same
# proprietary trend intelligence as the interactive application.
CHANNEL_AUTOMATION = ViralChannelAutomation(ROOT, _proprietary_insight_payload)


CREATORTHON_PREFETCH_CATEGORIES = (
    "Fashion", "AI", "Technology", "Beauty", "Business", "Gaming",
    "Food", "Sports", "Travel", "Cryptos", "Stocks", "Health",
)
# Increment whenever query-refinement behavior changes. Persisted reports from an
# older generation are requeued and fetched again instead of being shown.
MCP_QUERY_REFINER_VERSION = 6


def _topic_title_value(topic: dict[str, Any]) -> str:
    return " ".join(str(topic.get("topic") or topic.get("title") or topic.get("name") or "").split())


async def _prefetch_creatorthon_category(category: str, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    ttl_seconds = int(os.getenv("CREATORTHON_PREFETCH_TTL_SECONDS", "86400"))
    topic_limit = max(1, min(30, int(os.getenv("CREATORTHON_PREFETCH_TOPICS_PER_CATEGORY", "6"))))
    insight_limit = max(0, min(topic_limit, int(os.getenv("CREATORTHON_PREFETCH_INSIGHTS_PER_CATEGORY", "6"))))
    topics = get_cached_category_topics(ROOT, category)
    topic_source = "cache" if topics else "fetched"
    if not topics:
        queries = build_category_discovery_queries(category, "", "", "Everything", "")[:2]
        try:
            topics = await discover_category_topics(queries, topic_limit)
            topics = [
                item for item in annotate_topic_taxonomy(topics, [category], category, "Everything")
                if _english_topic(item)
            ][:topic_limit]
        except Exception as exc:
            # Never erase the last known-good category when discovery is temporarily unavailable.
            LOGGER.exception("Creatorthon prefetch failed to discover category=%s: %s", category, exc)
            return {"category": category, "topics": 0, "reports": 0, "failed": 1}
        if not topics:
            LOGGER.warning("Creatorthon prefetch returned no topics category=%s", category)
            return {"category": category, "topics": 0, "reports": 0, "failed": 1}
        save_cached_category_topics(ROOT, category, topics, ttl_seconds)

    counters = {"cached": 0, "saved": 0, "failed": 0}

    async def prepare(topic: dict[str, Any]) -> None:
        title = _topic_title_value(topic)
        if not title:
            counters["failed"] += 1
            return
        cached = get_cached_topic_insight(ROOT, title)
        if cached and int(cached.get("query_refiner_version") or 0) >= MCP_QUERY_REFINER_VERSION:
            counters["cached"] += 1
            return
        async with semaphore:
            try:
                result = await _proprietary_insight_payload(title)
            except Exception as exc:
                counters["failed"] += 1
                LOGGER.exception(
                    "Creatorthon prefetch report failed category=%s topic=%r: %s", category, title, exc
                )
                return
            save_cached_topic_insight(ROOT, title, result, ttl_seconds)
            counters["saved"] += 1

    if insight_limit:
        await asyncio.gather(*(prepare(topic) for topic in topics[:insight_limit]))
    report_count = counters["cached"] + counters["saved"]
    LOGGER.info(
        "Creatorthon prefetch category complete category=%s topics=%d topic_source=%s reports_ready=%d "
        "reports_cached=%d reports_saved=%d reports_failed=%d ttl_hours=%.1f",
        category, len(topics), topic_source, report_count, counters["cached"], counters["saved"],
        counters["failed"], ttl_seconds / 3600,
    )
    return {
        "category": category,
        "topics": len(topics),
        "reports": report_count,
        "failed": counters["failed"],
    }


async def _prefetch_all_creatorthon_topics() -> None:
    concurrency = max(1, min(6, int(os.getenv("CREATORTHON_PREFETCH_CONCURRENCY", "2"))))
    semaphore = asyncio.Semaphore(concurrency)
    # Event traffic is concentrated in the 12 featured categories. Warm those first
    # and leave custom categories on the normal request-time generation path.
    LOGGER.info(
        "Creatorthon event prefetch started categories=%d topics_per_category=%s reports_per_category=%s",
        len(CREATORTHON_PREFETCH_CATEGORIES),
        os.getenv("CREATORTHON_PREFETCH_TOPICS_PER_CATEGORY", "6"),
        os.getenv("CREATORTHON_PREFETCH_INSIGHTS_PER_CATEGORY", "6"),
    )
    results = []
    for category in CREATORTHON_PREFETCH_CATEGORIES:
        results.append(await _prefetch_creatorthon_category(category, semaphore))
    LOGGER.info(
        "Creatorthon event prefetch complete categories_ready=%d/%d topics_ready=%d reports_ready=%d failures=%d",
        sum(1 for item in results if item.get("topics") and item.get("reports")),
        len(CREATORTHON_PREFETCH_CATEGORIES),
        sum(int(item.get("topics") or 0) for item in results),
        sum(int(item.get("reports") or 0) for item in results),
        sum(int(item.get("failed") or 0) for item in results),
    )


async def _creatorthon_prefetch_scheduler() -> None:
    # Build one stable event snapshot. Valid category topics and reports are reused
    # after service restarts and are not automatically refreshed during the event.
    startup_delay = max(0, int(os.getenv("CREATORTHON_PREFETCH_STARTUP_DELAY_SECONDS", "5")))
    await asyncio.sleep(startup_delay)
    try:
        await _prefetch_all_creatorthon_topics()
    except Exception as exc:
        # Preserve every category/report that completed successfully.
        LOGGER.exception("Creatorthon event prefetch stopped unexpectedly: %s", exc)


async def _run_creatorthon_insight_queue(user_id: str) -> None:
    try:
        while True:
            job = claim_next_insight_job(ROOT, user_id)
            if not job:
                return
            try:
                title = _topic_title_value(job.get("topic", {}))
                result = get_cached_topic_insight(
                    ROOT,
                    title,
                    allow_stale=True,
                    stale_max_age_seconds=int(os.getenv("CREATORTHON_PREFETCH_STALE_SECONDS", "86400")),
                )
                if int((result or {}).get("query_refiner_version") or 0) < MCP_QUERY_REFINER_VERSION:
                    result = None
                if result is None:
                    result = await _proprietary_insight_payload(title)
                    save_cached_topic_insight(ROOT, title, result, int(os.getenv("CREATORTHON_PREFETCH_TTL_SECONDS", "5400")))
                finish_insight_job(ROOT, user_id, str(job["id"]), result=result)
            except Exception as exc:
                finish_insight_job(ROOT, user_id, str(job["id"]), error=str(exc) or "Viralizer intelligence could not complete this topic.")
    finally:
        CREATORTHON_INSIGHT_TASKS.pop(user_id, None)


def _start_creatorthon_insight_queue(user_id: str) -> None:
    task = CREATORTHON_INSIGHT_TASKS.get(user_id)
    if task and not task.done():
        return
    CREATORTHON_INSIGHT_TASKS[user_id] = asyncio.create_task(_run_creatorthon_insight_queue(user_id))


def _hydrate_creatorthon_insight_jobs_from_cache(user_id: str, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Complete pending jobs immediately when scheduled prefetch already has current data."""
    hydrated = False
    for job in jobs:
        if job.get("status") not in {"queued", "processing"}:
            continue
        title = _topic_title_value(job.get("topic", {}))
        cached = get_cached_topic_insight(
            ROOT,
            title,
            allow_stale=True,
            stale_max_age_seconds=int(os.getenv("CREATORTHON_PREFETCH_STALE_SECONDS", "86400")),
        )
        if int((cached or {}).get("query_refiner_version") or 0) < MCP_QUERY_REFINER_VERSION:
            continue
        finish_insight_job(ROOT, user_id, str(job["id"]), result=cached)
        hydrated = True
    return list_insight_jobs(ROOT, user_id) if hydrated else jobs


@app.post("/api/creatorthon/proprietary-insights")
async def creatorthon_proprietary_insights(request: Request, payload: CreatorthonInsightsRequest):
    creatorthon_user(request)
    try:
        return await _proprietary_insight_payload(payload.topic)
    except MCPOutlineError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/creatorthon/insight-queue")
async def enqueue_creatorthon_insight(request: Request, payload: CreatorthonInsightQueueRequest):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    try:
        job, created = enqueue_insight_job(ROOT, user_id, payload.topic)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    stale_completed_job = job.get("status") == "completed" and (
        int((job.get("result") or {}).get("parser_version") or 0) < 2
        or int((job.get("result") or {}).get("query_refiner_version") or 0) < MCP_QUERY_REFINER_VERSION
    )
    if stale_completed_job:
        retry_insight_job(ROOT, user_id, str(job["id"]))
        job = next(
            item for item in list_insight_jobs(ROOT, user_id)
            if str(item["id"]) == str(job["id"])
        )
    title = _topic_title_value(payload.topic)
    cached = get_cached_topic_insight(
        ROOT,
        title,
        allow_stale=True,
        stale_max_age_seconds=int(os.getenv("CREATORTHON_PREFETCH_STALE_SECONDS", "86400")),
    )
    if int((cached or {}).get("query_refiner_version") or 0) < MCP_QUERY_REFINER_VERSION:
        cached = None
    if created and cached:
        finish_insight_job(ROOT, user_id, str(job["id"]), result=cached)
        job = next(item for item in list_insight_jobs(ROOT, user_id) if str(item["id"]) == str(job["id"]))
    else:
        _start_creatorthon_insight_queue(user_id)
    jobs = _hydrate_creatorthon_insight_jobs_from_cache(user_id, list_insight_jobs(ROOT, user_id))
    current = next((item for item in jobs if str(item["id"]) == str(job["id"])), job)
    return {"job": current, "created": created, "jobs": jobs}


@app.get("/api/creatorthon/insight-queue")
async def get_creatorthon_insight_queue(request: Request):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    jobs = list_insight_jobs(ROOT, user_id)
    legacy_jobs = [
        job for job in jobs
        if job.get("status") == "completed" and (
            int((job.get("result") or {}).get("parser_version") or 0) < 2
            or int((job.get("result") or {}).get("query_refiner_version") or 0) < MCP_QUERY_REFINER_VERSION
        )
    ]
    for job in legacy_jobs:
        retry_insight_job(ROOT, user_id, str(job["id"]))
    if legacy_jobs:
        jobs = list_insight_jobs(ROOT, user_id)
    jobs = _hydrate_creatorthon_insight_jobs_from_cache(user_id, jobs)
    if any(job.get("status") in {"queued", "processing"} for job in jobs):
        _start_creatorthon_insight_queue(user_id)
    return {"jobs": jobs}


@app.post("/api/creatorthon/insight-queue/{job_id}/retry")
async def retry_creatorthon_insight(request: Request, job_id: str):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    if not retry_insight_job(ROOT, user_id, job_id):
        raise HTTPException(409, "Only a failed topic analysis can be retried.")
    _start_creatorthon_insight_queue(user_id)
    return {"jobs": list_insight_jobs(ROOT, user_id)}


@app.delete("/api/creatorthon/insight-queue/{job_id}")
async def delete_creatorthon_insight(request: Request, job_id: str):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    if not delete_insight_job(ROOT, user_id, job_id):
        raise HTTPException(404, "The selected topic was not found.")
    return {"jobs": list_insight_jobs(ROOT, user_id)}


@app.get("/api/creatorthon/event-status")
async def creatorthon_event_status(request: Request):
    user = creatorthon_user(request)
    capacity = event_capacity(ROOT, int(os.getenv("CREATORTHON_EVENT_USER_LIMIT", "50")))
    if _unlimited_creatorthon_user(user):
        return {"generation_used": False, "generation_status": "unlimited", "unlimited": True,
                "admin": _creatorthon_admin_user(user), "participant_number": None,
                "capacity": capacity, "participant_label": "Organizer"}
    status = generation_entitlement(ROOT, str(user.get("sub", "")), str(user.get("email") or ""))
    seat_number = int(status.get("seat_number") or 0)
    used = int(status.get("generation_count") or 0)
    allowance = 1 + int(status.get("extra_generation_credits") or 0)
    return {"generation_used": used >= allowance,
            "generation_status": status.get("generation_status") or "available", "unlimited": False, "admin": False,
            "videos_used": used, "total_allowance": allowance, "credits_remaining": max(0, allowance - used),
            "participant_number": seat_number, "capacity": capacity,
            "participant_label": f"Participant #{seat_number} of {capacity}"}


@app.get("/api/creatorthon/admin/state")
async def creatorthon_admin_state(request: Request):
    creatorthon_admin_user(request)
    return event_admin_state(ROOT, int(os.getenv("CREATORTHON_EVENT_USER_LIMIT", "50")))


@app.get("/api/creatorthon/admin/videos")
async def creatorthon_admin_videos(request: Request):
    creatorthon_admin_user(request)
    videos = list_participant_videos(ROOT)
    return {"videos": videos, "count": len(videos)}


@app.get("/api/creatorthon/admin/channel-automation")
async def creatorthon_admin_channel_automation(request: Request):
    """Inspect private trend-research runs and approval-gated story drafts."""
    creatorthon_admin_user(request)
    state = CHANNEL_AUTOMATION.state()
    state["available_categories"] = list(CHANNEL_AUTOMATION_CATEGORIES)
    state["youtube_discovery_configured"] = bool(os.getenv("YOUTUBE_DATA_API_KEY", "").strip())
    state["frame_analysis_enabled"] = os.getenv("CHANNEL_FRAME_ANALYSIS_ENABLED", "true").lower() == "true"
    state["youtube_frame_auth_configured"] = youtube_frame_auth_configured()
    state["publishing_mode"] = "approval_required"
    return state


@app.put("/api/creatorthon/admin/channel-automation")
async def creatorthon_admin_channel_automation_settings(request: Request, payload: ChannelAutomationSettingsRequest):
    creatorthon_admin_user(request)
    return CHANNEL_AUTOMATION.update_settings(enabled=payload.enabled, categories=payload.categories or None)


@app.post("/api/creatorthon/admin/channel-automation/run")
async def creatorthon_admin_channel_automation_run(request: Request, payload: ChannelAutomationRunRequest):
    creatorthon_admin_user(request)
    try:
        return CHANNEL_AUTOMATION.start(payload.categories or None)
    except ChannelAutomationError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/creatorthon/admin/channel-automation/analyze-upload")
async def creatorthon_admin_channel_automation_analyze_upload(
    request: Request,
    video: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form("Entertainment"),
    platform: str = Form("Instagram Reels"),
    output_duration: int = Form(20),
    language: str = Form("English"),
):
    """Deep-analyse an organizer-authorized upload without retaining its source media."""
    creatorthon_admin_user(request)
    suffix = Path(video.filename or "source.mp4").suffix.lower()
    allowed = {".mp4", ".mov", ".m4v", ".webm"}
    if suffix not in allowed:
        raise HTTPException(422, "Upload an MP4, MOV, M4V or WebM video.")
    if category not in CHANNEL_AUTOMATION_CATEGORIES:
        raise HTTPException(422, "Select a supported Viralizer category.")
    if platform not in {"Instagram Reels", "YouTube Shorts", "TikTok"}:
        raise HTTPException(422, "Select Instagram Reels, YouTube Shorts or TikTok.")
    if not 10 <= output_duration <= 60:
        raise HTTPException(422, "Output duration must be between 10 and 60 seconds.")
    maximum = max(25, min(1000, int(os.getenv("CHANNEL_UPLOAD_MAX_MB", "300")))) * 1024 * 1024
    upload_dir = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "channel_automation" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(f"{time.time_ns()}:{video.filename}".encode()).hexdigest()[:24]
    destination = upload_dir / f"{token}{suffix}"
    written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await video.read(1024 * 1024):
                written += len(chunk)
                if written > maximum:
                    raise HTTPException(413, f"Video exceeds the {maximum // (1024 * 1024)} MB upload limit.")
                target.write(chunk)
        if written < 1024:
            raise HTTPException(422, "The uploaded video is empty or unreadable.")
        return CHANNEL_AUTOMATION.start_uploaded_video(destination, title=title.strip()[:180], category=category,
            platform=platform, output_duration=output_duration, language=language.strip()[:80] or "English")
    except Exception:
        if destination.is_file():
            destination.unlink(missing_ok=True)
        raise
    finally:
        await video.close()


async def _finish_channel_automation_draft(draft_id: str, project_id: str, job_id: str, narration: str) -> None:
    """Monitor the existing multi-scene generator, then add narration and mandatory Viralizer branding."""
    user_id = "__viralizer_channel_automation__"
    try:
        for _ in range(720):
            await asyncio.sleep(10)
            result = long_video_status(job_id) or {}
            if result.get("status") == "failed":
                raise RuntimeError(str(result.get("error") or "Automated video generation failed."))
            if result.get("status") != "complete":
                continue
            video_url = str(result.get("url") or "")
            match = re.fullmatch(r"/api/finished-video/(viralizer-[a-f0-9]{32}\.mp4)", video_url)
            if not match:
                raise RuntimeError("Automated generation returned an unsupported video path.")
            source_path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / match.group(1)
            logo_path = ROOT / "static" / "viralizer-logo-white.png"
            logo_bytes = logo_path.read_bytes() if logo_path.is_file() else b""
            finished = await finish_video("", narration, "coral", logo_bytes, source_path=source_path)
            finished_url = f"/api/finished-video/{finished.name}"
            update_project(ROOT, user_id, project_id, {"status": "completed", "video_url": finished_url,
                "production": {"provider": "pixverse", "long_video_job_id": job_id, "status": "completed",
                               "approval_required_before_publish": True}})
            CHANNEL_AUTOMATION.update_draft(draft_id, {"status": "video_ready", "project_id": project_id,
                "video_url": finished_url, "generation_job_id": job_id})
            return
        raise RuntimeError("Automated video generation timed out.")
    except Exception as exc:
        update_project(ROOT, user_id, project_id, {"status": "failed", "production": {"status": "failed", "error": str(exc)[:500]}})
        CHANNEL_AUTOMATION.update_draft(draft_id, {"status": "production_failed", "production_error": str(exc)[:500]})


def _start_channel_automation_production(draft: dict[str, Any]) -> dict[str, Any]:
    user_id = "__viralizer_channel_automation__"
    duration = max(10, min(30, int(draft.get("duration") or 20)))
    content = {
        "title": draft.get("title") or "Viralizer original Short", "topic": draft.get("title") or "Original Short",
        "category": draft.get("category") or "Entertainment", "summary": draft.get("why_now") or "",
        "creator_angle": draft.get("originality_angle") or "", "video_idea": draft.get("generation_prompt") or "",
        "story_understanding": {"hook": draft.get("hook") or "", "payoff": draft.get("loop") or ""},
        "visual_story_plan": draft.get("story_beats") or [], "source_research": draft.get("research") or {},
        "unsupported_visuals": ["copied source footage", "copied faces", "copied logos", "copyrighted music"],
    }
    project = create_project(ROOT, user_id, content, {"provider": "pixverse", "status": "processing", "aspect_ratio": "9:16",
        "quality": "720p", "prompt": {"text": draft.get("generation_prompt") or "", "mode": "channel-automation"},
        "narration": {"text": draft.get("narration") or ""}, "configuration": {"approval_required_before_publish": True}})
    job_id = start_long_video(content, duration, "720p", False, {"aspect_ratio": "9:16", "prompt": draft.get("generation_prompt") or ""})
    update_project(ROOT, user_id, project["id"], {"job_id": job_id, "production": {"provider": "pixverse", "long_video_job_id": job_id, "status": "processing"}})
    CHANNEL_AUTOMATION.update_draft(str(draft["id"]), {"status": "producing", "project_id": project["id"], "generation_job_id": job_id})
    asyncio.create_task(_finish_channel_automation_draft(str(draft["id"]), project["id"], job_id, str(draft.get("narration") or "")))
    return {"project_id": project["id"], "generation_job_id": job_id, "status": "producing"}


@app.put("/api/creatorthon/admin/channel-automation/drafts/{draft_id}")
async def creatorthon_admin_channel_automation_review(request: Request, draft_id: str, payload: ChannelAutomationDraftRequest):
    """Approve the original story for production; publishing remains a separate admin action."""
    creatorthon_admin_user(request)
    try:
        draft = CHANNEL_AUTOMATION.set_draft_status(draft_id, payload.status)
        production = _start_channel_automation_production(draft) if payload.status == "approved" else None
        return {"draft": CHANNEL_AUTOMATION.update_draft(draft_id, {"production": production}) if production else draft,
                "production": production}
    except ChannelAutomationError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/creatorthon/admin/channel-automation/drafts/{draft_id}/publish")
async def creatorthon_admin_channel_automation_publish(request: Request, draft_id: str):
    """Publish only an organizer-reviewed, finished and Viralizer-branded automation video."""
    creatorthon_admin_user(request)
    draft = next((item for item in CHANNEL_AUTOMATION.state().get("drafts", []) if item.get("id") == draft_id), None)
    if not draft:
        raise HTTPException(404, "Automation draft not found.")
    if draft.get("status") == "published":
        return {"result": draft.get("published") or {}, "already_published": True}
    if draft.get("status") != "video_ready" or not draft.get("video_url"):
        raise HTTPException(409, "The approved automation video is not ready for publishing.")
    if not publishing_status().get("youtube", {}).get("configured"):
        raise HTTPException(409, "The Viralizer YouTube channel is not connected.")
    match = re.fullmatch(r"/api/finished-video/(viralizer-[a-f0-9]{32}\.mp4)", str(draft.get("video_url") or ""))
    if not match:
        raise HTTPException(422, "Only a completed Viralizer-branded automation video can be published.")
    video_path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / match.group(1)
    if not video_path.is_file() and not await restore_object_file(video_path, f"finished_videos/{match.group(1)}"):
        raise HTTPException(404, "The completed automation video could not be found.")
    caption = "\n\n".join(value for value in (str(draft.get("title") or ""), str(draft.get("caption") or "")) if value)
    hashtags = [str(item).lstrip("#") for item in draft.get("hashtags") or [] if str(item).strip()]
    if MANDATORY_HASHTAG.lstrip("#").casefold() not in {item.casefold() for item in hashtags}:
        hashtags.insert(0, MANDATORY_HASHTAG.lstrip("#"))
    try:
        upload = await publish_all(video_path, str(draft.get("video_url") or ""), caption, hashtags, ["youtube"])
    except (ObjectStoreError, SocialPublishError, YouTubeOAuthError) as exc:
        raise HTTPException(422, str(exc)) from exc
    result = dict((upload.get("results") or {}).get("youtube") or {})
    if result.get("status") != "published":
        raise HTTPException(422, str(result.get("detail") or "YouTube could not publish this automation video."))
    CHANNEL_AUTOMATION.update_draft(draft_id, {"status": "published", "published": result, "published_at": time.time()})
    return {"result": result, "hashtags": hashtags}


@app.post("/api/creatorthon/admin/videos/{project_id}/publish-youtube")
async def creatorthon_admin_publish_youtube(request: Request, project_id: str):
    """Publish a participant's completed video to the central Viralizer channel."""
    creatorthon_admin_user(request)
    summary = next((item for item in list_participant_videos(ROOT) if item.get("id") == project_id), None)
    if not summary:
        raise HTTPException(404, "Participant video not found.")
    user_id = str(summary.get("user_id") or "")
    project = update_project(ROOT, user_id, project_id, {})
    if not project:
        raise HTTPException(404, "Participant project not found.")
    if not publishing_status().get("youtube", {}).get("configured"):
        raise HTTPException(409, "The Viralizer YouTube channel is not connected.")

    production = dict(project.get("production") or {})
    published = dict(production.get("published") or {})
    previous = dict(published.get("youtube_viralizer") or {})
    if previous.get("status") == "published":
        return {"result": {**previous, "already_published": True}, "all_published": True}

    video_url = str(project.get("video_url") or "")
    match = re.fullmatch(r"/api/finished-video/(viralizer-(?:hybrid-)?[a-f0-9]{32}\.mp4)", video_url)
    if not match:
        raise HTTPException(422, "Only a completed, watermarked Creatorthon video can be published.")
    video_path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / match.group(1)
    if not video_path.is_file() and not await restore_object_file(video_path, f"finished_videos/{match.group(1)}"):
        raise HTTPException(404, "The completed video could not be found.")

    topic = dict(project.get("topic") or {})
    title = str(project.get("title") or topic.get("role_focused_title") or topic.get("topic") or "Viralizer video").strip()
    summary_text = str(topic.get("summary") or topic.get("description") or "").strip()
    caption = "\n\n".join(value for value in (title, summary_text) if value)
    hashtags = build_hashtags(topic or {"title": title})
    if MANDATORY_HASHTAG.casefold() not in {tag.casefold() for tag in hashtags}:
        hashtags.insert(0, MANDATORY_HASHTAG)
    try:
        upload = await publish_all(video_path, video_url, caption, hashtags, ["youtube"])
    except (ObjectStoreError, SocialPublishError, YouTubeOAuthError) as exc:
        raise HTTPException(422, str(exc)) from exc
    result = dict((upload.get("results") or {}).get("youtube") or {})
    result.update({
        "channel_title": os.getenv("YOUTUBE_CHANNEL_TITLE", "Viralizer YouTube").strip() or "Viralizer YouTube",
        "account_type": "viralizer", "published_by_admin": True,
    })
    if result.get("status") != "published":
        raise HTTPException(422, str(result.get("detail") or "YouTube could not publish this video."))
    published["youtube_viralizer"] = result
    production["published"] = published
    update_project(ROOT, user_id, project_id, {"status": "published", "production": production})
    return {"result": result, "all_published": True, "hashtags": hashtags}


@app.put("/api/creatorthon/admin/capacity")
async def creatorthon_admin_capacity(request: Request, payload: CreatorthonAdminCapacityRequest):
    admin = creatorthon_admin_user(request)
    return {"capacity": set_event_capacity(ROOT, payload.capacity, str(admin.get("email") or ""))}


@app.put("/api/creatorthon/admin/freeze")
async def creatorthon_admin_freeze(request: Request, payload: CreatorthonAdminFreezeRequest):
    admin = creatorthon_admin_user(request)
    frozen = set_event_frozen(ROOT, payload.frozen, str(admin.get("email") or ""))
    return {"frozen": frozen}


@app.put("/api/creatorthon/admin/allowances")
async def creatorthon_admin_allowances(request: Request, payload: CreatorthonAdminAllowanceRequest):
    admin = creatorthon_admin_user(request)
    emails = [email for email in payload.emails if isinstance(email, str) and 5 <= len(email) <= 254 and "@" in email]
    if not emails:
        raise HTTPException(422, "Select at least one valid admitted user.")
    updated = set_generation_allowance(ROOT, emails, payload.total_allowance, str(admin.get("email") or ""))
    return {"updated": updated, "total_allowance": payload.total_allowance}


@app.post("/api/creatorthon/admin/reset")
async def creatorthon_admin_reset(request: Request):
    admin = creatorthon_admin_user(request)
    return reset_event_roster(ROOT, str(admin.get("email") or ""))


@app.post("/api/creatorthon/admin/admit")
async def creatorthon_admin_admit(request: Request, payload: CreatorthonAdminEmailRequest):
    admin = creatorthon_admin_user(request)
    return grant_event_admission(ROOT, payload.email, str(admin.get("email") or ""))


@app.post("/api/creatorthon/admin/grant-video")
async def creatorthon_admin_grant_video(request: Request, payload: CreatorthonAdminEmailRequest):
    admin = creatorthon_admin_user(request)
    try:
        account = grant_extra_generation(ROOT, payload.email, str(admin.get("email") or ""))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    used = int(account.get("generation_count") or 0)
    allowance = 1 + int(account.get("extra_generation_credits") or 0)
    return {"email": payload.email.strip().lower(), "videos_used": used,
            "total_allowance": allowance, "credits_remaining": max(0, allowance - used)}


@app.delete("/api/creatorthon/admin/users")
async def creatorthon_admin_remove_user(request: Request, payload: CreatorthonAdminEmailRequest):
    admin = creatorthon_admin_user(request)
    try:
        return remove_event_user(ROOT, payload.email, str(admin.get("email") or ""))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/creatorthon/projects")
async def new_creatorthon_project(request: Request, payload: CreatorthonProjectRequest):
    user = creatorthon_user(request)
    if not str(payload.topic.get("topic") or payload.topic.get("title") or "").strip():
        raise HTTPException(422, "Choose a valid topic.")
    values = payload.model_dump(exclude={"topic"}, exclude_defaults=True)
    return _public_project(create_project(ROOT, str(user.get("sub", "")), payload.topic, values))


@app.patch("/api/creatorthon/projects/{project_id}")
async def patch_creatorthon_project(request: Request, project_id: str, payload: CreatorthonProjectUpdateRequest):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    changes = payload.model_dump(exclude_unset=True)
    result = update_project(ROOT, user_id, project_id, changes)
    if not result:
        raise HTTPException(404, "Creatorthon project not found.")
    if changes.get("video_url"):
        existing = [asset for asset in list_assets(ROOT, user_id) if asset.get("project_id") == project_id and asset.get("url") == changes["video_url"]]
        if not existing:
            add_asset(ROOT, user_id, {"project_id": project_id, "kind": "video", "url": changes["video_url"],
                                      "metadata": {"provider": result.get("provider", ""), "status": result.get("status", "")}})
    return _public_project(result)


@app.get("/api/creatorthon/publishing/status")
async def creatorthon_publishing_status(request: Request):
    user = creatorthon_user(request)
    platforms = publishing_status()
    connection = get_youtube_connection(ROOT, str(user.get("sub", "")))
    central_youtube = bool(platforms.get("youtube", {}).get("configured"))
    platforms["youtube_user"] = {
        "configured": bool(connection),
        "label": str((connection or {}).get("channel_title") or "Connect your YouTube channel"),
        "account_type": "user" if connection else "user_required",
    }
    platforms["youtube_viralizer"] = {
        "configured": central_youtube,
        "label": os.getenv("YOUTUBE_CHANNEL_TITLE", "Viralizer YouTube").strip() or "Viralizer YouTube",
        "account_type": "viralizer",
    }
    # Keep the legacy key for older clients while new clients use explicit destinations.
    platforms["youtube"] = platforms["youtube_user"]
    return {"platforms": platforms, "mandatory_hashtag": MANDATORY_HASHTAG}


@app.get("/api/creatorthon/youtube/status")
async def creatorthon_youtube_status(request: Request):
    user = creatorthon_user(request)
    connection = get_youtube_connection(ROOT, str(user.get("sub", "")))
    return {
        "connected": bool(connection),
        "channel_id": str((connection or {}).get("channel_id") or ""),
        "channel_title": str((connection or {}).get("channel_title") or ""),
        "oauth_email": str((connection or {}).get("oauth_email") or ""),
        "central_fallback_configured": bool(publishing_status()["youtube"]["configured"]),
        "central_channel_title": os.getenv("YOUTUBE_CHANNEL_TITLE", "Viralizer YouTube").strip() or "Viralizer YouTube",
    }


@app.post("/api/creatorthon/youtube/disconnect")
async def creatorthon_youtube_disconnect(request: Request):
    user = creatorthon_user(request)
    delete_youtube_connection(ROOT, str(user.get("sub", "")))
    return {"disconnected": True}


@app.post("/api/creatorthon/hashtags")
async def creatorthon_hashtags(request: Request, payload: CreatorthonHashtagRequest):
    user = creatorthon_user(request)
    varied = _creatorthon_user_variation(str(user.get("sub", "")), payload.topic)
    tags = build_hashtags(varied)
    for variation_tag in reversed(varied.get("variation_hashtags") or []):
        if variation_tag and variation_tag.casefold() not in {tag.casefold() for tag in tags}:
            tags.insert(4, variation_tag)
    return {"hashtags": tags[:14], "mandatory_hashtag": MANDATORY_HASHTAG,
            "variation": str(varied.get("variation_label") or "")}


@app.post("/api/creatorthon/publish")
async def publish_creatorthon_video(request: Request, payload: CreatorthonPublishRequest):
    user = creatorthon_user(request)
    project = update_project(ROOT, str(user.get("sub", "")), payload.project_id, {})
    if not project:
        raise HTTPException(404, "Creatorthon project not found.")
    production = dict(project.get("production") or {})
    published = dict(production.get("published") or {})
    requested = {value.lower() for value in payload.platforms}
    youtube_connection = get_youtube_connection(ROOT, str(user.get("sub", "")))
    if "youtube" in requested:
        requested.remove("youtube")
        requested.add("youtube_user" if youtube_connection else "youtube_viralizer")
    if "youtube_user" in requested and not youtube_connection:
        raise HTTPException(409, "Connect your YouTube channel before publishing there.")
    central_youtube_configured = bool(publishing_status().get("youtube", {}).get("configured"))
    if "youtube_viralizer" in requested and not central_youtube_configured:
        raise HTTPException(409, "The Viralizer YouTube channel is not connected.")
    if "youtube_viralizer" in requested and not payload.viralizer_youtube_consent:
        raise HTTPException(422, "Confirm permission to publish this video on the Viralizer YouTube channel.")
    match = re.fullmatch(r"/api/finished-video/(viralizer-(?:hybrid-)?[a-f0-9]{32}\.mp4)", payload.video_url)
    if not match:
        raise HTTPException(422, "Only a completed, watermarked Creatorthon video can be published.")
    video_path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / match.group(1)
    if not video_path.is_file() and not await restore_object_file(video_path, f"finished_videos/{match.group(1)}"):
        raise HTTPException(404, "The completed video could not be found.")
    hashtags = list(dict.fromkeys(value.strip() for value in payload.hashtags if value.strip()))
    if MANDATORY_HASHTAG.lower() not in {value.lower() for value in hashtags}:
        hashtags.insert(0, MANDATORY_HASHTAG)
    publish_video_url = payload.video_url
    results: dict[str, Any] = {}
    try:
        if "instagram" in requested:
            publish_video_url = object_share_url(f"finished_videos/{match.group(1)}", expires_in=3600)
        standard_platforms = sorted(requested & {"instagram", "facebook", "linkedin"})
        if standard_platforms:
            standard = await publish_all(video_path, publish_video_url, payload.caption, hashtags, standard_platforms)
            results.update(standard.get("results") or {})
        if "youtube_user" in requested:
            previous = published.get("youtube_user") or {}
            if previous.get("status") == "published":
                results["youtube_user"] = {**previous, "already_published": True}
            else:
                try:
                    user_refresh_token = decrypt_refresh_token(str(youtube_connection.get("refresh_token_ciphertext") or ""))
                    user_upload = await publish_all(
                        video_path, payload.video_url, payload.caption, hashtags, ["youtube"],
                        youtube_refresh_token=user_refresh_token,
                    )
                    user_result = dict((user_upload.get("results") or {}).get("youtube") or {})
                    user_result.update({
                        "channel_id": youtube_connection.get("channel_id", ""),
                        "channel_title": youtube_connection.get("channel_title", ""),
                        "account_type": "user",
                    })
                    results["youtube_user"] = user_result
                except (SocialPublishError, YouTubeOAuthError) as exc:
                    detail = str(exc)
                    connection_invalid = any(
                        marker in detail.casefold()
                        for marker in ("could not refresh", "reconnect", "could not be decrypted", "invalid_grant")
                    )
                    if connection_invalid:
                        delete_youtube_connection(ROOT, str(user.get("sub", "")))
                    results["youtube_user"] = {
                        "status": "failed", "detail": detail, "account_type": "user",
                        "connection_invalid": connection_invalid,
                    }
        if "youtube_viralizer" in requested:
            previous = published.get("youtube_viralizer") or {}
            if previous.get("status") == "published":
                results["youtube_viralizer"] = {**previous, "already_published": True}
            else:
                try:
                    central_upload = await publish_all(video_path, payload.video_url, payload.caption, hashtags, ["youtube"])
                    central_result = dict((central_upload.get("results") or {}).get("youtube") or {})
                    central_result.update({
                        "channel_title": os.getenv("YOUTUBE_CHANNEL_TITLE", "Viralizer YouTube").strip() or "Viralizer YouTube",
                        "account_type": "viralizer",
                    })
                    results["youtube_viralizer"] = central_result
                except SocialPublishError as exc:
                    results["youtube_viralizer"] = {"status": "failed", "detail": str(exc), "account_type": "viralizer"}
    except (ObjectStoreError, SocialPublishError, YouTubeOAuthError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if not results:
        raise HTTPException(422, "Select at least one configured publishing destination.")
    published.update(results)
    production["published"] = published
    all_published = all(item.get("status") == "published" for item in results.values())
    update_project(
        ROOT, str(user.get("sub", "")), payload.project_id,
        {"status": "published" if all_published else "publish-partial", "production": production},
    )
    response_results = dict(results)
    # V3 and Workspace submit the legacy `youtube` destination. Keep the
    # explicit account-specific records in storage, but return the selected
    # YouTube result under the key the clients requested as well.
    if "youtube_user" in results:
        response_results["youtube"] = results["youtube_user"]
    elif "youtube_viralizer" in results:
        response_results["youtube"] = results["youtube_viralizer"]
    return {"results": response_results, "all_published": all_published, "hashtags": hashtags}


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
    try:
        content = await prepare_article_intelligence(
            request.content,
            request.duration,
            request.aspect_ratio,
            require_openai=not request.creator_concept,
        )
    except Exception as exc:
        raise HTTPException(
            503,
            "OpenAI could not complete the selected topic analysis. No video credits were spent. Please try again.",
        ) from exc
    if not request.creator_concept and not openai_story_analysis_complete(content):
        raise HTTPException(
            503,
            "The selected topic did not receive a validated OpenAI story analysis. No video credits were spent.",
        )
    selected_provider = request.provider
    if selected_provider == "auto":
        routing_text = " ".join(str(content.get(key) or "") for key in ("topic", "category", "video_idea", "creator_angle")).lower()
        presenter_intent = any(word in routing_text for word in ("presenter", "spokesperson", "talking", "host", "explainer", "news anchor"))
        selected_provider = "heygen" if presenter_intent and request.aspect_ratio in {"9:16", "16:9"} and bool(os.getenv("HEYGEN_API_KEY", "").strip()) else "pixverse"
    effective_quality_mode = request.quality_mode or (selected_provider == "pixverse" and not request.allow_standard_fallback)
    if selected_provider == "pixverse" and effective_quality_mode and not (content.get("article_intelligence") or {}).get("approved_for_media_generation"):
        raise HTTPException(
            422,
            "The selected topic did not pass story and storyboard approval. No video credits were spent.",
        )
    production = prepare_production(content, request.duration, request.prompt or "", quality_mode=effective_quality_mode, aspect_ratio=request.aspect_ratio, quality=request.quality, generation_type="text_to_video")
    prompt = production["prompt"]
    if content.get("product_video"):
        prompt = _provider_safe_product_prompt(prompt)
        production["prompt"] = prompt
    if not prompt:
        raise HTTPException(422, "The selected content did not produce a usable video direction.")
    if selected_provider == "hybrid":
        script = request.narration or build_heygen_script(content, request.duration)
        job_id = start_hybrid_video(content, request.duration, request.quality, script, request.avatar_id, request.voice_id, request.background, effective_quality_mode)
        production.update(job_id=job_id, provider="hybrid", status="processing", generation_mode="hybrid", motion_prompt=build_presenter_direction(content, request.duration))
        record_production(production, Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))))
        return {"job_id": job_id, "provider": "hybrid", "status": "processing", "prompt": prompt, "quality_mode": effective_quality_mode, "openai_story_analysis": True, "stage": "Planning presenter and content visuals"}
    if selected_provider == "pixverse" and (request.duration > 15 or effective_quality_mode):
        if selected_provider != "pixverse":
            raise HTTPException(422, "Long multi-clip videos are not available with the selected video engine.")
        job_id = start_long_video(content, request.duration, request.quality, quality_mode=effective_quality_mode, production=production)
        production.update(job_id=job_id, provider="viralizer", status="processing")
        record_production(production, Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))))
        return {"job_id": job_id, "provider": "viralizer", "status": "processing", "prompt": prompt, "multi_clip": True, "quality_mode": effective_quality_mode, "openai_story_analysis": True, "vision_qc_required": True, "stage": "Preparing scenes"}
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
        return {"job_id": job_id, "provider": selected_provider, "status": "processing", "prompt": prompt, "quality_mode": effective_quality_mode, "openai_story_analysis": True, "stage": "Generating video"}
    except VideoProviderError as exc:
        if (
            selected_provider == "pixverse"
            and content.get("product_video")
            and "sensitive information" in str(exc).casefold()
        ):
            retry_prompt = _provider_safe_product_retry_prompt(content, request.duration, request.aspect_ratio)
            try:
                job_id = await generate_with_provider(
                    selected_provider,
                    retry_prompt,
                    content=content,
                    duration=request.duration,
                    quality=request.quality,
                    narration=request.narration or build_narration_script(content, request.duration),
                    avatar_id=request.avatar_id,
                    voice_id=request.voice_id,
                    background=request.background,
                    aspect_ratio=request.aspect_ratio,
                    visual_mode=request.visual_mode,
                    captions=request.captions,
                    style_id=request.heygen_style_id,
                    brand_kit_id=request.brand_kit_id,
                )
                production.update(job_id=job_id, provider=selected_provider, status="processing", prompt=retry_prompt)
                record_production(production, Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))))
                return {"job_id": job_id, "provider": selected_provider, "status": "processing", "prompt": retry_prompt, "quality_mode": effective_quality_mode, "openai_story_analysis": True, "stage": "Generating video with provider-safe direction"}
            except VideoProviderError as retry_exc:
                raise HTTPException(502, str(retry_exc)) from retry_exc
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/creatorthon/concept/generate")
async def generate_creatorthon_concept(request: Request, payload: CreatorthonConceptGenerateRequest):
    """The browser starts one provider job; durable server storage owns every later step."""
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    project = update_project(ROOT, user_id, payload.project_id, {})
    if not project:
        raise HTTPException(404, "Creatorthon project not found.")
    private_prompt, custom_prompt = _creatorthon_generation_prompt(project, payload.prompt)
    stored_prompt = project.get("prompt") if isinstance(project.get("prompt"), dict) else {}
    if payload.custom_prompt_confirmed and stored_prompt.get("mode") == "custom-developed" and not custom_prompt:
        custom_prompt = True
    if not private_prompt:
        raise HTTPException(409, "Prepare this concept before generating the video.")
    if custom_prompt:
        if not payload.custom_prompt_confirmed:
            raise HTTPException(422, "Confirm that you want to use your own video prompt.")
        if not payload.speech_script_reviewed or not payload.hashtags_reviewed:
            raise HTTPException(422, "Review the speech script and hashtags before using a custom prompt.")
        if not _creatorthon_prompt_matches_topic(project.get("topic") or {}, private_prompt) and not payload.topic_mismatch_acknowledged:
            raise HTTPException(422, "This prompt may not match the selected topic. Edit it or confirm the topic mismatch.")
        update_project(ROOT, user_id, payload.project_id, {
            "prompt": {"text": private_prompt, "concept": private_prompt[:180], "mode": "custom"}
        })
    payload.prompt = private_prompt
    payload.content = project.get("topic") or payload.content
    unlimited = _unlimited_creatorthon_user(user)
    if not unlimited:
        reservation = reserve_event_generation(ROOT, user_id, payload.project_id, payload.provider, str(user.get("email") or ""))
        if not reservation.get("allowed"):
            detail = "This Creatorthon account has used all available video credits. Ask an organizer for one more video or open My Workspace to view the existing video."
            if reservation.get("generation_status") == "reserved":
                detail = "A video generation is already starting for this account. Please wait and recover it from My Workspace instead of starting another."
            raise HTTPException(409, detail)
    try:
        started = await generate_video(payload)
    except Exception:
        if not unlimited:
            release_event_generation(ROOT, user_id, payload.project_id)
        raise
    provider = str(started.get("provider") or payload.provider)
    provider_job_id = str(started.get("job_id") or "")
    if not provider_job_id:
        if not unlimited:
            release_event_generation(ROOT, user_id, payload.project_id)
        raise HTTPException(502, "The video provider did not return a job reference. No video credit was spent.")
    if not unlimited:
        accept_event_generation(ROOT, user_id, payload.project_id, provider, provider_job_id)
    try:
        job = enqueue_durable_media_job(
            ROOT, user_id, project_id=payload.project_id, provider=provider,
            provider_job_id=provider_job_id, narration=payload.narration if payload.narration else "",
            voice=payload.voice_id or "coral", official_logo_data=payload.official_logo_data,
            append_outro=not bool(payload.content.get("reference_recreation")),
        )
        update_project(ROOT, user_id, payload.project_id, {
            "job_id": provider_job_id, "provider": provider, "status": "processing",
            "production": {"provider": provider, "provider_job_id": provider_job_id,
                           "media_job_id": job["id"], "status": "processing"},
        })
    except Exception as exc:
        raise HTTPException(503, f"Video was accepted, but Viralizer could not secure its completion job: {type(exc).__name__}: {str(exc)[:240]}") from exc
    return {"job_id": provider_job_id, "provider": provider, "media_job_id": job["id"],
            "status": job["status"], "stage": job["stage"], "durable": True}


PROTOTYPE_VIDEO_USER_ID = "prototype-onboarding-demo"


def _prototype_storyboard_prompt(payload: PrototypeVideoStartRequest) -> str:
    scene_lines = []
    for index, scene in enumerate(payload.scenes, 1):
        text_note = f' On-screen text: "{scene.on_screen_text}".' if scene.on_screen_text else " No on-screen text."
        scene_lines.append(
            f"Scene {index} ({scene.duration_seconds}s) — {scene.title}: {scene.visual} "
            f"Camera: {scene.camera}.{text_note}"
        )
    source = f" Source/reference: {payload.source_description}." if payload.source_description else ""
    return (
        f"Create a conversion-focused {payload.aspect_ratio} {payload.creative_style} video titled "
        f'"{payload.title}" for the {payload.category} category.{source} '
        + " ".join(scene_lines)
        + " Preserve the same people, products, colors, wardrobe and environment across every scene. "
          "Use natural motion, realistic anatomy, physically believable lighting and premium commercial composition. "
          "Do not show or generate any logo, watermark, brand mark, unrelated product, location, claim or text. "
          "Leave clean corner space for branding that will be applied after generation."
    )[:6000]


def _prototype_reference_image_prompt(payload: PrototypeVideoStartRequest, video_prompt: str) -> str:
    """Build one clean hero frame that PixVerse can animate without changing the subject."""
    scene = payload.scenes[0] if payload.scenes else None
    scene_direction = scene.visual if scene else payload.title
    return (
        f"Create one ultra-photorealistic vertical 9:16 cinematic keyframe for a premium short video titled "
        f'"{payload.title}". Category: {payload.category}. Creative style: {payload.creative_style}. '
        f"The exact visible action and subject must be: {scene_direction}. "
        f"Use the literal subject named in the title; do not replace an animal with a person or lifestyle model. "
        f"Show the requested product or food clearly and accurately. Compose a single coherent scene with natural anatomy, "
        f"realistic materials, believable scale, cinematic lighting, shallow depth of field and clean commercial framing. "
        f"No words, captions, logos, borders, collage, split screen or watermark. "
        f"This frame will be animated, so keep limbs, faces, paws, containers and objects unobstructed. "
        f"Approved motion direction for context only: {video_prompt[:1800]}"
    )[:4000]


def _prototype_project_for_request(request_id: str) -> dict[str, Any] | None:
    for project in list_projects(ROOT, PROTOTYPE_VIDEO_USER_ID, limit=100):
        if str((project.get("topic") or {}).get("prototype_request_id") or "") == request_id:
            return project
    return None


def _prototype_video_url(output_url: str) -> str:
    value = str(output_url or "").strip()
    if value.startswith("https://"):
        return value
    match = re.fullmatch(r"/api/finished-video/([A-Za-z0-9._-]+\.mp4)", value)
    if not match:
        return ""
    return object_share_url(f"finished_videos/{match.group(1)}", expires_in=3600)


@app.post("/api/prototype/video/start")
async def start_prototype_video(request: Request, payload: PrototypeVideoStartRequest):
    if os.getenv("PROTOTYPE_GENERATION_ENABLED", "false").strip().casefold() not in {"1", "true", "yes", "on"}:
        raise HTTPException(503, "Prototype video generation is not enabled.")
    request_id = request.headers.get("x-prototype-request-id", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
        raise HTTPException(422, "A valid prototype request id is required.")
    existing = _prototype_project_for_request(request_id)
    if existing:
        production = existing.get("production") or {}
        return {
            "project_id": existing["id"], "media_job_id": production.get("media_job_id", ""),
            "provider_job_id": production.get("provider_job_id", ""), "status": existing.get("status", "processing"),
            "reused": True,
        }
    now = int(time.time())
    day_start = now - (now % 86400)
    # The private prototype intentionally permits fifteen real demos per UTC day.
    # Keep an older Render value from silently lowering the published contract.
    daily_limit = max(15, min(int(os.getenv("PROTOTYPE_DAILY_GENERATION_LIMIT", "15")), 25))
    todays_projects = [
        item for item in list_projects(ROOT, PROTOTYPE_VIDEO_USER_ID, limit=100)
        if int(item.get("created_at") or 0) >= day_start
    ]
    if len(todays_projects) >= daily_limit:
        raise HTTPException(429, "The prototype has reached today's real-video demo limit.")
    prompt = payload.custom_prompt.strip() or _prototype_storyboard_prompt(payload)
    prompt = (
        prompt
        + " Do not generate any logo, watermark or brand mark inside the scene. Branding is added separately after generation."
    )[:6000]
    topic = {
        "title": payload.title, "topic": payload.title, "category": payload.category,
        "video_idea": payload.title, "creator_angle": payload.creative_style,
        "prototype_request_id": request_id, "prototype": True,
    }
    project = create_project(ROOT, PROTOTYPE_VIDEO_USER_ID, topic, {
        "status": "starting", "provider": "pixverse", "aspect_ratio": payload.aspect_ratio, "quality": "720p",
        "prompt": {"text": prompt, "mode": "approved-storyboard"},
        "narration": {"text": payload.narration},
        "configuration": {"storyboard": [scene.model_dump() for scene in payload.scenes], "prototype": True},
    })
    try:
        duration = min(10, max(5, sum(scene.duration_seconds for scene in payload.scenes)))
        reference_prompt = _prototype_reference_image_prompt(payload, prompt)
        reference_bytes = await generate_instagram_image(topic, reference_prompt, purpose="pixverse")
        pixverse = PixVerseClient()
        reference_id = await pixverse.upload_image(
            image_bytes=reference_bytes,
            filename="prototype-reference.png",
            content_type="image/png",
        )
        provider_job_id = str(await pixverse.generate_from_image(
            reference_id,
            prompt,
            duration=duration,
            quality="720p",
            negative_prompt=(
                "unrelated person, lifestyle model, wrong animal, wrong product, duplicate subject, extra limbs, "
                "deformed anatomy, text, captions, watermark, collage, split screen, cartoon"
            ),
            motion_mode="normal",
        ))
        provider = "pixverse"
        if not provider_job_id:
            raise HTTPException(502, "The video provider did not return a job reference.")
        job = enqueue_durable_media_job(
            ROOT, PROTOTYPE_VIDEO_USER_ID, project_id=project["id"], provider=provider,
            provider_job_id=provider_job_id, narration=payload.narration, voice="coral",
            # Preserve the duration approved in the storyboard. The finisher still
            # overlays the mandatory Viralizer logo when no outro is appended.
            append_outro=False,
        )
        update_project(ROOT, PROTOTYPE_VIDEO_USER_ID, project["id"], {
            "job_id": provider_job_id, "provider": provider, "status": "processing",
            "reference_image": {"mode": "openai-generated", "prompt": reference_prompt},
            "production": {"provider": provider, "provider_job_id": provider_job_id,
                           "media_job_id": job["id"], "status": "processing",
                           "generation_mode": "image_to_video"},
        })
    except Exception as exc:
        update_project(ROOT, PROTOTYPE_VIDEO_USER_ID, project["id"], {
            "status": "failed", "production": {"status": "failed", "error": str(exc)[:500]},
        })
        raise
    return {"project_id": project["id"], "media_job_id": job["id"], "provider_job_id": provider_job_id,
            "status": job["status"], "stage": job["stage"], "reused": False}


@app.get("/api/prototype/video/status/{job_id}")
async def prototype_video_status(job_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(404, "Video job not found.")
    job = get_durable_media_job(ROOT, PROTOTYPE_VIDEO_USER_ID, job_id)
    if not job:
        raise HTTPException(404, "Video job not found.")
    return {
        "id": job["id"], "status": job.get("status", ""), "stage": job.get("stage", ""),
        "error": job.get("error", "") if job.get("status") == "failed" else "",
        "video_url": _prototype_video_url(str(job.get("output_url") or "")) if job.get("status") == "completed" else "",
        "updated_at": job.get("updated_at", 0),
    }


@app.post("/api/prototype/video/revision/start")
async def start_prototype_video_revision(request: Request, payload: PrototypeVideoRevisionRequest):
    if os.getenv("PROTOTYPE_GENERATION_ENABLED", "false").strip().casefold() not in {"1", "true", "yes", "on"}:
        raise HTTPException(503, "Prototype video generation is not enabled.")
    request_id = request.headers.get("x-prototype-request-id", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
        raise HTTPException(422, "A valid prototype request id is required.")
    parsed = urlparse(payload.original_video_url)
    allowed_video_host = parsed.hostname == "v3.viralizer.ai" or bool(parsed.hostname and parsed.hostname.endswith(".r2.cloudflarestorage.com"))
    if parsed.scheme != "https" or not allowed_video_host:
        raise HTTPException(422, "The original video must be a completed Viralizer video.")
    project = create_project(ROOT, PROTOTYPE_VIDEO_USER_ID, {
        "title": payload.title,
        "topic": payload.title,
        "category": "Prototype revision",
        "prototype_request_id": request_id,
        "prototype": True,
    }, {
        "status": "starting",
        "provider": "pixverse",
        "aspect_ratio": payload.aspect_ratio,
        "quality": "720p",
        "prompt": {"text": payload.revision_prompt, "mode": "scene-revision"},
        "configuration": {
            "prototype": True,
            "revision": True,
            "scene_index": payload.scene_index,
            "scene_start_seconds": payload.scene_start_seconds,
            "scene_duration_seconds": payload.scene_duration_seconds,
        },
    })
    try:
        with tempfile.TemporaryDirectory(prefix="viralizer-revision-frame-") as folder:
            original = Path(folder) / "original.mp4"
            frame = Path(folder) / "scene-start.jpg"
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                response = await client.get(payload.original_video_url)
            if response.is_error or len(response.content) > 100 * 1024 * 1024:
                raise HTTPException(422, "The original Viralizer video could not be loaded for revision.")
            original.write_bytes(response.content)
            completed = subprocess.run([
                "ffmpeg", "-y", "-ss", f"{payload.scene_start_seconds:.3f}", "-i", str(original),
                "-frames:v", "1", "-q:v", "2", str(frame),
            ], capture_output=True, text=True)
            if completed.returncode or not frame.is_file():
                raise HTTPException(422, "The selected scene frame could not be extracted.")
            pixverse = PixVerseClient()
            image_id = await pixverse.upload_image(
                image_bytes=frame.read_bytes(), filename="scene-start.jpg", content_type="image/jpeg"
            )
        locked_prompt = (
            f"Revise only Scene {payload.scene_index} of an existing video. {payload.revision_prompt.strip()} "
            "Use the supplied first frame as a strict continuity reference. Keep the exact same subject identity, face, "
            "wardrobe, objects, architecture, background, camera height, color grade, lighting direction and visual style. "
            "Do not introduce a new location, background, logo, watermark, text, person or product. End with framing that "
            "can cut naturally back into the unchanged original video."
        )[:6000]
        provider_job_id = str(await pixverse.generate_from_image(
            image_id,
            locked_prompt,
            duration=5,
            quality="720p",
            negative_prompt="new background, new location, different subject, different face, different lighting, logo, watermark, text, extra limbs, duplicate subject",
            motion_mode="normal",
        ))
        job = enqueue_durable_media_job(
            ROOT,
            PROTOTYPE_VIDEO_USER_ID,
            project_id=project["id"],
            provider="pixverse",
            provider_job_id=provider_job_id,
            append_outro=False,
            revision_original_url=payload.original_video_url,
            revision_start=payload.scene_start_seconds,
            revision_duration=payload.scene_duration_seconds,
        )
        update_project(ROOT, PROTOTYPE_VIDEO_USER_ID, project["id"], {
            "job_id": provider_job_id,
            "provider": "pixverse",
            "status": "processing",
            "production": {
                "provider": "pixverse",
                "provider_job_id": provider_job_id,
                "media_job_id": job["id"],
                "status": "processing",
                "generation_mode": "scene_replacement",
            },
        })
    except HTTPException:
        raise
    except (PixVerseError, httpx.HTTPError, OSError) as exc:
        update_project(ROOT, PROTOTYPE_VIDEO_USER_ID, project["id"], {
            "status": "failed", "production": {"status": "failed", "error": str(exc)[:500]},
        })
        raise HTTPException(502, str(exc)) from exc
    return {
        "project_id": project["id"],
        "media_job_id": job["id"],
        "provider_job_id": provider_job_id,
        "status": job["status"],
        "stage": "Regenerating only the selected scene…",
        "revision": True,
    }


@app.post("/api/creatorthon/prepare-prompt")
async def prepare_creatorthon_prompt(request: Request, payload: CreatorthonPrepareRequest):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    payload.content = _creatorthon_user_variation(user_id, payload.content)
    if payload.content.get("prediction_video"):
        prepared = {
            "prompt": _creatorthon_prediction_prompt(payload.content, payload.duration, payload.aspect_ratio),
            "narration": _creatorthon_prediction_narration(payload.content, payload.duration),
            "content": payload.content,
            "article_intelligence": {},
        }
    elif payload.content.get("reference_recreation") and not payload.content.get("commercial_product_present"):
        exact_prompt = str(payload.prompt or payload.content.get("style_direction") or payload.content.get("video_idea") or "").strip()
        if not exact_prompt:
            raise HTTPException(422, "The approved video-recreation prompt is empty.")
        prepared = {
            "prompt": exact_prompt[:6000],
            "narration": str(payload.content.get("approved_narration") or "")[:1200],
            "content": payload.content,
            "article_intelligence": {},
        }
    elif payload.content.get("product_video"):
        prepared = {
            "prompt": _creatorthon_product_prompt(payload.content, payload.duration, payload.aspect_ratio),
            "narration": _creatorthon_product_narration(payload.content, payload.duration),
            "content": payload.content,
            "article_intelligence": {},
        }
    else:
        prepared = await video_prompt(payload)
        prepared["narration"] = _creatorthon_variation_narration(str(prepared.get("narration") or ""), payload.content)
        if prepared.get("heygen_script"):
            prepared["heygen_script"] = _creatorthon_variation_narration(str(prepared.get("heygen_script") or ""), payload.content)
    title = str(payload.content.get("topic") or payload.content.get("title") or "Selected topic").strip()
    angle = str(payload.content.get("variation_label") or payload.content.get("selected_alternate_concept") or "").strip()
    concept = str(payload.prompt or (f"{title} · {angle}" if angle else title)).strip()
    values = {
        "provider": payload.provider,
        "status": "prepared",
        "aspect_ratio": payload.aspect_ratio,
        "quality": payload.quality,
        "prompt": {
            "text": prepared.get("prompt", ""),
            "concept": concept,
            "mode": "custom-developed" if payload.prompt_mode == "custom" else payload.prompt_mode,
        },
        "narration": {"text": prepared.get("narration", ""), "heygen_script": prepared.get("heygen_script", "")},
        "article_intelligence": prepared.get("article_intelligence") or {},
    }
    if payload.project_id:
        project = update_project(ROOT, user_id, payload.project_id, values)
        if not project:
            raise HTTPException(404, "Creatorthon project not found.")
    else:
        project = create_project(ROOT, user_id, payload.content, values)
    return {
        "project_id": project["id"],
        "concept_line": concept[:180],
        "narration": prepared.get("narration", ""),
        "heygen_script": prepared.get("heygen_script", ""),
        "provider": payload.provider,
    }


@app.post("/api/creatorthon/product/analyze")
async def analyze_product_materials(request: Request, instruction: str = Form("Create a premium advertising campaign."), materials: list[UploadFile] = File(...)):
    """Convert product/menu photographs into a factual, editable campaign brief."""
    creatorthon_user(request)
    if not 1 <= len(materials) <= 8:
        raise HTTPException(422, "Upload between one and eight images.")
    image_parts: list[dict[str, Any]] = []
    for upload in materials:
        content_type = (upload.content_type or "").lower()
        if content_type not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
            raise HTTPException(415, "Materials must be JPEG, PNG, or WebP images.")
        raw = await upload.read(15 * 1024 * 1024 + 1)
        if len(raw) > 15 * 1024 * 1024:
            raise HTTPException(413, "Each image must be 15 MiB or smaller.")
        image_parts.append({"type": "input_image", "image_url": f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"})
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "Product-material analysis is not configured.")
    prompt = f"""Analyze these product/menu/brochure images as factual source material. User request: {instruction[:1200]}
Return only JSON: {{"brand":"","industry":"","summary":"","product_identity":{{"name":"","category":"","variant":"","materials":"","colors":"","packaging":"","visible_features":[],"reference_roles":[]}},"facts":[{{"name":"","description":"","price":"","category":""}}],"auto_prompt":"","negative_prompt":"","recommended_audience":"","recommended_goal":"","concepts":[{{"title":"","hook":"","product":"","visual_direction":"","video_prompt":"","negative_prompt":"","narration":"","music_direction":"","cta":"","duration":15,"aspect_ratio":"9:16"}}]}}.
Transcribe only clearly visible names and prices. Never invent products, prices, ingredients, offers, awards or locations. Identify whether each image is primarily product, packaging, menu, logo, person/model, location, or visual inspiration. Produce one immediately usable auto_prompt plus up to six distinct premium ad concepts. The auto_prompt and every video_prompt must explicitly lock the same visible product identity, material, colors, packaging and branding across all shots; specify a three-beat timeline, suitable adult human interaction, environment, camera movement, lighting, sound and final CTA composition. Adapt creative intensity to the requested Accurate, Promotional or Cinematic mode. Accurate stays literal; Promotional adds a conversion arc; Cinematic adds atmosphere and bolder camera language without changing facts. Use photorealistic motion and no generated text. Put defects, unrelated products, identity drift, invented claims/prices and distorted anatomy in negative_prompt. Narration must stay below 32 words."""
    payload = {"model": os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"), "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}, *image_parts]}], "max_output_tokens": 2400}
    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Viralizer could not read the supplied material.") from exc
    text = str(data.get("output_text") or "").strip() or " ".join(str(item.get("text") or "") for output in data.get("output") or [] for item in output.get("content") or [] if item.get("type") == "output_text")
    match = re.search(r"\{.*\}", text, re.S)
    try:
        result = json.loads(match.group(0) if match else text)
    except (json.JSONDecodeError, AttributeError) as exc:
        raise HTTPException(502, "Viralizer could not structure the extracted details. Please retry.") from exc
    if not isinstance(result, dict) or not isinstance(result.get("concepts"), list):
        raise HTTPException(502, "Viralizer returned an incomplete campaign brief. Please retry.")
    result["facts"] = result.get("facts") if isinstance(result.get("facts"), list) else []
    result["concepts"] = [value for value in result["concepts"] if isinstance(value, dict)][:6]
    if not result["concepts"]:
        raise HTTPException(502, "No usable campaign concepts were found in the supplied material.")
    result.update(instruction=instruction[:1200], source_count=len(materials), requires_user_verification=True)
    result["auto_prompt"] = str(result.get("auto_prompt") or result["concepts"][0].get("video_prompt") or result["concepts"][0].get("visual_direction") or "")[:5000]
    result["negative_prompt"] = str(result.get("negative_prompt") or result["concepts"][0].get("negative_prompt") or "")[:1800]
    return result


def _youtube_video_id(value: str) -> str:
    """Return a conservative YouTube video id without accepting arbitrary hosts."""
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().removeprefix("www.")
    candidate = ""
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            candidate = parts[1]
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate or "") else ""


async def _youtube_reference_context(url: str) -> dict[str, str]:
    """Read public metadata and captions when available; never download source footage."""
    video_id = _youtube_video_id(url)
    if not video_id:
        raise HTTPException(422, "Enter a valid public YouTube or YouTube Shorts link.")
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    title = "YouTube reference"
    author = ""
    transcript = ""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Viralizer/3"}) as client:
        try:
            metadata = (await client.get("https://www.youtube.com/oembed", params={"url": canonical, "format": "json"})).json()
            title = str(metadata.get("title") or title)[:300]
            author = str(metadata.get("author_name") or "")[:160]
            thumbnail = str(metadata.get("thumbnail_url") or thumbnail)
        except (httpx.HTTPError, ValueError):
            pass
        try:
            page = (await client.get(canonical)).text
            match = re.search(r'"captionTracks":(\[.*?\])(?:,"audioTracks"|,"translationLanguages")', page)
            if match:
                tracks = json.loads(match.group(1))
                track = next((item for item in tracks if str(item.get("languageCode", "")).startswith("en")), tracks[0])
                caption_xml = (await client.get(str(track.get("baseUrl") or ""))).text
                transcript = " ".join(
                    html.unescape(re.sub(r"<[^>]+>", "", item)).strip()
                    for item in re.findall(r"<text[^>]*>(.*?)</text>", caption_xml, re.S)
                )[:8000]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, json.JSONDecodeError):
            transcript = ""
    return {"video_id": video_id, "url": canonical, "title": title, "author": author, "thumbnail_url": thumbnail, "transcript": transcript}


@app.post("/api/creatorthon/product/analyze-video-link")
async def analyze_product_video_link(request: Request, payload: VideoReferenceAnalyzeRequest):
    """Turn a public YouTube reference into an editable, original short-video campaign."""
    creatorthon_user(request)
    source = await _youtube_reference_context(payload.url)
    sampled_frames, frame_detail = await CHANNEL_AUTOMATION._sample_frames({
        "url": source["url"],
        "title": source["title"],
        "description": source.get("transcript", ""),
        "thumbnail_url": source.get("thumbnail_url", ""),
    })
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "Video-reference analysis is not configured.")
    source_text = "\n".join(filter(None, [
        f"Reference title: {source['title']}",
        f"Publisher: {source['author']}",
        f"Available captions: {source['transcript']}",
        f"User request: {payload.instruction}",
        f"Narration language: {payload.language}",
        f"Output: {payload.aspect_ratio}",
    ]))
    evidence_note = (
        f"You are receiving {len(sampled_frames)} chronological frames sampled across the complete source video. "
        "Treat them as the primary evidence and reconstruct the action progression between them."
        if sampled_frames else
        "The source video could not be sampled. You have only metadata, captions and one thumbnail; mark confidence low and do not invent unseen actions."
    )
    prompt = f"""Analyze this public video reference to understand its exact visible subject, premise, hook, pacing, shot progression, emotional beat, and viewer payoff.
{source_text[:11000]}
Evidence status: {evidence_note}
Return only JSON: {{"brand":"","industry":"","summary":"","reference_archetype":"pet moment|skit|reaction|tutorial|recipe|product ad|other","commercial_product_present":false,"analysis_confidence":0,"accuracy_review":{{"detected_subjects":[""],"core_action":"","camera_and_framing":"","timing_and_pacing":"","payoff":"","must_preserve":[""],"forbidden_substitutions":[""]}},"product_identity":{{"name":"","category":"","variant":"","materials":"","colors":"","packaging":"","visible_features":[],"reference_roles":["video inspiration"]}},"facts":[],"source_analysis":{{"main_subject":"","supporting_subject":"","relationship":"","premise":"","hook":"","pacing":"","visual_language":"","framing":"","emotional_arc":"","scene_progression":[""],"audio_style":"","viewer_payoff":""}},"auto_prompt":"","negative_prompt":"","recommended_audience":"","recommended_goal":"","concepts":[{{"title":"","hook":"","product":"","visual_direction":"","video_prompt":"","negative_prompt":"","narration":"","music_direction":"","cta":"","duration":15,"aspect_ratio":"{payload.aspect_ratio}"}}]}}.
First classify the reference. A person, animal, meal, location, joke, or activity is NOT a commercial product unless a product or service is clearly shown or named. If commercial_product_present is false, create an original story/skit/pet/reaction/tutorial in the same genre; never convert it into a product advertisement, never invent packaging, treats, prices, offers, benefits, or a purchase CTA. Preserve the clearly visible subject class and defining traits shown by the thumbnail and title (for example animal species/breed, coat colour, number of people, setting and intimate versus wide framing). Do not replace a Rottweiler with another dog breed or replace a close owner-and-pet interaction with generic lifestyle footage.
Create up to six distinct, immediately usable concepts. They must be ORIGINAL: do not copy source footage, exact wording, logos, a real person's face, channel identity, copyrighted music, or a shot-for-shot sequence. Preserve the subject identity, premise, emotional mechanism, framing intimacy and high-level storytelling mechanics. Every video_prompt must specify a timed 15-second scene sequence, realistic human/animal actions, camera distance and movement, continuity locks, narration or intentional no-dialogue direction in {payload.language}, sound design, music arc, and a short Viralizer-branded final beat. Do not invent factual claims. No generated paragraph text. Put wrong species/breed, subject replacement, invented products, identity drift, visual glitches, unsafe actions, copied branding, watermarks, distorted anatomy, and generic stock footage in negative_prompt."""
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for index, frame in enumerate(sampled_frames, 1):
        content.append({"type": "input_text", "text": f"Chronological source frame {index} of {len(sampled_frames)}"})
        content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{frame}"})
    if not sampled_frames and source.get("thumbnail_url"):
        content.append({"type": "input_image", "image_url": source["thumbnail_url"]})
    body = {"model": os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"), "input": [{"role": "user", "content": content}], "max_output_tokens": 2800}
    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Viralizer could not analyze this video reference. Confirm that it is public and retry.") from exc
    text = str(data.get("output_text") or "").strip() or " ".join(str(item.get("text") or "") for output in data.get("output") or [] for item in output.get("content") or [] if item.get("type") == "output_text")
    match = re.search(r"\{.*\}", text, re.S)
    try:
        result = json.loads(match.group(0) if match else text)
    except (json.JSONDecodeError, AttributeError) as exc:
        raise HTTPException(502, "Viralizer could not structure the video analysis. Please retry.") from exc
    concepts = [item for item in result.get("concepts", []) if isinstance(item, dict)][:6]
    if not concepts:
        raise HTTPException(502, "No usable recreation concepts were found.")
    result["concepts"] = concepts
    result["facts"] = result.get("facts") if isinstance(result.get("facts"), list) else []
    result["auto_prompt"] = str(result.get("auto_prompt") or concepts[0].get("video_prompt") or "")[:6000]
    result["negative_prompt"] = str(result.get("negative_prompt") or concepts[0].get("negative_prompt") or "")[:1800]
    result.update(
        source=source,
        source_count=1,
        reference_type="youtube",
        requires_user_verification=True,
        evidence={
            "sampled_frames": len(sampled_frames),
            "frame_status": "ready" if sampled_frames else "unavailable",
            "frame_detail": frame_detail,
            "used_thumbnail_fallback": not bool(sampled_frames),
        },
    )
    return result


@app.post("/api/creatorthon/prediction/analyze-references")
async def analyze_prediction_references(request: Request, references: list[UploadFile] = File(...)):
    """Describe supplied event references so the video prompt can retain visible identity cues."""
    creatorthon_user(request)
    if not 1 <= len(references) <= 5:
        raise HTTPException(422, "Upload between one and five reference images.")
    opened: list[Image.Image] = []
    for upload in references:
        raw = await upload.read(12 * 1024 * 1024 + 1)
        if len(raw) > 12 * 1024 * 1024:
            raise HTTPException(413, "Each reference image must be 12 MiB or smaller.")
        try:
            opened.append(Image.open(io.BytesIO(raw)).convert("RGB"))
        except Exception as exc:
            raise HTTPException(415, "References must be readable JPEG, PNG, or WebP images.") from exc
    canvas = Image.new("RGB", (1024, 1024), (18, 12, 24))
    columns, rows = 2, (len(opened) + 1) // 2
    cell_height = 1024 // max(1, rows)
    for index, source in enumerate(opened):
        fitted = ImageOps.fit(source, (512, cell_height), method=Image.Resampling.LANCZOS)
        canvas.paste(fitted, ((index % columns) * 512, (index // columns) * cell_height))
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=88)
    try:
        description = await analyze_reference_image("", output.getvalue(), "image/jpeg")
    except OpenAIImageError as exc:
        raise HTTPException(502, "Viralizer could not inspect the supplied references.") from exc
    return {"reference_description": str(description)[:1600], "count": len(opened)}


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
    timeout_seconds = float(os.getenv("PROMPT_INTELLIGENCE_TIMEOUT_SECONDS", "12"))
    content = await prepare_article_intelligence_safely(
        request.content,
        request.duration,
        request.aspect_ratio,
        timeout_seconds=timeout_seconds,
    )
    content = apply_selected_alternate_direction(content, request.prompt or "")
    try:
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
    except Exception as exc:
        title = " ".join(str(request.content.get("topic") or request.content.get("suggested_title") or "the selected story").split())[:500]
        summary = " ".join(str(request.content.get("summary") or request.content.get("description") or request.content.get("video_idea") or "").split())[:1200]
        aspect = {"9:16": "vertical 9:16", "16:9": "landscape 16:9", "3:4": "portrait 3:4", "1:1": "square 1:1"}.get(request.aspect_ratio, "vertical 9:16")
        prompt = (
            f"Create one uninterrupted {request.duration}-second {aspect} editorial video centered on {title}. "
            f"Visually communicate this verified development: {summary or title}. "
            "Use one clear real-world subject, one achievable physical action, one controlled camera move, "
            "natural cause-and-effect reactions, stable identity and object geometry, and a clean hero ending. "
            "No cuts, flicker, abrupt movement, readable text, captions, watermarks, generated logos, morphing, "
            "duplicated subjects, disappearing objects, or anatomy distortion."
        )
        intelligence = dict(content.get("article_intelligence") or {})
        intelligence.update(
            extraction_state=intelligence.get("extraction_state") or "failed",
            analysis_model="safe-prompt-response-fallback",
            fallback_reason=f"{type(exc).__name__}: {str(exc)[:240]}",
        )
        content["article_intelligence"] = intelligence
        return {
            "prompt": prompt,
            "narration": build_narration_script(request.content, request.duration),
            "heygen_script": "",
            "heygen_direction": "",
            "heygen_plan": {},
            "heygen_request": {},
            "content": content,
            "article_intelligence": intelligence,
            "prompt_fallback": True,
        }

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
        await upload_object_file(output, f"finished_videos/{output.name}", "video/mp4")
    except MediaFinisherError as exc:
        raise HTTPException(502, str(exc)) from exc
    except ObjectStoreError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"url": f"/api/finished-video/{output.name}"}


def _official_creatorthon_logo(payload: CreatorthonFinishRequest) -> bytes | None:
    if not payload.official_logo_data:
        return None
    match = re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\r\n]+)", payload.official_logo_data)
    if not match:
        raise HTTPException(422, "Official logo must be a PNG, JPG, JPEG, or WebP image.")
    try:
        logo = base64.b64decode(match.group(1), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, "Official logo data is invalid.") from exc
    if len(logo) > 10 * 1024 * 1024:
        raise HTTPException(422, "Official logo must be smaller than 10 MB.")
    return logo


async def _finish_creatorthon_job(
    job_id: str,
    payload: CreatorthonFinishRequest,
    logo_bytes: bytes,
    official_logo_bytes: bytes | None,
) -> None:
    job = CREATORTHON_FINISH_JOBS[job_id]
    try:
        job.update(status="processing", stage="Creating narration, branding, and saving your video…")
        output = await finish_video(
            payload.video_url,
            payload.narration,
            payload.voice,
            logo_bytes,
            secondary_logo_bytes=official_logo_bytes,
        )
        job.update(stage="Saving your narrated video to your library…")
        await upload_object_file(output, f"finished_videos/{output.name}", "video/mp4")
        job.update(status="completed", stage="Your narrated video is ready.", url=f"/api/finished-video/{output.name}")
    except (MediaFinisherError, ObjectStoreError) as exc:
        job.update(status="failed", stage="Could not finish your video.", error=str(exc))
    except Exception:
        job.update(status="failed", stage="Could not finish your video.", error="The finished video could not be prepared. Please try saving this completed video again.")


@app.post("/api/creatorthon/finish")
async def finish_creatorthon_video(request: Request, payload: CreatorthonFinishRequest):
    creatorthon_user(request)
    logo_bytes = (ROOT / "static" / "viralizer-original-logo.png").read_bytes()
    official_logo_bytes = _official_creatorthon_logo(payload)
    try:
        output = await finish_video(payload.video_url, payload.narration, payload.voice, logo_bytes, secondary_logo_bytes=official_logo_bytes)
        await upload_object_file(output, f"finished_videos/{output.name}", "video/mp4")
    except MediaFinisherError as exc:
        raise HTTPException(502, str(exc)) from exc
    except ObjectStoreError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"url": f"/api/finished-video/{output.name}"}


@app.post("/api/creatorthon/finish-async")
async def start_creatorthon_finish_job(request: Request, payload: CreatorthonFinishRequest):
    user = creatorthon_user(request)
    user_id = str(user.get("sub", ""))
    project = update_project(ROOT, user_id, payload.project_id, {}) if payload.project_id else None
    production = project.get("production") if isinstance(project, dict) and isinstance(project.get("production"), dict) else {}
    narration_data = project.get("narration") if isinstance(project, dict) and isinstance(project.get("narration"), dict) else {}
    provider = str(payload.provider or production.get("provider") or (project or {}).get("provider") or "").strip()
    provider_job_id = str(payload.provider_job_id or production.get("provider_job_id") or production.get("job_id") or (project or {}).get("job_id") or "").strip()
    raw_video_url = str(payload.video_url or production.get("raw_video_url") or "").strip()
    narration = payload.narration or str(narration_data.get("text") or "")
    voice = payload.voice or str(narration_data.get("voice") or "coral")
    if not raw_video_url and not (provider and provider_job_id):
        raise HTTPException(409, "The completed provider video reference is missing. Reopen the saved project so Viralizer can recover it; no new video will be generated.")
    job = enqueue_durable_media_job(ROOT, user_id, project_id=payload.project_id, provider=provider, provider_job_id=provider_job_id, raw_video_url=raw_video_url, narration=narration, voice=voice, official_logo_data=payload.official_logo_data)
    if project:
        update_project(ROOT, user_id, payload.project_id, {
            "status": "processing",
            "production": {**production, "provider": provider, "provider_job_id": provider_job_id,
                           "raw_video_url": raw_video_url, "media_job_id": job["id"],
                           "finish_job_id": job["id"], "finish_status": "processing"},
        })
    return {"job_id": job["id"], "status": job["status"], "stage": job["stage"], "durable": True}
@app.get("/api/creatorthon/finish-async/{job_id}")
async def creatorthon_finish_job_status(request: Request, job_id: str):
    user = creatorthon_user(request)
    try:
        job = await asyncio.to_thread(get_durable_media_job, ROOT, str(user.get("sub", "")), job_id)
    except Exception:
        return {"id": job_id, "status": "processing", "stage": "Viralizer is reconnecting to secure media storage…", "url": "", "durable": True}
    if job:
        response = {key: value for key, value in job.items() if key not in {"user_id", "payload"}}
        response["url"] = response.get("output_url", "")
        return response
    legacy = CREATORTHON_FINISH_JOBS.get(job_id)
    if not legacy or legacy.get("user_id") != str(user.get("sub", "")):
        raise HTTPException(404, "Video finishing job not found.")
    return {key: value for key, value in legacy.items() if key != "user_id"}
@app.get("/api/finished-video/{filename}")
async def finished_video(request: Request, filename: str):
    if not re.fullmatch(r"viralizer-(?:hybrid-)?[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(404, "Finished video not found.")
    try:
        return RedirectResponse(
            object_share_url(
                f"finished_videos/{filename}",
                expires_in=3600,
                disposition="inline",
                filename=filename,
            ),
            status_code=307,
            headers={"Cache-Control": "private, no-store"},
        )
    except ObjectStoreError:
        pass
    path = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data"))) / "finished_videos" / filename
    if not path.is_file() and not await restore_object_file(path, f"finished_videos/{filename}"):
        raise HTTPException(404, "Finished video not found.")
    return _video_file_response(request, path, filename)

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
