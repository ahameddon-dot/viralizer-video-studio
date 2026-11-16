"""Deterministic, resumable chat onboarding for an unconfirmed brand profile."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from autopilot_brand_analysis import analyze_brand_sources
from autopilot_intelligence import save_brand_profile
from conversation.store import append_message


def _text(message: dict[str, Any]) -> str:
    content = message.get("content") or {}
    return str(content.get("text") or content.get("message") or "").strip()


def _state(messages: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content") or {}
        if content.get("onboarding_stage"):
            return str(content["onboarding_stage"]), dict(content.get("onboarding_data") or {})
    return "start", {}


def _suggestions(items: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"label": label, "prompt": prompt} for label, prompt in items]


def _assistant(root: Path, customer_id: str, conversation_id: str, text: str, stage: str,
               data: dict[str, Any], suggestions: list[dict[str, str]], *, kind: str = "text") -> dict[str, Any]:
    return append_message(root, customer_id, conversation_id, "assistant", {
        "type": kind, "text": text, "provider": "viralizer_onboarding", "model": "deterministic",
        "stage": "onboarding", "intent": "brand_onboarding", "flow_step": stage,
        "onboarding_stage": stage, "onboarding_data": data, "suggestions": suggestions,
    })


def _url(value: str) -> str:
    match = re.search(r"https?://[^\s<>]+", value or "", re.I)
    return match.group(0).rstrip(".,)") if match else ""


def _profile_payload(data: dict[str, Any], confirmed: bool = True) -> dict[str, Any]:
    draft = dict(data.get("draft") or {})
    sources = list(data.get("sources") or [])
    return {
        "customer_type": "creator" if data.get("role") == "creator" else "business",
        "brand_name": str(draft.get("brand_name") or data.get("brand_name") or ""),
        "category": str(draft.get("category") or data.get("category") or ""),
        "logo_url": str(draft.get("logo_url") or next((source.get("logo_url") or source.get("image_url") for source in sources if source.get("logo_url") or source.get("image_url")), "")),
        "website_url": str(data.get("website_url") or ""),
        "social_urls": list(data.get("social_urls") or []),
        "voice": list(draft.get("voice") or []),
        "positioning": str(draft.get("positioning") or data.get("manual_description") or ""),
        "audiences": list(draft.get("audiences") or []),
        "goals": [str(data.get("goal") or "Grow audience")],
        "products_services": list(draft.get("products_services") or []),
        "keywords": list(draft.get("keywords") or []),
        "hashtags": list(draft.get("hashtags") or []),
        "content_themes": list(draft.get("content_themes") or draft.get("areas_of_interest") or []),
        "recent_content": list(draft.get("recent_content") or []),
        "analysis_confidence": str(draft.get("confidence") or "customer_supplied"),
        "visual_style": list(draft.get("visual_style") or []) + list(draft.get("brand_colors") or []),
        "constraints": list(data.get("constraints") or []),
        "confirmed": confirmed,
    }


async def respond_onboarding(root: Path, customer_id: str, conversation_id: str,
                             messages: list[dict[str, Any]], latest_text: str) -> dict[str, Any]:
    """Advance exactly one onboarding decision and persist the complete state in the reply."""
    stage, data = _state(messages)
    clean = " ".join((latest_text or "").split())
    lowered = clean.casefold()

    if stage == "start":
        data = {}
        message = _assistant(root, customer_id, conversation_id,
            "Welcome. I’ll build your Brand DNA before creating content. First, which best describes you?",
            "role", data, _suggestions([
                ("Business owner", "I am a business owner."), ("Content creator", "I am a content creator."),
                ("Agency", "I run an agency."),
            ]))
    elif stage == "role":
        data["role"] = "creator" if "creator" in lowered else "agency" if "agency" in lowered else "business"
        message = _assistant(root, customer_id, conversation_id,
            "What should I analyze first? Public analysis helps me learn your logo, niche, visual style, voice and content patterns. Nothing is connected for publishing yet.",
            "source_choice", data, _suggestions([
                ("Analyze my website", "Analyze my website first."),
                ("Analyze a social profile", "Analyze my public social profile first."),
                ("Skip analysis", "Skip website and social analysis."),
            ]))
    elif stage == "source_choice":
        if "skip" in lowered:
            message = _assistant(root, customer_id, conversation_id,
                "Without a website or public social profile, trend matching and creative recommendations will be less personalized. You can add sources later. Do you want to continue manually?",
                "skip_warning", data, _suggestions([
                    ("Continue manually", "I understand. Continue without source analysis."),
                    ("Add website", "I want to add my website."), ("Add social profile", "I want to add a social profile."),
                ]))
        elif "social" in lowered:
            message = _assistant(root, customer_id, conversation_id,
                "Paste one public Instagram, YouTube, TikTok or LinkedIn profile URL. This analyzes public brand signals; it does not connect the account for posting.",
                "social_url", data, [])
        else:
            message = _assistant(root, customer_id, conversation_id,
                "Paste your main public website URL. I’ll inspect public pages for brand identity, logo candidates, positioning, products, audience and visual signals.",
                "website_url", data, [])
    elif stage == "skip_warning":
        if "website" in lowered:
            message = _assistant(root, customer_id, conversation_id, "Paste your main public website URL.", "website_url", data, [])
        elif "social" in lowered:
            message = _assistant(root, customer_id, conversation_id, "Paste one public social profile URL.", "social_url", data, [])
        else:
            data["source_analysis_skipped"] = True
            message = _assistant(root, customer_id, conversation_id,
                "Briefly describe what you offer, your niche, and the audience you want to reach.", "manual_description", data, [])
    elif stage == "website_url":
        value = _url(clean)
        if not value:
            message = _assistant(root, customer_id, conversation_id, "Please paste a complete public URL beginning with http:// or https://.", "website_url", data, [])
        else:
            data["website_url"] = value
            if data.get("social_urls"):
                result = await analyze_brand_sources(value, list(data.get("social_urls") or []))
                data["draft"], data["sources"] = result.get("draft") or {}, result.get("sources") or []
                append_message(root, customer_id, conversation_id, "tool", {"tool": "analyze_brand_sources", "output": {"status": "completed", "data": result}})
                message = _assistant(root, customer_id, conversation_id,
                    "I analyzed the website and social profile together. Review the Brand DNA below.", "brand_review", data,
                    _suggestions([("Confirm Brand DNA", "I confirm this Brand DNA."), ("Correct description", "I want to correct the brand description.")]), kind="brand_dna")
            else:
                message = _assistant(root, customer_id, conversation_id,
                    "Website saved. Add one public social profile too, or analyze the website alone.", "social_optional", data,
                    _suggestions([("Analyze website only", "Analyze the website now."), ("Skip social profile", "Skip the social profile and analyze now.")]))
    elif stage == "social_url":
        value = _url(clean)
        if not value:
            message = _assistant(root, customer_id, conversation_id, "Please paste a complete public social profile URL.", "social_url", data, [])
        else:
            data["social_urls"] = [value]
            message = _assistant(root, customer_id, conversation_id,
                "Social profile saved. Add a website too, or analyze this profile now.", "website_optional", data,
                _suggestions([("Analyze social profile", "Analyze the social profile now."), ("Add website", "I want to add my website too.")]))
    elif stage == "social_optional":
        value = _url(clean)
        if value:
            data["social_urls"] = [value]
        result = await analyze_brand_sources(str(data.get("website_url") or ""), list(data.get("social_urls") or []))
        data["draft"], data["sources"] = result.get("draft") or {}, result.get("sources") or []
        append_message(root, customer_id, conversation_id, "tool", {"tool": "analyze_brand_sources", "output": {"status": "completed", "data": result}})
        message = _assistant(root, customer_id, conversation_id,
            "I prepared an evidence-based Brand DNA draft. Review the card below. Detected values remain unconfirmed until you approve them.",
            "brand_review", data, _suggestions([
                ("Confirm Brand DNA", "I confirm this Brand DNA."), ("Correct description", "I want to correct the brand description."),
                ("Re-analyze sources", "Re-analyze my public sources."),
            ]), kind="brand_dna")
    elif stage == "website_optional":
        value = _url(clean)
        if not value and "website" in lowered:
            message = _assistant(root, customer_id, conversation_id, "Paste your main public website URL.", "website_url", data, [])
            return {"message": message, "approval_cards": [], "model": "deterministic", "provider": "viralizer_onboarding", "suggestions": []}
        if value:
            data["website_url"] = value
        result = await analyze_brand_sources(str(data.get("website_url") or ""), list(data.get("social_urls") or []))
        data["draft"], data["sources"] = result.get("draft") or {}, result.get("sources") or []
        append_message(root, customer_id, conversation_id, "tool", {"tool": "analyze_brand_sources", "output": {"status": "completed", "data": result}})
        message = _assistant(root, customer_id, conversation_id,
            "I prepared an evidence-based Brand DNA draft. Review the card below and confirm or correct it.", "brand_review", data,
            _suggestions([("Confirm Brand DNA", "I confirm this Brand DNA."), ("Correct description", "I want to correct the brand description.")]), kind="brand_dna")
    elif stage == "manual_description":
        data["manual_description"] = clean[:2000]
        data["draft"] = {"positioning": clean[:500], "confidence": "customer_supplied", "category": "Customer supplied"}
        message = _assistant(root, customer_id, conversation_id,
            "I created a manual Brand DNA draft from your description. Confirm it now; you can add public sources later.", "brand_review", data,
            _suggestions([("Confirm Brand DNA", "I confirm this Brand DNA."), ("Correct description", "I want to correct the brand description.")]), kind="brand_dna")
    elif stage == "brand_review":
        if "correct" in lowered or "edit" in lowered:
            message = _assistant(root, customer_id, conversation_id, "Tell me the corrected brand description, niche and audience in one message.", "brand_correction", data, [])
        elif "re-analy" in lowered:
            message = _assistant(root, customer_id, conversation_id, "Paste the website or social URL you want me to analyze again.", "source_choice", data, [])
        else:
            profile = save_brand_profile(root, customer_id, _profile_payload(data, confirmed=True))
            data["profile_id"], data["profile_version"] = profile["id"], profile["version"]
            message = _assistant(root, customer_id, conversation_id,
                "Your Brand DNA is confirmed. Next, connect publishing accounts with secure authorization—Viralizer never asks for social passwords. Or continue to content discovery now.",
                "complete", data, _suggestions([
                    ("Connect Instagram", "Connect my Instagram publishing account."),
                    ("Connect YouTube", "Connect my YouTube publishing account."),
                    ("Find hot topics", "Find profile-matched live trends and show their real Viral Rank."),
                ]), kind="onboarding_complete")
    elif stage == "brand_correction":
        draft = dict(data.get("draft") or {})
        draft["positioning"] = clean[:500]
        data["draft"] = draft
        message = _assistant(root, customer_id, conversation_id,
            "Updated. Review the corrected Brand DNA and confirm it when it is accurate.", "brand_review", data,
            _suggestions([("Confirm Brand DNA", "I confirm this Brand DNA."), ("Edit again", "I want to correct the brand description.")]), kind="brand_dna")
    else:
        message = _assistant(root, customer_id, conversation_id, "Your onboarding is ready. Confirm the Brand DNA to continue.", "brand_review", data,
            _suggestions([("Confirm Brand DNA", "I confirm this Brand DNA.")]), kind="brand_dna")

    return {"message": message, "approval_cards": [], "model": "deterministic",
            "provider": "viralizer_onboarding", "suggestions": message["content"].get("suggestions") or []}
