import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx


FEEDS = [
    ("Saudi Arabia", "Saudi Arabia OR Saudi Vision 2030 OR Riyadh OR Jeddah", "en-US", "US", "US:en"),
    ("Saudi Arabia", "Saudi Arabia investment technology sports entertainment", "en-GB", "GB", "GB:en"),
    ("Saudi Arabia", "Saudi Arabia business energy tourism diplomacy", "en-IN", "IN", "IN:en"),
    ("السعودية", "السعودية OR الرياض OR جدة OR رؤية 2030", "ar", "SA", "SA:ar"),
    ("الخليج", "الخليج OR الإمارات OR قطر OR الكويت OR البحرين OR عمان", "ar", "AE", "AE:ar"),
    ("محتوى عربي", "الذكاء الاصطناعي OR التقنية OR الاقتصاد OR الترفيه OR الرياضة", "ar", "EG", "EG:ar"),
    ("MENA", "Middle East OR Gulf business technology culture entertainment", "en-US", "US", "US:en"),
]


def clean(value: str) -> str:
    return re.sub(r"\s+-\s+[^-]{2,60}$", "", re.sub(r"\s+", " ", value).strip()).strip()


def key(value: str) -> str:
    return re.sub(r"[^\w ]", "", value.lower(), flags=re.UNICODE).strip()


async def regional_report(search: str = "") -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "ViralizerRegionalTrends/1.0"}) as client:
        for section, query, language, country, edition in FEEDS:
            url = f"https://news.google.com/rss/search?q={quote_plus(query + ' when:2d')}&hl={language}&gl={country}&ceid={edition}"
            try:
                response = await client.get(url); response.raise_for_status(); root = ElementTree.fromstring(response.content)
            except Exception:
                continue
            for item in root.findall(".//item")[:15]:
                title = clean(item.findtext("title", "")); link = item.findtext("link", "")
                if len(title) < 8 or (search and search.lower() not in title.lower()):
                    continue
                identity = key(title)
                try: published = parsedate_to_datetime(item.findtext("pubDate", "")).isoformat()
                except (TypeError, ValueError): published = datetime.now(timezone.utc).isoformat()
                record = records.setdefault(identity, {"topic": title, "section": section, "published_at": published, "source_urls": [], "global_mentions": 0, "languages": []})
                record["global_mentions"] += 1
                if language.startswith("ar") and "Arabic" not in record["languages"]: record["languages"].append("Arabic")
                if language.startswith("en") and "English" not in record["languages"]: record["languages"].append("English")
                if link and link not in record["source_urls"]: record["source_urls"].append(link)
    topics = sorted(records.values(), key=lambda x: (x["global_mentions"], x["published_at"]), reverse=True)[:60]
    for index, item in enumerate(topics, 1): item["rank"] = index
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(topics), "topics": topics}
