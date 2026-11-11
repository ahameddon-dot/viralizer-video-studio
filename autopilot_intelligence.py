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


OPPORTUNITY_MODEL_VERSION = "autopilot-opportunity-v3"
CONCEPT_VERSION = "autopilot-concept-v4-distinct-scenes"


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
    competitor_urls = _clean_list(model.competitor_urls, 20)
    inspiration_urls = _clean_list(model.inspiration_urls, 20)
    all_profile_urls = social_urls + competitor_urls + inspiration_urls
    if any(not url.startswith(("http://", "https://")) for url in all_profile_urls):
        raise ValueError("Social, competitor, and inspiration URLs must begin with http:// or https://.")
    profile = {
        "voice": _clean_list(model.voice, 20),
        "positioning": " ".join(model.positioning.split()),
        "audiences": _clean_list(model.audiences, 20),
        "goals": _clean_list(model.goals, 20),
        "products_services": _clean_list(model.products_services, 100),
        "keywords": _clean_list(model.keywords, 100),
        "hashtags": _clean_list(model.hashtags, 100),
        "competitor_urls": competitor_urls,
        "inspiration_urls": inspiration_urls,
        "inspiration_notes": " ".join(model.inspiration_notes.split()),
        "visual_style": _clean_list(model.visual_style, 30),
        "constraints": _clean_list(model.constraints, 50),
        "social_urls": social_urls,
    }
    evidence = []
    if website:
        evidence.append({"field": "website_url", "value": website, "provenance": "observed", "source": website})
    evidence.extend({"field": "social_urls", "value": url, "provenance": "observed", "source": url} for url in social_urls)
    evidence.extend({"field": "competitor_urls", "value": url, "provenance": "customer_supplied", "source": url} for url in competitor_urls)
    evidence.extend({"field": "inspiration_urls", "value": url, "provenance": "customer_supplied", "source": url} for url in inspiration_urls)
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
    goals = _tokens(" ".join(brand.get("profile", {}).get("goals", [])))
    products = _tokens(" ".join(brand.get("profile", {}).get("products_services", [])))
    commercial_overlap = len((goals | products) & topic_tokens)
    explicit_impact = _number(topic.get("business_impact") or topic.get("commercial_relevance"))
    business_impact = round(max(0, min(100, explicit_impact or (35 + commercial_overlap * 15))))
    heat = str(topic.get("discovery_heat") or topic.get("heat") or "").upper().replace("_", " ")
    freshness = {"EXPLODING": 100, "VERY HOT": 90, "HOT": 75, "WATCH": 50}.get(heat, 60)
    feasibility = 85 if topic.get("recommended_format") or topic.get("video_idea") else 70
    return {"viralizer": viral, "viral_rank": int(viral_rank) if viral_rank else None, "viral_data_available": bool(viral_score or viral_rank), "brand_relevance": relevance, "business_impact": business_impact, "freshness": freshness, "production_feasibility": feasibility}


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
        score = round(components["viralizer"] * .30 + components["brand_relevance"] * .25 + components["business_impact"] * .20 + components["freshness"] * .10 + components["production_feasibility"] * .15, 2)
        trend_key = hashlib.sha256(title.casefold().encode("utf-8")).hexdigest()[:32]
        rationale = (
            f"Brand relevance {components['brand_relevance']}/100, business impact {components['business_impact']}/100, freshness {components['freshness']}/100, "
            f"production feasibility {components['production_feasibility']}/100"
            + (f", Viralizer signal {components['viralizer']}/100 from rank #{components['viral_rank']}." if components["viral_data_available"] and components["viral_rank"] else f", Viralizer signal {components['viralizer']}/100." if components["viral_data_available"] else ". Viralizer data is unavailable and was not estimated.")
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
        source_rank = _number(item["source"].get("viral_rank"))
        if source_rank and "viral_rank" not in item["components"]:
            item["components"]["viral_rank"] = int(source_rank)
            item["components"]["viral_data_available"] = True
            if not item["components"].get("viralizer"):
                item["rationale"] = re.sub(
                    r"\. Viralizer data is unavailable and was not estimated\.$",
                    f", Viralizer signal 0/100 from rank #{int(source_rank)}.",
                    item["rationale"],
                )
        result.append(item)
    return result


def archive_other_opportunities(root: Path, customer_id: str, keep_ids: list[str]) -> None:
    """Keep Today limited to the newest refresh without deleting historical evidence."""
    if not keep_ids:
        return
    placeholders = ",".join("?" for _ in keep_ids)
    with _connect(root) as db:
        db.execute(
            f"UPDATE autopilot_opportunities SET status='archived',updated_at=? WHERE customer_id=? AND status IN ('recommended','selected') AND id NOT IN ({placeholders})",
            (int(time.time()), customer_id, *keep_ids),
        )


def _concepts(opportunity: dict[str, Any], brand: dict[str, Any], platform: str, goal: str) -> list[dict[str, Any]]:
    title = opportunity["title"]
    profile = brand.get("profile", {})
    audience = (profile.get("audiences") or ["your audience"])[0]
    tone = ", ".join((profile.get("voice") or ["clear", "credible"])[:2])
    cta_goal = goal.strip() or ((profile.get("goals") or ["invite the audience to respond"])[0])
    def scene(start: int, end: int, purpose: str, narration: str, visual: str, motion: str) -> dict[str, Any]:
        return {"start": start, "end": end, "purpose": purpose, "narration": narration,
                "on_screen_text": narration[:60],
                "keyframe_prompt": f"Vertical 9:16 premium editorial keyframe about {title}. {visual}. Brand tone: {tone}. Clean composition, one clear focal subject, safe text margins, realistic detail, consistent identity and color palette.",
                "negative_prompt": "No generated text, captions, logos, watermarks, distorted hands, duplicate people, invented statistics, or unsupported brand claims.",
                "motion_prompt": f"Animate only from the approved keyframe. {motion}. Preserve identity, product geometry, wardrobe, lighting, background layout, and brand colors. No morphing, cuts, new objects, or generated text.",
                "camera": motion, "transition": "clean motivated cut" if start else "opening frame"}
    return [
        {"name": "Fast Insight", "hook": f"Here is what {title} changes for {audience}.", "narrative": "Lead with the verified development, explain its immediate relevance, and end with one practical implication.", "script": f"{title} is moving quickly. Here is the part that matters for {audience}, what to watch next, and why it deserves attention now.", "cta": cta_goal, "production_mode": "image_to_video", "storyboard": [scene(0,3,"hook",f"Here is what {title} changes.","A striking close editorial view of the central subject at the moment of change","Slow controlled push-in with restrained environmental motion"),scene(3,11,"explain",f"This matters now for {audience}.","A concrete real-world scene showing why the verified development matters to the audience","Gentle lateral track while the subject performs one clear action"),scene(11,15,"action",cta_goal,"A confident outcome frame connecting the insight to the customer's offer without fake interface elements","Subtle pull-back settling into a clean closing composition")]},
        {"name": "Myth vs Reality", "hook": f"The obvious take on {title} misses the real opportunity.", "narrative": "Contrast a common assumption with source-grounded reality, then reveal the brand-relevant opportunity.", "script": f"The headline is only the surface. The useful signal for {audience} is the contrast between the popular assumption and what the evidence actually supports.", "cta": cta_goal, "production_mode": "image_to_video", "storyboard": [scene(0,5,"myth",f"The obvious take on {title} misses the point.","MYTH: a wide, cool-toned composition showing the approved person acting on the common mistaken assumption; make the misconception visually obvious without generated labels","Slow push toward the mistaken action; keep the unresolved result visible"),scene(5,10,"reality",f"The evidence reveals what matters for {audience}.","REALITY: a clearly different side-angle medium composition showing the same person discovering and demonstrating the evidence-grounded reality; change pose, action, lighting, and focal object","Quick motivated lateral reveal into the corrected action; do not repeat the myth framing"),scene(10,15,"takeaway",cta_goal,"TAKEAWAY: a distinct warm hero composition showing the same person applying the correct insight and reaching a credible completed outcome","Gentle pull-back from the result to the confident person, ending with clean CTA space")]},
        {"name": "Before & After", "hook": f"Before {title}, the playbook looked different.", "narrative": "Show the prior situation, the visible transformation, and the improved outcome without unsupported claims.", "script": f"Before this shift, {audience} followed the old pattern. Then the verified conditions changed. Here is the clearer after-state and the practical action it supports.", "cta": cta_goal, "production_mode": "image_to_video", "storyboard": [scene(0,5,"before",f"Before {title}, the playbook looked different.","BEFORE: a wide environmental composition showing the recurring problem in progress; the approved person is visibly struggling with the old process, with restrained cool lighting and clear negative space around the unresolved obstacle","Mostly locked wide shot; the person performs one small frustrated action while the unresolved environment remains unchanged"),scene(5,10,"transformation",f"Now the verified conditions are changing.","TRANSFORMATION: a clearly different medium side-angle composition; the same approved person actively changes the process using the relevant product or method, with directional light and visible cause-and-effect action","Decisive lateral tracking move following the person's hands through one complete transformation action; do not repeat the before pose"),scene(10,15,"after",cta_goal,"AFTER: a clearly different confident hero composition; the same approved person and product occupy the improved finished environment, with warmer light, an unmistakable completed outcome, and clean CTA space","Begin on the completed result, then use a gentle reveal or pull-back to include the confident person and finished environment; do not repeat earlier framing")]},
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
            "SELECT * FROM autopilot_creative_concepts WHERE opportunity_id=? AND customer_id=? AND concept_version=? ORDER BY variant_number",
            (opportunity_id, customer_id, CONCEPT_VERSION),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["content"] = _load(item.pop("content_json"), {})
        result.append(item)
    return result


def get_concept(root: Path, customer_id: str, concept_id: str) -> dict[str, Any] | None:
    with _connect(root) as db:
        row = db.execute("SELECT * FROM autopilot_creative_concepts WHERE id=? AND customer_id=?", (concept_id, customer_id)).fetchone()
    if not row:
        return None
    item = dict(row); item["content"] = _load(item.pop("content_json"), {})
    return item


def record_keyframe(root: Path, customer_id: str, concept_id: str, scene_index: int, metadata: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute("SELECT * FROM autopilot_creative_concepts WHERE id=? AND customer_id=?", (concept_id, customer_id)).fetchone()
        if not row:
            raise ValueError("Creative concept was not found for this customer.")
        content = _load(dict(row)["content_json"], {})
        storyboard = content.get("storyboard") or []
        if scene_index >= len(storyboard):
            raise ValueError("Storyboard scene was not found.")
        keyframes = content.setdefault("keyframes", {})
        versions = keyframes.setdefault(str(scene_index), [])
        version = {**metadata, "version": len(versions) + 1, "created_at": now}
        versions.append(version)
        db.execute("UPDATE autopilot_creative_concepts SET content_json=?,updated_at=? WHERE id=? AND customer_id=?", (_json(content), now, concept_id, customer_id))
    return version


def update_keyframe_animation(root: Path, customer_id: str, concept_id: str, scene_index: int, job: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute("SELECT content_json FROM autopilot_creative_concepts WHERE id=? AND customer_id=?", (concept_id, customer_id)).fetchone()
        if not row:
            raise ValueError("Creative concept was not found for this customer.")
        content = _load(dict(row)["content_json"], {})
        versions = (content.get("keyframes") or {}).get(str(scene_index)) or []
        if not versions:
            raise ValueError("Generate and review the scene keyframe before animation.")
        versions[-1]["animation"] = {**job, "updated_at": now}
        db.execute("UPDATE autopilot_creative_concepts SET content_json=?,updated_at=? WHERE id=? AND customer_id=?", (_json(content), now, concept_id, customer_id))
        return versions[-1]

