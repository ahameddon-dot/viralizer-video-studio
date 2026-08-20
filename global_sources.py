import asyncio
import html
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


_ENTITY_NOISE = {
    "a", "an", "the", "new", "latest", "breaking", "report", "reports", "reported",
    "attorney", "general", "judge", "court", "federal", "government", "users", "user",
    "security", "critical", "dangerous", "major", "million", "billion", "says", "said",
    "secures", "faces", "facing", "misleading", "enabling", "fake", "scam", "over", "after",
    "from", "with", "for", "and", "or",
}

_POSITIVE_REPUTATION_SIGNALS = (
    "award", "wins", "winner", "growth", "growing", "record profit", "profit rises",
    "partnership", "launches", "innovation", "milestone", "comeback", "praise",
    "positive review", "expands", "funding", "breakthrough", "approved", "success",
)
_NEGATIVE_REPUTATION_SIGNALS = (
    "lawsuit", "sued", "investigation", "fine", "penalty", "ban", "backlash",
    "controversy", "scandal", "fraud", "scam", "data breach", "security flaw",
    "outage", "complaint", "recall", "layoff", "decline", "loss", "crisis",
    "fired", "resigns", "protest", "boycott", "warning", "accused",
)
_MIXED_REPUTATION_SIGNALS = ("debate", "divides", "mixed reviews", "pros and cons", "questions", "uncertain")


def _reputation_label(title: str, summary: str = "") -> tuple[str, list[str]]:
    """Return an explainable editorial signal label, not a factual verdict."""
    text = f"{title} {summary}".lower()
    positive = [signal for signal in _POSITIVE_REPUTATION_SIGNALS if signal in text]
    negative = [signal for signal in _NEGATIVE_REPUTATION_SIGNALS if signal in text]
    mixed = [signal for signal in _MIXED_REPUTATION_SIGNALS if signal in text]
    if mixed or (positive and negative):
        return "Mixed / debate", list(dict.fromkeys((mixed + positive + negative)[:4]))
    if negative:
        return "Bad news", negative[:4]
    if positive:
        return "Good news", positive[:4]
    return "Neutral", ["No strong positive or negative wording detected"]


def _youtube_search_terms(title: str) -> tuple[str, list[str]]:
    """Create an entity-led YouTube query of no more than five words."""
    clean = " ".join(str(title).split())
    lower = clean.lower()
    issue = "latest update"
    for needles, label in (
        (("data breach", "data leak", "exposed", "leaking user data"), "data leak"),
        (("vulnerabil", "security flaw", "security bug", "hijack"), "security flaw"),
        (("locked out", "locks out", "review freeze", "account ban"), "account lockout"),
        (("fake", "scam", "fraud", "stolen"), "scam controversy"),
        (("lawsuit", "sued", "sues", "class action"), "lawsuit"),
        (("fine", "penalt", "regulatory action", "investigation"), "regulatory action"),
        (("outage", "offline", "went down", "service disruption"), "outage"),
        (("backlash", "controvers", "criticism"), "controversy"),
        (("complaint", "bad review", "subscription charge", "pricing"), "complaints"),
    ):
        if any(needle in lower for needle in needles):
            issue = label
            break

    quoted = re.findall(r'"([^"“”]{2,45})"|“([^“”]{2,45})”|(?<!\w)\'([^\']{2,45})\'', clean)
    quoted = [next((part for part in match if part), "") for match in quoted]
    candidates: list[str] = [value for value in quoted if len(value.split()) <= 3]
    proper_runs = re.findall(r"\b(?:[A-Z][A-Za-z0-9.+&-]*)(?:\s+(?:[A-Z][A-Za-z0-9.+&-]*|to)){0,3}\b", clean)
    candidates.extend(proper_runs)
    app_candidates = [value for value in candidates if any(word.lower() in {"app", "wallet", "chat", "pay", "zoom", "whatsapp"} for word in value.split())]
    ordered = quoted + app_candidates + candidates
    entity = ""
    for value in ordered:
        words = [word for word in value.split() if word.lower() not in _ENTITY_NOISE]
        candidate = " ".join(words[:3]).strip(" -:,.')(")
        if candidate and not candidate.isdigit() and len(candidate) > 1:
            entity = candidate
            break
    if not entity:
        words = [word.strip(" -:,.')(") for word in clean.split() if word.lower().strip(" -:,.')(") not in _ENTITY_NOISE]
        entity = " ".join(filter(None, words[:3])) or "App"

    max_entity_words = max(1, 5 - len(issue.split()))
    entity = " ".join(entity.split()[:max_entity_words])
    primary = " ".join(f"{entity} {issue}".split()[:5])
    alternate_issue = "explained" if issue != "latest update" else "news update"
    alternate = " ".join(f"{entity} {alternate_issue}".split()[:5])
    return primary, [alternate] if alternate.lower() != primary.lower() else []


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


def build_category_discovery_queries(
    category: str, keyword: str = "", description: str = "", lens: str = "", reputation: str = ""
) -> list[str]:
    """Expand category and reputation selections into useful public-news searches."""
    raw_selected = keyword or category
    # Grouped super-category searches contain quoted OR terms. Preserve the
    # complete batch so every category reaches the public-news providers.
    selected = " ".join(raw_selected.split()[:40] if " OR " in raw_selected else raw_selected.split()[:8])
    if category.strip().lower() in {"app", "apps", "applications"} and not keyword.strip():
        selected = '(app OR "mobile app" OR software)'
    elif " " in selected and not any(mark in selected for mark in ('"', '(', ')')):
        selected = f'"{selected}"'
    context = " ".join(description.split()[:10])
    if not context and lens and lens.lower() != "everything":
        context = " ".join(lens.split()[:4])
    context_suffix = f' "{context}"' if context else ""
    reputation_key = reputation.strip().lower()
    if reputation_key in {"bad reputation", "negative", "criticism", "backlash", "product complaints", "controversy", "reputation falling", "crisis risk"}:
        signals = (
            '(complaints OR backlash OR controversy OR criticism OR "bad reviews")',
            '(lawsuit OR investigation OR fine OR ban OR regulation)',
            '("data breach" OR privacy OR "security flaw" OR scam OR fraud OR outage)',
        )
    elif reputation_key in {"good reputation", "positive", "praise", "brand advocacy", "product satisfaction", "reputation rising"}:
        signals = (
            '(praise OR award OR achievement OR "positive reviews")',
            '(growth OR innovation OR launch OR partnership)',
            '(customer satisfaction OR comeback OR milestone)',
        )
    elif reputation_key == "mixed":
        signals = ('(praise OR criticism OR debate OR controversy)',)
    else:
        signals = ('(news OR launch OR review OR trend)',)
    return [f"{selected} {signal}{context_suffix}".strip() for signal in signals]


async def discover_category_topics(query: str | list[str], limit: int = 30) -> list[dict[str, Any]]:
    """Discover current worldwide public-web topics without contacting Viralizer."""
    queries = [query] if isinstance(query, str) else query
    queries = [" ".join(str(value).split()[:45]).strip() for value in queries if str(value).strip()]
    if not queries:
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
        async def google_feed(search_query: str, country: str, language: str, edition: str) -> list[dict[str, Any]]:
            try:
                url = f"https://news.google.com/rss/search?q={quote_plus(search_query + ' when:30d')}&hl={language}&gl={country}&ceid={edition}"
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
                    description = html.unescape(re.sub(r"<[^>]+>", " ", item.findtext("description", "") or ""))
                    description = " ".join(description.split())
                    found.append(record(title, search_query, f"Google News {country}", item.findtext("link", ""), published, 1, description))
                return found
            except Exception:
                return []

        async def gdelt_feed(search_query: str) -> list[dict[str, Any]]:
            try:
                response = await client.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={"query": search_query, "mode": "ArtList", "maxrecords": 75, "format": "json", "sort": "HybridRel", "timespan": "30d"},
                )
                response.raise_for_status()
                return [
                    record(item.get("title", ""), search_query, "GDELT Worldwide", item.get("url", ""), parse_date(item.get("seendate")), 1)
                    for item in response.json().get("articles", [])
                    if item.get("title")
                ]
            except Exception:
                return []

        groups = await asyncio.gather(
            *(google_feed(search_query, *edition) for search_query in queries for edition in google_editions),
            *(gdelt_feed(search_query) for search_query in queries),
        )

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
            if len(item.get("summary", "")) > len(existing.get("summary", "")):
                existing["summary"] = item["summary"]
        else:
            merged[key] = item
    ordered = sorted(
        merged.values(),
        key=lambda item: (item.get("published_at", ""), item.get("mentions", 0)),
        reverse=True,
    )
    for item in ordered:
        item["youtube_search_topic"], item["alternate_topics"] = _youtube_search_terms(item["topic"])
        item["reputation_label"], item["reputation_signals"] = _reputation_label(item["topic"], item.get("summary", ""))
    return ordered[:max(1, min(50, limit))]


def parse_date(value: Any) -> datetime:
    text = str(value or "")
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def record(
    title: str, category: str, source: str, url: str, published: datetime, engagement: int,
    summary: str = "",
) -> dict[str, Any]:
    return {
        "topic": " ".join(str(title).split()),
        "category": category,
        "published_at": published.isoformat(),
        "summary": " ".join(str(summary).split())[:1000],
        "source_urls": [url] if url else [],
        "mentions": 1,
        "source_platforms": [source],
        "source_engagement": {source: engagement},
    }
