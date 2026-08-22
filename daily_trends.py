import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx

from mcp_outline_client import MCPOutlineError, get_outline_from_mcp
from global_sources import discover_global_sources


ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("APP_DATA_DIR", str(ROOT / "data")))
REPORTS = DATA_ROOT / "daily_trends"
REPORTS.mkdir(parents=True, exist_ok=True)

CATEGORY_QUERIES = {
    "Breaking News": "breaking news OR developing story OR major announcement OR urgent news",
    "Stock Market": "stocks OR earnings OR shares OR market rally OR market selloff OR unusual volume",
    "AI": "artificial intelligence OR AI model OR AI agents OR AI chips OR robotics",
    "Investors / Money": "investing OR investors OR IPO OR venture funding OR acquisition OR personal finance",
    "Beauty & Makeup": "beauty OR makeup OR skincare OR cosmetics OR beauty launch",
    "Technology": "Apple OR Google OR Microsoft OR NVIDIA OR Meta OR Samsung OR technology launch",
    "Business": "CXO OR CEO OR CFO OR business taxes OR IPO OR new business ideas OR business thought leaders OR corporate strategy",
    "Supply Chain": "supply chain OR logistics OR shipping OR freight OR procurement OR warehouse OR logistics companies OR supply chain innovation OR manufacturing disruption",
    "E-commerce": "ecommerce OR e-commerce OR new product launch OR fast growing brand OR brand complaints OR online retail OR marketplace OR Amazon sellers OR Shopify OR digital commerce",
    "Gen Z": "Gen Z OR Generation Z OR youth culture OR young consumers OR Gen Z workplace OR Gen Z trends",
    "Startups": "startup OR funding round OR venture capital OR founder OR startup launch",
    "Cryptocurrency": "Bitcoin OR Ethereum OR cryptocurrency OR crypto regulation OR blockchain",
    "Creator Economy": "creator economy OR creators OR influencers OR creator commerce OR social commerce OR YouTube creators OR monetization OR brand partnerships",
    "Social Media": "Instagram OR TikTok OR YouTube OR X platform OR social media trend OR viral challenge",
    "Entertainment": "movies OR streaming OR music OR celebrity OR trailer OR box office",
    "Gaming": "video games OR gaming launch OR PlayStation OR Xbox OR Nintendo OR esports",
    "Sports": "football OR soccer OR basketball OR cricket OR tennis OR Formula 1 OR championship",
    "Fashion": "fashion OR luxury brand OR runway OR designer OR fashion week OR apparel trend",
    "Health": "health OR medicine OR mental health OR wellness OR healthcare OR medical research",
    "Science": "science OR space exploration OR climate research OR biology OR physics OR astronomy",
    "Brands in Growth": "stock up OR shares surge OR company winning OR company growth OR fastest growing brand OR record revenue OR business expansion",
    "Brands in Trouble": "stock down OR shares plunge OR company in trouble OR CEO fired OR CEO resigns OR company investigation OR company fine OR regulatory penalty OR bankruptcy OR layoffs",
    "Celebrities Good News": "celebrity good news OR celebrity achievement OR celebrity award OR celebrity wedding OR celebrity charity OR celebrity comeback OR positive celebrity news",
    "Celebrities in Trouble": "celebrity in trouble OR celebrity investigation OR celebrity lawsuit OR celebrity arrest OR celebrity controversy OR celebrity scandal",
    "DeepTech": "deep tech OR deeptech OR hard tech OR hardtech OR quantum computing OR advanced materials OR semiconductors OR biotech platform OR photonics OR space technology",
    "Esports": "esports OR e-sports OR esports tournament OR esports team OR competitive gaming OR esports championship OR gaming roster",
    "Movies": "movie trailer OR film review OR upcoming movie OR movie launch OR film premiere OR TV show OR streaming series OR season premiere",
}


def _clean_title(value: str) -> str:
    title = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+-\s+[^-]{2,50}$", "", title).strip()


def _topic_key(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", value.lower()).strip()


def _youtube_topics(title: str, category: str, keyword: str = "") -> tuple[str, list[str]]:
    words = re.findall(r"[\w'’.-]+", _clean_title(title), flags=re.UNICODE)
    primary = " ".join(words[:10]).strip() or title
    alternatives: list[str] = []
    if keyword.strip():
        alternatives.append(" ".join(f"{keyword.strip()} {category} latest update".split()[:10]))
    alternatives.append(" ".join(f"{primary} explained".split()[:11]))
    alternatives.append(" ".join(f"{category} {primary} analysis".split()[:11]))
    return primary, list(dict.fromkeys(item for item in alternatives if item and item.lower() != primary.lower()))[:2]


def _remaining_number(value: Any) -> float | None:
    match = re.search(r"([\d.]+)\s*([KMB]?)", str(value or "").upper())
    if not match:
        return None
    return float(match.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[match.group(2)]


class DailyTrendService:
    def __init__(self) -> None:
        self.running = False
        self.progress = "Idle"
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None

    def status(self) -> dict[str, Any]:
        latest = self.latest_report()
        return {
            "running": self.running,
            "progress": self.progress,
            "last_error": self.last_error,
            "latest_generated_at": latest.get("generated_at") if latest else None,
            "schedule": os.getenv("DAILY_TRENDS_TIME", "07:00"),
            "enabled": os.getenv("DAILY_TRENDS_ENABLED", "true").lower() == "true",
        }

    def latest_report(self) -> dict[str, Any] | None:
        files = sorted(REPORTS.glob("*.json"), reverse=True)
        if not files:
            return None
        try:
            return json.loads(files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def start(self, options: dict[str, str] | None = None) -> bool:
        if self.running:
            return False
        self._task = asyncio.create_task(self.run(options or {}))
        return True

    async def scheduler(self) -> None:
        while True:
            await asyncio.sleep(45)
            if os.getenv("DAILY_TRENDS_ENABLED", "true").lower() != "true" or self.running:
                continue
            now = datetime.now().astimezone()
            scheduled = os.getenv("DAILY_TRENDS_TIME", "07:00")
            try:
                scheduled_time = datetime.strptime(scheduled, "%H:%M").time()
            except ValueError:
                self.last_error = "DAILY_TRENDS_TIME must use HH:MM format."
                continue
            if now.time() < scheduled_time:
                continue
            latest = self.latest_report()
            if not latest or not str(latest.get("generated_at", "")).startswith(now.date().isoformat()):
                self.start()

    async def discover(self, options: dict[str, str] | None = None) -> list[dict[str, Any]]:
        options = options or {}
        selected_category = str(options.get("category") or "ALL").strip()
        keyword = " ".join(str(options.get("keyword") or "").split()[:8])
        description = " ".join(str(options.get("description") or "").split()[:12])
        limit = max(30, min(600, int(os.getenv("DAILY_CANDIDATE_LIMIT", "540"))))
        candidates: dict[str, dict[str, Any]] = {}
        headers = {"User-Agent": "ViralizerDailyTrends/1.0"}
        async with httpx.AsyncClient(headers=headers, timeout=25.0, follow_redirects=True) as client:
            category_queries = CATEGORY_QUERIES.items() if selected_category in ("", "ALL") else [(selected_category, CATEGORY_QUERIES.get(selected_category, selected_category))]
            for category, query in category_queries:
                focus = " ".join(item for item in (keyword, description) if item)
                if focus:
                    query = f"({query}) ({focus})"
                url = (
                    "https://news.google.com/rss/search?q="
                    f"{quote_plus(query + ' when:1d')}&hl=en-US&gl=US&ceid=US:en"
                )
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    root = ElementTree.fromstring(response.content)
                except Exception:
                    continue
                for item in root.findall(".//item")[:30]:
                    title = _clean_title(item.findtext("title", ""))
                    link = item.findtext("link", "")
                    if len(title) < 8:
                        continue
                    key = _topic_key(title)
                    if not key:
                        continue
                    try:
                        published = parsedate_to_datetime(item.findtext("pubDate", ""))
                    except (TypeError, ValueError):
                        published = datetime.now(timezone.utc)
                    record = candidates.setdefault(
                        key,
                        {
                            "topic": title,
                            "category": category,
                            "published_at": published.isoformat(),
                            "source_urls": [],
                            "source_platforms": ["Google News"],
                            "source_engagement": {},
                            "mentions": 0,
                        },
                    )
                    record["mentions"] += 1
                    if link and link not in record["source_urls"]:
                        record["source_urls"].append(link)
        external = await discover_global_sources()
        for item in external:
            item_key = _topic_key(item["topic"])
            existing = candidates.get(item_key)
            if existing is None:
                item_tokens = set(item_key.split())
                existing = next((candidate for candidate in candidates.values() if candidate["category"] == item["category"] and len(item_tokens & set(_topic_key(candidate["topic"]).split())) / max(1, len(item_tokens | set(_topic_key(candidate["topic"]).split()))) >= .72), None)
            if existing:
                existing["mentions"] += 1
                existing["source_urls"] = list(dict.fromkeys(existing["source_urls"] + item["source_urls"]))
                existing["source_platforms"] = list(dict.fromkeys(existing.get("source_platforms", []) + item["source_platforms"]))
                existing.setdefault("source_engagement", {}).update(item.get("source_engagement", {}))
                if not existing.get("image_url") and item.get("image_url"):
                    existing["image_url"] = item["image_url"]
            elif len(item["topic"]) >= 8:
                candidates[item_key] = item
        ordered = sorted(
            candidates.values(),
            key=lambda item: (item["mentions"], item["published_at"]),
            reverse=True,
        )
        for item in ordered:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(item["published_at"])
            item["discovery_heat"] = (
                "EXPLODING" if item["mentions"] >= 3 and age < timedelta(hours=12)
                else "VERY HOT" if item["mentions"] >= 2 or age < timedelta(hours=6)
                else "HOT" if age < timedelta(hours=24)
                else "WATCH"
            )
        return ordered[:limit]

    async def _validate(self, candidate: dict[str, Any], semaphore: asyncio.Semaphore) -> dict[str, Any]:
        topic = candidate["topic"]
        variants = [
            topic,
            re.split(r"\s*[:|]\s*", topic, maxsplit=1)[0],
            re.split(r"\s+[–—-]\s+", topic, maxsplit=1)[0],
            " ".join(topic.split()[:7]),
        ]
        variants = list(dict.fromkeys(value.strip() for value in variants if len(value.strip()) >= 5))[:3]
        outline = None
        errors = []
        async with semaphore:
            for query in variants:
                try:
                    outline = await get_outline_from_mcp(query)
                    if outline:
                        break
                except MCPOutlineError as exc:
                    errors.append(str(exc))
        if not outline:
            return {**candidate, "viralizer_status": "NO DATA", "viralizer_error": errors[-1] if errors else "No Viralizer data"}
        rank_text = str(outline.get("viral_rank", "")).strip()
        try:
            viral_rank = int(rank_text)
        except ValueError:
            viral_rank = None
        return {
            **candidate,
            "validated_topic": outline.get("topic") or query,
            "viralizer_status": "VALID",
            "viralizer": {
                "viral_rank": viral_rank,
                "viral_score": outline.get("viral_score"),
                "resonance": outline.get("resonance"),
                "boost_reach": outline.get("boost_reach"),
                "remaining_reach": outline.get("remaining_reach") or None,
                "competition": outline.get("competition"),
                "total_audience": outline.get("total_audience") or None,
            },
            "best_content_angle": outline.get("creator_angle") or outline.get("video_idea") or "",
            "headline": outline.get("suggested_title") or outline.get("hook") or candidate["topic"],
            "keywords": outline.get("hashtags") or [],
            "platforms": ["YouTube", "Instagram", "TikTok", "X"],
            "trend_catalyst": candidate["topic"],
            "content_ideas": {
                "short_video": outline.get("video_idea") or "",
                "carousel": f"Explain the key developments and implications behind {candidate['topic']}.",
                "youtube": outline.get("suggested_title") or outline.get("hook") or candidate["topic"],
                "linkedin_x": outline.get("creator_angle") or "",
            },
        }

    @staticmethod
    def _rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            {"EXPLODING": 0, "VERY HOT": 1, "HOT": 2, "WATCH": 3}.get(item["discovery_heat"], 4),
            -item.get("mentions", 0),
            item.get("published_at", ""),
        )

    @staticmethod
    def _action(item: dict[str, Any]) -> str:
        return "PENDING VALIDATION"

    async def run(self, options: dict[str, str] | None = None) -> None:
        options = options or {}
        self.running = True
        self.last_error = None
        try:
            self.progress = "Discovering fresh topics from public news sources"
            candidates = await self.discover(options)
            if not candidates:
                raise RuntimeError("No fresh public-web candidates were discovered.")
            self.progress = f"Ranking {len(candidates)} public trend candidates"
            candidates.sort(key=self._rank_key)
            result_limit = max(1, min(20, int(os.getenv("DAILY_RESULT_LIMIT", "20"))))
            topics = candidates[:result_limit]
            for item in candidates:
                youtube_topic, alternates = _youtube_topics(
                    item["topic"], item["category"], str(options.get("keyword") or "")
                )
                item["youtube_search_topic"] = youtube_topic
                item["alternate_topics"] = alternates
            for index, item in enumerate(topics, 1):
                item["rank"] = index
                item["action"] = self._action(item)
                item["viralizer_status"] = "PENDING"
            report = {
                "generated_at": datetime.now().astimezone().isoformat(),
                "discovery_brief": {
                    "category": str(options.get("category") or "ALL"),
                    "keyword": str(options.get("keyword") or ""),
                    "description": str(options.get("description") or ""),
                },
                "candidate_count": len(candidates),
                "validated_count": 0,
                "pending_validation_count": len(topics),
                "top_5": topics[:5],
                "topics": topics,
                "category_topics": {
                    category: [
                        {**item, "category_rank": index}
                        for index, item in enumerate(
                            [candidate for candidate in candidates if candidate["category"] == category][:30], 1
                        )
                    ]
                    for category in CATEGORY_QUERIES
                },
                "category_winners": {
                    category: next((item for item in topics if item["category"] == category), None)
                    for category in CATEGORY_QUERIES
                    if any(item["category"] == category for item in topics)
                },
                "no_data_count": 0,
            }
            path = REPORTS / f"{datetime.now().astimezone().date().isoformat()}.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            self.progress = f"Complete — {len(topics)} opportunities saved"
        except Exception as exc:
            self.last_error = str(exc)
            self.progress = "Daily workflow failed"
        finally:
            self.running = False


daily_trends = DailyTrendService()
