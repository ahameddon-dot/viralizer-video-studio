"""Provider-free Brand, Opportunity, and Creative Director MVP services."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from autopilot_contracts import BrandProfileUpsert, ConceptGenerateRequest, OpportunityRankRequest
from creatorthon_store import _connect


OPPORTUNITY_MODEL_VERSION = "autopilot-opportunity-v1"
CONCEPT_VERSION = "autopilot-concept-v1"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value: Any, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _clean_list(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(" ".join(str(value).split()) for value in values if str(value).strip()))[:limit]


def _public_brand(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["profile"] = _load(item.pop("profile_json"), {})
    item["evidence"] = _load(item.pop("evidence_json"), [])
    return item


def save_brand_profile(root: Path, customer_id: str, request: BrandProfileUpsert | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, BrandProfileUpsert) else BrandProfileUpsert.model_validate(request)
    if not customer_id.strip():
        raise ValueError("customer_id is required")
    website = model.website_url.strip()
    if website and not website.startswith(("http://", "https://")):
        raise ValueError("Website URL must begin with http:// or https://.")
    social_urls = _clean_list(model.social_urls, 20)
    if any(not url.startswith(("http://", "https://")) for url in social_urls):
        raise ValueError("Social account URLs must begin with http:// or https://.")
    profile = {
        "voice": _clean_list(model.voice, 20),
        "positioning": " ".join(model.positioning.split()),
        "audiences": _clean_list(model.audiences, 20),
        "goals": _clean_list(model.goals, 20),
        "products_services": _clean_list(model.products_services, 100),
        "visual_style": _clean_list(model.visual_style, 30),
        "constraints": _clean_list(model.constraints, 50),
        "social_urls": social_urls,
    }
    evidence = []
    if website:
        evidence.append({"field": "website_url", "value": website, "provenance": "observed", "source": website})
    evidence.extend({"field": "social_urls", "value": url, "provenance": "observed", "source": url} for url in social_urls)
    for field, value in profile.items():
        if field != "social_urls" and value:
            evidence.append({"field": field, "value": value, "provenance": "customer_confirmed" if model.confirmed else "customer_supplied", "source": "onboarding"})
    now, status = int(time.time()), "confirmed" if model.confirmed else "draft"
    with _connect(root) as db:
        if getattr(db, "dialect", "sqlite") == "postgres":
            db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"autopilot-brand:{customer_id}",))
        else:
            db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT * FROM autopilot_brand_profiles WHERE customer_id=? AND status IN ('draft','confirmed') ORDER BY version DESC LIMIT 1",
            (customer_id,),
        ).fetchone()
        version = int(dict(current)["version"]) + 1 if current else 1
        if current:
            db.execute(
                "UPDATE autopilot_brand_profiles SET status='archived',updated_at=? WHERE id=? AND customer_id=?",
                (now, dict(current)["id"], customer_id),
            )
        profile_id = uuid.uuid4().hex
        db.execute(
            """INSERT INTO autopilot_brand_profiles
            (id,customer_id,version,customer_type,status,website_url,profile_json,evidence_json,confirmed_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (profile_id, customer_id, version, model.customer_type, status, website, _json(profile), _json(evidence), now if model.confirmed else 0, now, now),
        )
        row = db.execute("SELECT * FROM autopilot_brand_profiles WHERE id=? AND customer_id=?", (profile_id, customer_id)).fetchone()
    return _public_brand(row)


def get_brand_profile(root: Path, customer_id: str) -> dict[str, Any] | None:
    with _connect(root) as db:
        row = db.execute(
            "SELECT * FROM autopilot_brand_profiles WHERE customer_id=? AND status IN ('draft','confirmed') ORDER BY version DESC LIMIT 1",
            (customer_id,),
        ).fetchone()
    return _public_brand(row) if row else None


def _tokens(value: Any) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", str(value).casefold()) if len(word) > 2}


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _opportunity_components(topic: dict[str, Any], brand: dict[str, Any]) -> dict[str, int]:
    viralizer = topic.get("viralizer") if isinstance(topic.get("viralizer"), dict) else {}
    viral_score = _number(topic.get("viral_score") or viralizer.get("viral_score"))
    viral_rank = _number(topic.get("viral_rank") or viralizer.get("viral_rank"))
    viral_value = viral_score if viral_score else 100 - min(100, viral_rank)
    viral = round(max(0, min(100, viral_value))) if (viral_score or viral_rank) else 0
    role_match = _number(topic.get("role_match_index"))
    brand_text = " ".join(str(value) for value in brand.get("profile", {}).values())
    topic_text = " ".join(str(topic.get(key) or "") for key in ("topic", "title", "category", "summary", "description", "creator_angle"))
    brand_tokens, topic_tokens = _tokens(brand_text), _tokens(topic_text)
    overlap = len(brand_tokens & topic_tokens)
    relevance = round(max(role_match / 2, min(100, 35 + overlap * 15)))
    heat = str(topic.get("discovery_heat") or topic.get("heat") or "").upper().replace("_", " ")
    freshness = {"EXPLODING": 100, "VERY HOT": 90, "HOT": 75, "WATCH": 50}.get(heat, 60)
    feasibility = 85 if topic.get("recommended_format") or topic.get("video_idea") else 70
    return {"viralizer": viral, "brand_relevance": relevance, "freshness": freshness, "production_feasibility": feasibility}


def rank_opportunities(root: Path, customer_id: str, request: OpportunityRankRequest | dict[str, Any]) -> list[dict[str, Any]]:
    model = request if isinstance(request, OpportunityRankRequest) else OpportunityRankRequest.model_validate(request)
    brand = get_brand_profile(root, customer_id)
    if not brand or brand["status"] != "confirmed":
        raise ValueError("Confirm the Brand Intelligence Profile before ranking opportunities.")
    ranked = []
    for topic in model.topics:
        title = " ".join(str(topic.get("topic") or topic.get("title") or "").split())[:500]
        if not title:
            continue
        components = _opportunity_components(topic, brand)
        score = round(components["viralizer"] * .35 + components["brand_relevance"] * .30 + components["freshness"] * .20 + components["production_feasibility"] * .15, 2)
        trend_key = hashlib.sha256(title.casefold().encode("utf-8")).hexdigest()[:32]
        rationale = (
            f"Brand relevance {components['brand_relevance']}/100, freshness {components['freshness']}/100, "
            f"production feasibility {components['production_feasibility']}/100"
            + (f", Viralizer signal {components['viralizer']}/100." if components["viralizer"] else ". Viralizer data is unavailable and was not estimated.")
        )
        ranked.append({"trend_key": trend_key, "title": title, "category": str(topic.get("category") or "")[:120], "score": score, "components": components, "rationale": rationale, "source": topic})
    ranked.sort(key=lambda item: (-item["score"], item["title"].casefold()))
    ranked = ranked[: model.limit]
    now = int(time.time())
    with _connect(root) as db:
        for item in ranked:
            opportunity_id = uuid.uuid4().hex
            row = db.execute(
                """INSERT INTO autopilot_opportunities
                (id,customer_id,brand_profile_id,trend_key,title,category,model_version,score,components_json,rationale,source_json,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,'recommended',?,?)
                ON CONFLICT(customer_id,trend_key,model_version) DO UPDATE SET
                brand_profile_id=excluded.brand_profile_id,title=excluded.title,category=excluded.category,score=excluded.score,
                components_json=excluded.components_json,rationale=excluded.rationale,source_json=excluded.source_json,updated_at=excluded.updated_at
                RETURNING *""",
                (opportunity_id, customer_id, brand["id"], item["trend_key"], item["title"], item["category"], OPPORTUNITY_MODEL_VERSION, f"{item['score']:.2f}", _json(item["components"]), item["rationale"], _json(item["source"]), now, now),
            ).fetchone()
            item["id"] = dict(row)["id"]
            item["model_version"] = OPPORTUNITY_MODEL_VERSION
    return ranked


def list_opportunities(root: Path, customer_id: str, limit: int = 5) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM autopilot_opportunities WHERE customer_id=? AND status IN ('recommended','selected') ORDER BY CAST(score AS DECIMAL) DESC,updated_at DESC LIMIT ?",
            (customer_id, max(1, min(50, int(limit)))),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["score"] = float(item["score"])
        item["components"] = _load(item.pop("components_json"), {})
        item["source"] = _load(item.pop("source_json"), {})
        result.append(item)
    return result


def _concepts(opportunity: dict[str, Any], brand: dict[str, Any], platform: str, goal: str) -> list[dict[str, Any]]:
    title = opportunity["title"]
    profile = brand.get("profile", {})
    audience = (profile.get("audiences") or ["your audience"])[0]
    tone = ", ".join((profile.get("voice") or ["clear", "credible"])[:2])
    cta_goal = goal.strip() or ((profile.get("goals") or ["invite the audience to respond"])[0])
    return [
        {"name": "Fast Insight", "hook": f"Here is what {title} changes for {audience}.", "narrative": "Lead with the verified development, explain its immediate relevance, and end with one practical implication.", "script": f"{title} is moving quickly. Here is the part that matters for {audience}, what to watch next, and why it deserves attention now.", "cta": cta_goal, "storyboard": [{"start": 0, "end": 3, "purpose": "hook"}, {"start": 3, "end": 11, "purpose": "explain"}, {"start": 11, "end": 15, "purpose": "action"}]},
        {"name": "Myth vs Reality", "hook": f"The obvious take on {title} misses the real opportunity.", "narrative": "Contrast a common assumption with source-grounded reality, then reveal the brand-relevant opportunity.", "script": f"The headline is only the surface. The useful signal for {audience} is the contrast between the popular assumption and what the evidence actually supports.", "cta": cta_goal, "storyboard": [{"start": 0, "end": 4, "purpose": "assumption"}, {"start": 4, "end": 11, "purpose": "reveal"}, {"start": 11, "end": 15, "purpose": "action"}]},
        {"name": "Before and Next", "hook": f"Before {title}, the playbook looked different.", "narrative": "Show the prior situation, the current shift, and the next action without making unsupported predictions.", "script": f"Before this shift, {audience} followed the old pattern. Now the conditions are changing. The next sensible move is to respond to the verified signal, not speculate beyond it.", "cta": cta_goal, "storyboard": [{"start": 0, "end": 4, "purpose": "before"}, {"start": 4, "end": 11, "purpose": "change"}, {"start": 11, "end": 15, "purpose": "next"}]},
    ]


def generate_concepts(root: Path, customer_id: str, request: ConceptGenerateRequest | dict[str, Any]) -> list[dict[str, Any]]:
    model = request if isinstance(request, ConceptGenerateRequest) else ConceptGenerateRequest.model_validate(request)
    brand = get_brand_profile(root, customer_id)
    if not brand or brand["status"] != "confirmed":
        raise ValueError("Confirm the Brand Intelligence Profile before generating concepts.")
    with _connect(root) as db:
        row = db.execute("SELECT * FROM autopilot_opportunities WHERE id=? AND customer_id=?", (model.opportunity_id, customer_id)).fetchone()
        if not row:
            raise ValueError("Opportunity was not found for this customer.")
        opportunity = dict(row)
        concepts = _concepts(opportunity, brand, model.platform, model.goal)
        now = int(time.time())
        saved = []
        for index, concept in enumerate(concepts, 1):
            concept.update({"platform": model.platform, "duration_seconds": 15, "brand_tone": brand["profile"].get("voice", [])})
            concept_id = uuid.uuid4().hex
            stored = db.execute(
                """INSERT INTO autopilot_creative_concepts
                (id,customer_id,opportunity_id,variant_number,concept_version,name,content_json,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,'proposed',?,?)
                ON CONFLICT(opportunity_id,variant_number,concept_version) DO UPDATE SET
                name=excluded.name,content_json=excluded.content_json,updated_at=excluded.updated_at RETURNING *""",
                (concept_id, customer_id, model.opportunity_id, index, CONCEPT_VERSION, concept["name"], _json(concept), now, now),
            ).fetchone()
            item = dict(stored)
            item["content"] = _load(item.pop("content_json"), {})
            saved.append(item)
        db.execute("UPDATE autopilot_opportunities SET status='selected',updated_at=? WHERE id=? AND customer_id=?", (now, model.opportunity_id, customer_id))
    return saved


def list_concepts(root: Path, customer_id: str, opportunity_id: str) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM autopilot_creative_concepts WHERE opportunity_id=? AND customer_id=? ORDER BY variant_number",
            (opportunity_id, customer_id),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["content"] = _load(item.pop("content_json"), {})
        result.append(item)
    return result

