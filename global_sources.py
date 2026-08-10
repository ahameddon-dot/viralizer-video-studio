import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx


SOURCE_QUERIES = {
    "Breaking News": "breaking news",
    "Stock Market": "stocks earnings",
    "AI": "artificial intelligence",
    "Investors / Money": "investing finance",
    "Beauty & Makeup": "beauty skincare makeup",
    "Technology": "technology launch",
    "Business": "business company",
    "Startups": "startup funding",
    "Cryptocurrency": "bitcoin crypto",
    "Creator Economy": "creator economy",
    "Social Media": "social media",
    "Entertainment": "movies music streaming",
    "Gaming": "video games gaming",
    "Sports": "sports championship",
    "Fashion": "fashion luxury",
    "Health": "health medicine",
    "Science": "science space climate",
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
