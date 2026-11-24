from __future__ import annotations

from typing import Any


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_brand_profile": {"type": "object", "properties": {}, "additionalProperties": False},
    "analyze_brand_sources": {"type": "object", "properties": {"website_url": {"type": "string"}, "social_urls": {"type": "array", "items": {"type": "string"}, "maxItems": 8}}, "additionalProperties": False},
    "discover_topics": {"type": "object", "properties": {
        "option_keys": {"type": "string", "description": "Comma-separated Viralizer topic source keys"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        "category": {"type": "string", "maxLength": 80, "description": "A category explicitly selected by the customer, such as Food, Sports, Technology, Fashion, Travel, Health, Pets, Business, or Entertainment."},
        "scope": {"type": "string", "enum": ["profile", "category", "worldwide_hot"], "description": "profile uses the confirmed niche; category uses the customer's chosen category; worldwide_hot returns the hottest worldwide topics after explicit customer opt-in."}
    }, "additionalProperties": False},
    "rank_opportunities": {"type": "object", "properties": {"topics": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 25}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["topics"], "additionalProperties": False},
    "create_from_idea": {"type": "object", "properties": {
        "idea": {"type": "string", "minLength": 3, "maxLength": 500, "description": "The customer's own video idea, copied without requiring a trend or opportunity ID."},
        "goal": {"type": "string", "maxLength": 300},
        "platform": {"type": "string", "enum": ["instagram", "youtube", "tiktok", "linkedin"]},
        "narration_mode": {"type": "string", "enum": ["ai", "custom", "none"]},
        "narration_text": {"type": "string", "maxLength": 4000},
        "visual_style": {"type": "string", "maxLength": 80},
        "aspect_ratio": {"type": "string", "enum": ["9:16", "16:9", "1:1"]},
        "duration_seconds": {"type": "integer", "minimum": 5, "maximum": 300}},
        "required": ["idea"], "additionalProperties": False},
    "create_concepts": {"type": "object", "properties": {"opportunity_id": {"type": "string"}, "platform": {"type": "string", "enum": ["instagram", "youtube", "tiktok", "linkedin"]}, "goal": {"type": "string"}, "duration_seconds": {"type": "integer", "minimum": 5, "maximum": 300, "description": "Video length. Built from 5-second scenes; rounded up to a multiple of 5."}}, "required": ["opportunity_id"], "additionalProperties": False},
    "get_growth_report": {"type": "object", "properties": {}, "additionalProperties": False},
    "revise_storyboard": {"type": "object", "properties": {
        "concept_id": {"type": "string"},
        "edits": {"type": "array", "maxItems": 60, "items": {"type": "object", "properties": {
            "scene_index": {"type": "integer", "minimum": 0, "maximum": 59, "description": "Zero-based: scene 1 is index 0."},
            "narration": {"type": "string", "description": "New spoken/on-screen line for this scene."},
            "visual": {"type": "string", "description": "What the image should show differently."},
            "motion": {"type": "string", "description": "How the camera/subject should move differently."}},
            "required": ["scene_index"], "additionalProperties": False}},
        "style_direction": {"type": "string", "description": "Whole-video look/tone applied to every scene (e.g. cinematic, funnier, warmer)."},
        "summary": {"type": "string", "description": "One short sentence describing the change."}},
        "required": ["concept_id"], "additionalProperties": False},
    "generate_storyboard": {"type": "object", "properties": {"concept_id": {"type": "string"}, "direction": {"type": "string"}}, "required": ["concept_id"], "additionalProperties": False},
    "generate_keyframe": {"type": "object", "properties": {"concept_id": {"type": "string"}, "scene_index": {"type": "integer", "minimum": 0, "maximum": 59}, "direction": {"type": "string"}}, "required": ["concept_id", "scene_index"], "additionalProperties": False},
    "animate_scene": {"type": "object", "properties": {"concept_id": {"type": "string"}, "scene_index": {"type": "integer", "minimum": 0, "maximum": 20}}, "required": ["concept_id", "scene_index"], "additionalProperties": False},
    "finalize_video": {"type": "object", "properties": {"concept_id": {"type": "string"}}, "required": ["concept_id"], "additionalProperties": False},
    "prepare_publication": {"type": "object", "properties": {"asset_version_id": {"type": "string"}, "title": {"type": "string", "maxLength": 200}, "caption": {"type": "string"}, "destination_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["asset_version_id", "caption", "destination_ids"], "additionalProperties": False},
}


TOOL_DESCRIPTIONS = {
    "get_brand_profile": "Read this customer's confirmed or draft Viralizer brand profile.",
    "analyze_brand_sources": "Analyze customer-provided public website and social profile URLs. Returns an unconfirmed draft only.",
    "discover_topics": "Fetch verified Viralizer V3 trends for the confirmed profile category, a customer-selected category, or explicitly requested hottest worldwide scope.",
    "rank_opportunities": "Rank supplied topics against the customer's confirmed brand profile and save the recommendations.",
    "create_from_idea": "Turn the customer's own idea directly into a saved user-directed opportunity and storyboard. It does not require a live trend or an opportunity ID.",
    "create_concepts": "Create three storyboard concepts for a customer-owned opportunity.",
    "get_growth_report": "Read publication performance with explicit live or simulated provenance.",
    "revise_storyboard": "Edit the storyboard text and image directions for one scene, several scenes, or the whole video (style_direction). Free; never calls an image or video provider. Edited scenes then need a new image.",
    "generate_storyboard": "Request a storyboard generation or revision. This may require confirmation.",
    "generate_keyframe": "Request a provider-generated keyframe. Never run without provider-cost confirmation.",
    "animate_scene": "Request PixVerse image-to-video animation. Never run without provider-cost confirmation.",
    "finalize_video": "Request assembly of completed scene clips into the final review video.",
    "prepare_publication": "Prepare an exact-content publication approval card. This can never approve or publish content.",
}
