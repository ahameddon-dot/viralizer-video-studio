import asyncio
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx


SOURCE_QUERIES = {
    "Breaking News": "breaking news",
    "Stock Market": "stocks earnings",
    "AI": "artificial intelligence",
    "Investors / Money": "investing finance",
    "Beauty & Makeup": "beauty skincare makeup",
    "Technology": "technology launch",
    "Business": "CXO taxes IPO new business ideas business thought leaders",
    "Supply Chain": "supply chain logistics shipping warehouse companies innovation",
    "E-commerce": "ecommerce new product launches growing brands brand complaints online retail",
    "Gen Z": "Gen Z youth culture young consumers",
    "Startups": "startup funding",
    "Cryptocurrency": "bitcoin crypto",
    "Creator Economy": "creators influencers creator commerce social commerce",
    "Social Media": "social media",
    "Entertainment": "movies music streaming",
    "Gaming": "video games gaming",
    "Sports": "sports championship",
    "Fashion": "fashion luxury",
    "Health": "health medicine",
    "Science": "science space climate",
    "Brands in Growth": "stocks up companies winning company growth brands growing",
    "Brands in Trouble": "stocks down CEO fired company investigations company fines",
    "Celebrities Good News": "celebrity good news achievement award charity comeback",
    "Celebrities in Trouble": "celebrity trouble investigation lawsuit controversy scandal",
    "DeepTech": "deeptech hardtech quantum semiconductors advanced materials photonics",
    "Esports": "esports tournament team competitive gaming championship",
    "Movies": "trailers reviews upcoming movies launches TV shows streaming series",
}


async def discover_global_sources() -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(8)
    headers = {"User-Agent": "ViralizerTrendDiscovery/1.0 (+local trend research tool)"}
    async with httpx.AsyncClient(timeout=22, follow_redirects=True, headers=headers) as client:
        async def fetch(category: str, query: str, source: str) -> list[dict[str, Any]]:
            async with semaphore:
                try:
                    if source == "Hacker News":
                        since = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp())
                        response = await client.get("https://hn.algolia.com/api/v1/search_by_date", params={"query": query, "tags": "story", "numericFilters": f"created_at_i>{since}", "hitsPerPage": 20})
                        response.raise_for_status()
                        return [record(item.get("title", ""), category, "Hacker News", item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}", datetime.fromtimestamp(item.get("created_at_i", 0), timezone.utc), max(1, int(item.get("points") or 0))) for item in response.json().get("hits", []) if item.get("title")]
                    response = await client.get("https://api.gdeltproject.org/api/v2/doc/doc", params={"query": query, "mode": "ArtList", "maxrecords": 20, "format": "json", "sort": "HybridRel", "timespan": "2d"})
                    response.raise_for_status()
                    return [record(item.get("title", ""), category, "GDELT", item.get("url", ""), parse_date(item.get("seendate")), 1) for item in response.json().get("articles", []) if item.get("title")]
                except Exception:
                    return []

        tasks = [fetch(category, query, source) for category, query in SOURCE_QUERIES.items() for source in ("Hacker News", "GDELT")]
        groups = await asyncio.gather(*tasks)
    return [item for group in groups for item in group]


async def discover_category_topics(query: str, limit: int = 30) -> list[dict[str, Any]]:
    """Discover current worldwide public-web topics without contacting Viralizer."""
    query = " ".join(str(query).split()[:18]).strip()
    if not query:
        return []
    headers = {"User-Agent": "ViralizerCategoryDiscovery/1.0 (+public trend research tool)"}
    google_editions = (
        ("US", "en-US", "US:en"),
        ("GB", "en-GB", "GB:en"),
        ("IN", "en-IN", "IN:en"),
        ("AU", "en-AU", "AU:en"),
        ("SA", "ar", "SA:ar"),
    )

    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as client:
        async def google_feed(country: str, language: str, edition: str) -> list[dict[str, Any]]:
            try:
                url = f"https://news.google.com/rss/search?q={quote_plus(query + ' when:2d')}&hl={language}&gl={country}&ceid={edition}"
                response = await client.get(url)
                response.raise_for_status()
                root = ElementTree.fromstring(response.content)
                found = []
                for item in root.findall(".//item")[:30]:
                    title = re.sub(r"\s+-\s+[^-]{2,60}$", "", " ".join((item.findtext("title") or "").split())).strip()
                    if len(title) < 8:
                        continue
                    try:
                        published = parsedate_to_datetime(item.findtext("pubDate", ""))
                    except (TypeError, ValueError):
                        published = datetime.now(timezone.utc)
                    found.append(record(title, query, f"Google News {country}", item.findtext("link", ""), published, 1))
                return found
            except Exception:
                return []

        async def gdelt_feed() -> list[dict[str, Any]]:
            try:
                response = await client.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={"query": query, "mode": "ArtList", "maxrecords": 75, "format": "json", "sort": "HybridRel", "timespan": "2d"},
                )
                response.raise_for_status()
                return [
                    record(item.get("title", ""), query, "GDELT Worldwide", item.get("url", ""), parse_date(item.get("seendate")), 1)
                    for item in response.json().get("articles", [])
                    if item.get("title")
                ]
            except Exception:
                return []

        groups = await asyncio.gather(*(google_feed(*edition) for edition in google_editions), gdelt_feed())

    merged: dict[str, dict[str, Any]] = {}
    for item in (entry for group in groups for entry in group):
        key = re.sub(r"[^\w ]", "", item["topic"].lower(), flags=re.UNICODE).strip()
        if not key:
            continue
        existing = merged.get(key)
        if existing:
            existing["mentions"] += 1
            existing["source_urls"] = list(dict.fromkeys(existing["source_urls"] + item["source_urls"]))
            existing["source_platforms"] = list(dict.fromkeys(existing["source_platforms"] + item["source_platforms"]))
            if item["published_at"] > existing["published_at"]:
                existing["published_at"] = item["published_at"]
        else:
            merged[key] = item
    ordered = sorted(merged.values(), key=lambda item: (item["mentions"], item["published_at"]), reverse=True)
    return ordered[:max(1, min(50, limit))]


def parse_date(value: Any) -> datetime:
    text = str(value or "")
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def record(title: str, category: str, source: str, url: str, published: datetime, engagement: int) -> dict[str, Any]:
    return {"topic": " ".join(str(title).split()), "category": category, "published_at": published.isoformat(), "source_urls": [url] if url else [], "mentions": 1, "source_platforms": [source], "source_engagement": {source: engagement}}
