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
    "Business": "business OR company earnings OR acquisition OR corporate announcement OR industry",
    "Startups": "startup OR funding round OR venture capital OR founder OR startup launch",
    "Cryptocurrency": "Bitcoin OR Ethereum OR cryptocurrency OR crypto regulation OR blockchain",
    "Creator Economy": "creator economy OR influencers OR YouTube creators OR monetization OR brand partnerships",
    "Social Media": "Instagram OR TikTok OR YouTube OR X platform OR social media trend OR viral challenge",
    "Entertainment": "movies OR streaming OR music OR celebrity OR trailer OR box office",
    "Gaming": "video games OR gaming launch OR PlayStation OR Xbox OR Nintendo OR esports",
    "Sports": "football OR soccer OR basketball OR cricket OR tennis OR Formula 1 OR championship",
    "Fashion": "fashion OR luxury brand OR runway OR designer OR fashion week OR apparel trend",
    "Health": "health OR medicine OR mental health OR wellness OR healthcare OR medical research",
    "Science": "science OR space exploration OR climate research OR biology OR physics OR astronomy",
}


def _clean_title(value: str) -> str:
    title = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+-\s+[^-]{2,50}$", "", title).strip()


def _topic_key(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", value.lower()).strip()


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

    def start(self) -> bool:
        if self.running:
            return False
        self._task = asyncio.create_task(self.run())
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

    async def discover(self) -> list[dict[str, Any]]:
        limit = max(30, min(600, int(os.getenv("DAILY_CANDIDATE_LIMIT", "540"))))
        candidates: dict[str, dict[str, Any]] = {}
        headers = {"User-Agent": "ViralizerDailyTrends/1.0"}
        async with httpx.AsyncClient(headers=headers, timeout=25.0, follow_redirects=True) as client:
            for category, query in CATEGORY_QUERIES.items():
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

    async def run(self) -> None:
        self.running = True
        self.last_error = None
        try:
            self.progress = "Discovering fresh topics from public news sources"
            candidates = await self.discover()
            if not candidates:
                raise RuntimeError("No fresh public-web candidates were discovered.")
            self.progress = f"Ranking {len(candidates)} public trend candidates"
            candidates.sort(key=self._rank_key)
            result_limit = max(1, min(20, int(os.getenv("DAILY_RESULT_LIMIT", "20"))))
            topics = candidates[:result_limit]
            for index, item in enumerate(topics, 1):
                item["rank"] = index
                item["action"] = self._action(item)
                item["viralizer_status"] = "PENDING"
            report = {
                "generated_at": datetime.now().astimezone().isoformat(),
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
