import asyncio
import json
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

import httpx

from mcp_outline_client import MCPOutlineError, get_outline_from_mcp


CONTENT_WORDS = {
    "fed": "FINANCE", "rate": "FINANCE", "inflation": "ECONOMY", "gdp": "ECONOMY",
    "bitcoin": "CRYPTO", "crypto": "CRYPTO", "ethereum": "CRYPTO", "election": "POLITICS",
    "president": "POLITICS", "trump": "POLITICS", "congress": "POLITICS", "ai": "TECH / AI",
    "openai": "TECH / AI", "nvidia": "TECH / AI", "tesla": "TECH / AI", "apple": "TECH / AI",
    "oscars": "ENTERTAINMENT", "movie": "ENTERTAINMENT", "album": "ENTERTAINMENT",
    "championship": "SPORTS", "world cup": "SPORTS", "super bowl": "SPORTS",
    "war": "POLITICS", "ceasefire": "POLITICS", "tariff": "ECONOMY", "ipo": "FINANCE",
}
NOISE = re.compile(r"\b(over|under) \d+(\.\d+)?|first (quarter|half)|player props?|parlay|wins by over\b", re.I)


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def category(title: str) -> str | None:
    lower = title.lower()
    for word, label in CONTENT_WORDS.items():
        if word in lower:
            return label
    return None


def tokens(title: str) -> set[str]:
    ignored = {"will", "the", "a", "an", "to", "by", "in", "of", "on", "before", "after", "be"}
    return {word for word in re.findall(r"[a-z0-9]+", title.lower()) if len(word) > 2 and word not in ignored}


def clean_market(item: dict[str, Any]) -> bool:
    title = item.get("topic", "")
    return bool(category(title)) and not NOISE.search(title) and item.get("volume", 0) >= 500


def windows_public_json(url: str) -> Any:
    safe_url = url.replace("'", "''")
    command = f"[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $r=Invoke-RestMethod -Uri '{safe_url}'; $r | ConvertTo-Json -Depth 20 -Compress"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True, timeout=50, check=True,
    )
    for encoding in ("utf-8-sig", "utf-16le"):
        try:
            return json.loads(result.stdout.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise RuntimeError("The public market API returned unreadable data.")


async def fetch_markets(query: str = "") -> list[dict[str, Any]]:
    # These are public, read-only market-data endpoints. The bundled Windows Python
    # environment does not inherit the Windows trust store, so TLS verification is
    # disabled only for these two public reads.
    async with httpx.AsyncClient(timeout=35, follow_redirects=True, verify=False) as client:
        polymarket_request = client.get("https://gamma-api.polymarket.com/markets", params={"active": "true", "closed": "false", "order": "volume24hr", "ascending": "false", "limit": 150})
        kalshi_request = client.get("https://external-api.kalshi.com/trade-api/v2/markets", params={"status": "open", "mve_filter": "exclude", "limit": 1000})
        try:
            polymarket_response, kalshi_response = await asyncio.gather(polymarket_request, kalshi_request)
            polymarket_response.raise_for_status(); kalshi_response.raise_for_status()
            polymarket_data, kalshi_data = polymarket_response.json(), kalshi_response.json()
        except httpx.HTTPError:
            polymarket_url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume24hr&ascending=false&limit=150"
            kalshi_url = "https://external-api.kalshi.com/trade-api/v2/markets?status=open&mve_filter=exclude&limit=1000"
            polymarket_data, kalshi_data = await asyncio.gather(
                asyncio.to_thread(windows_public_json, polymarket_url),
                asyncio.to_thread(windows_public_json, kalshi_url),
            )

    markets: list[dict[str, Any]] = []
    for raw in polymarket_data:
        try:
            prices = json.loads(raw.get("outcomePrices") or "[]")
        except (json.JSONDecodeError, TypeError):
            prices = []
        probability = round(number(prices[0]) * 100, 1) if prices else None
        markets.append({
            "topic": str(raw.get("question") or "").strip(), "category": category(str(raw.get("question") or "")),
            "source": "POLYMARKET", "probability": probability,
            "change_24h": round(number(raw.get("oneDayPriceChange")) * 100, 1),
            "volume": number(raw.get("volume24hr") or raw.get("volume")), "event_date": raw.get("endDate"),
            "source_url": f"https://polymarket.com/event/{raw.get('slug')}", "created_at": raw.get("startDate"),
        })
    for raw in kalshi_data.get("markets", []):
        title = str(raw.get("title") or raw.get("subtitle") or "").strip()
        current = number(raw.get("last_price_dollars") or raw.get("yes_bid_dollars"))
        previous = number(raw.get("previous_price_dollars") or raw.get("previous_yes_bid_dollars"))
        markets.append({
            "topic": title, "category": category(title), "source": "KALSHI",
            "probability": round(current * 100, 1) if current else None,
            "change_24h": round((current - previous) * 100, 1) if current and previous else None,
            "volume": number(raw.get("volume_24h_fp") or raw.get("volume_fp")), "event_date": raw.get("close_time"),
            "source_url": f"https://kalshi.com/markets/{str(raw.get('event_ticker') or '').lower()}", "created_at": raw.get("created_time"),
        })
    query_lower = query.strip().lower()
    markets = [item for item in markets if clean_market(item) and (not query_lower or query_lower in item["topic"].lower())]
    markets.sort(key=lambda item: (abs(item.get("change_24h") or 0) * 2500 + item["volume"]), reverse=True)
    return merge_markets(markets)[:20]


def merge_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for market in markets:
        match = next((item for item in merged if item["source"] != market["source"] and len(tokens(item["topic"]) & tokens(market["topic"])) / max(1, len(tokens(item["topic"]) | tokens(market["topic"]))) >= .45), None)
        if match:
            match["platforms"].append({"source": market["source"], "probability": market["probability"], "change_24h": market["change_24h"], "volume": market["volume"], "url": market["source_url"]})
            match["source"] = "BOTH"; match["volume"] += market["volume"]
            probabilities = [p["probability"] for p in match["platforms"] if p["probability"] is not None]
            match["probability_gap"] = round(max(probabilities) - min(probabilities), 1) if len(probabilities) > 1 else None
        else:
            market["platforms"] = [{"source": market["source"], "probability": market["probability"], "change_24h": market["change_24h"], "volume": market["volume"], "url": market["source_url"]}]
            merged.append(market)
    return merged


async def enrich(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(3)
    async def one(item: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            try:
                concise_topic = " ".join(item["topic"].split()[:10]).rstrip("?!,.;:-")
                outline = await get_outline_from_mcp(concise_topic)
                item["viralizer"] = {"rank": outline.get("viral_rank"), "score": outline.get("viral_score"), "resonance": outline.get("estimated_resonance"), "boost_reach": outline.get("boost_reach"), "remaining_reach": outline.get("remaining_reach"), "competition": outline.get("competition")}
                item["why_it_matters"] = outline.get("why_it_matters") or ""
                item["best_content_angle"] = outline.get("creator_angle") or ""
                item["suggested_headline"] = outline.get("suggested_title") or outline.get("hook") or item["topic"]
            except MCPOutlineError as exc:
                item["viralizer"] = None; item["viralizer_error"] = str(exc)
        movement = abs(item.get("change_24h") or 0)
        item["trend_status"] = "EXPLODING" if movement >= 12 else "VERY HOT" if movement >= 7 else "HOT" if movement >= 3 else "EARLY"
        score = movement * 4 + min(35, item["volume"] / 10000) + (15 if item["source"] == "BOTH" else 0)
        item["prediction_signal"] = "VERY HIGH" if score >= 65 else "HIGH" if score >= 40 else "MEDIUM" if score >= 20 else "LOW"
        item["cross_market_signal"] = "STRONG CROSS-MARKET SIGNAL" if item["source"] == "BOTH" and movement >= 5 else "CROSS-MARKET SIGNAL" if item["source"] == "BOTH" else None
        item["why_odds_moving"] = f"Trader pricing moved {item.get('change_24h'):+.1f} percentage points in 24 hours." if item.get("change_24h") is not None else "The source does not provide a comparable 24-hour probability change."
        rank = number((item.get("viralizer") or {}).get("rank"))
        item["action"] = "PUSH NOW" if score >= 65 and rank and rank <= 30 else "HIGH PRIORITY" if score >= 40 else "EARLY OPPORTUNITY" if score >= 20 else "WATCH"
        return item
    return await asyncio.gather(*(one(item) for item in markets))


async def betting_report(query: str = "") -> dict[str, Any]:
    markets = await fetch_markets(query)
    markets = await enrich(markets[:12])
    markets.sort(key=lambda item: ({"VERY HIGH": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}[item["prediction_signal"]], number((item.get("viralizer") or {}).get("rank")) or 9999, -item["volume"]))
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "query": query, "early_signals": [item for item in markets if item["trend_status"] in ("EXPLODING", "VERY HOT")][:5], "topics": markets}
