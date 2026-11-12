from __future__ import annotations

from typing import Any


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_brand_profile": {"type": "object", "properties": {}, "additionalProperties": False},
    "analyze_brand_sources": {"type": "object", "properties": {"website_url": {"type": "string"}, "social_urls": {"type": "array", "items": {"type": "string"}, "maxItems": 8}}, "additionalProperties": False},
    "discover_topics": {"type": "object", "properties": {"option_keys": {"type": "string", "description": "Comma-separated Viralizer topic source keys"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, "additionalProperties": False},
    "rank_opportunities": {"type": "object", "properties": {"topics": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 25}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["topics"], "additionalProperties": False},
    "create_concepts": {"type": "object", "properties": {"opportunity_id": {"type": "string"}, "platform": {"type": "string", "enum": ["instagram", "youtube", "tiktok", "linkedin"]}, "goal": {"type": "string"}}, "required": ["opportunity_id"], "additionalProperties": False},
    "get_growth_report": {"type": "object", "properties": {}, "additionalProperties": False},
    "generate_storyboard": {"type": "object", "properties": {"concept_id": {"type": "string"}, "direction": {"type": "string"}}, "required": ["concept_id"], "additionalProperties": False},
    "generate_keyframe": {"type": "object", "properties": {"concept_id": {"type": "string"}, "scene_index": {"type": "integer", "minimum": 0, "maximum": 20}, "direction": {"type": "string"}}, "required": ["concept_id", "scene_index"], "additionalProperties": False},
    "animate_scene": {"type": "object", "properties": {"concept_id": {"type": "string"}, "scene_index": {"type": "integer", "minimum": 0, "maximum": 20}}, "required": ["concept_id", "scene_index"], "additionalProperties": False},
    "finalize_video": {"type": "object", "properties": {"concept_id": {"type": "string"}}, "required": ["concept_id"], "additionalProperties": False},
    "prepare_publication": {"type": "object", "properties": {"asset_version_id": {"type": "string"}, "caption": {"type": "string"}, "destination_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["asset_version_id", "caption", "destination_ids"], "additionalProperties": False},
}


TOOL_DESCRIPTIONS = {
    "get_brand_profile": "Read this customer's confirmed or draft Viralizer brand profile.",
    "analyze_brand_sources": "Analyze customer-provided public website and social profile URLs. Returns an unconfirmed draft only.",
    "discover_topics": "Fetch current worldwide hot topics from the configured Viralizer MCP service.",
    "rank_opportunities": "Rank supplied topics against the customer's confirmed brand profile and save the recommendations.",
    "create_concepts": "Create three storyboard concepts for a customer-owned opportunity.",
    "get_growth_report": "Read publication performance with explicit live or simulated provenance.",
    "generate_storyboard": "Request a storyboard generation or revision. This may require confirmation.",
    "generate_keyframe": "Request a provider-generated keyframe. Never run without provider-cost confirmation.",
    "animate_scene": "Request PixVerse image-to-video animation. Never run without provider-cost confirmation.",
    "finalize_video": "Request assembly of completed scene clips into the final review video.",
    "prepare_publication": "Prepare an exact-content publication approval card. This can never approve or publish content.",
}
