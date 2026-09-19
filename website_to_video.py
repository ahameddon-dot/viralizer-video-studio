from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx


MAX_PAGE_BYTES = 2_000_000
NEWS_WORDS = {
    "news", "latest", "breaking", "world", "business", "technology", "politics",
    "sports", "markets", "science", "entertainment", "article", "story",
}
COMPANY_WORDS = {
    "product", "products", "service", "services", "solutions", "features",
    "pricing", "customers", "company", "about", "platform",
}


class WebsiteAnalysisError(RuntimeError):
    pass


@dataclass
class Page:
    url: str
    title: str = ""
    description: str = ""
    site_name: str = ""
    published_at: str = ""
    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    article_type: str = ""
    logo_url: str = ""


def _clean(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


class PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.page = Page(url=base_url)
        self._tag = ""
        self._skip = 0
        self._parts: list[str] = []
        self._href = ""
        self._json_ld = False
        self._json_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag in {"style", "noscript", "svg"}:
            self._skip += 1
        if tag == "script":
            self._skip += 1
            if "ld+json" in attrs_dict.get("type", "").lower():
                self._json_ld = True
                self._json_parts = []
        if tag in {"title", "h1", "h2", "h3", "p", "a"}:
            self._tag = tag
            self._parts = []
            self._href = attrs_dict.get("href", "") if tag == "a" else ""
        if tag == "link" and not self.page.logo_url:
            rel = attrs_dict.get("rel", "").lower()
            href = attrs_dict.get("href", "")
            if href and ("icon" in rel or "apple-touch-icon" in rel):
                self.page.logo_url = urljoin(self.base_url, href)
        if tag == "img" and not self.page.logo_url:
            src = attrs_dict.get("src", "")
            identity = " ".join((attrs_dict.get("alt", ""), attrs_dict.get("class", ""), attrs_dict.get("id", ""), src)).lower()
            if src and "logo" in identity:
                self.page.logo_url = urljoin(self.base_url, src)
        if tag == "meta":
            key = (attrs_dict.get("property") or attrs_dict.get("name") or attrs_dict.get("itemprop") or "").lower()
            value = _clean(attrs_dict.get("content"), 1000)
            if key in {"description", "og:description", "twitter:description"} and not self.page.description:
                self.page.description = value
            elif key in {"og:title", "twitter:title"} and not self.page.title:
                self.page.title = value
            elif key == "og:site_name":
                self.page.site_name = value
            elif key in {"article:published_time", "datepublished", "date", "pubdate"}:
                self.page.published_at = value
            elif key == "og:type":
                self.page.article_type = value.lower()

    def handle_data(self, data: str) -> None:
        if self._json_ld:
            self._json_parts.append(data)
        if not self._skip and self._tag:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            if self._json_ld:
                self._consume_json_ld("".join(self._json_parts))
            self._json_ld = False
            self._skip = max(0, self._skip - 1)
        elif tag in {"style", "noscript", "svg"}:
            self._skip = max(0, self._skip - 1)
        if tag != self._tag:
            return
        text = _clean(" ".join(self._parts), 1000)
        if tag == "title" and text and not self.page.title:
            self.page.title = text
        elif tag in {"h1", "h2", "h3"} and len(text) >= 8:
            self.page.headings.append(text)
        elif tag == "p" and len(text) >= 35:
            self.page.paragraphs.append(text)
        elif tag == "a" and self._href and len(text) >= 12:
            self.page.links.append((urljoin(self.base_url, self._href), text))
        self._tag = ""
        self._parts = []
        self._href = ""

    def _consume_json_ld(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            kind = str(item.get("@type") or "").lower()
            if "article" in kind or "news" in kind:
                self.page.article_type = kind
                self.page.title = _clean(item.get("headline") or self.page.title, 300)
                self.page.description = _clean(item.get("description") or self.page.description, 1000)
                self.page.published_at = _clean(item.get("datePublished") or self.page.published_at, 80)


def parse_page(url: str, html: str) -> Page:
    parser = PageParser(url)
    parser.feed(html)
    parser.close()
    page = parser.page
    page.headings = list(dict.fromkeys(page.headings))[:30]
    page.paragraphs = list(dict.fromkeys(page.paragraphs))[:30]
    page.links = list(dict.fromkeys(page.links))[:250]
    page.title = _clean(page.title, 300)
    page.description = _clean(page.description, 1000)
    return page


def normalize_url(value: str) -> str:
    value = _clean(value, 2000)
    if not value:
        raise WebsiteAnalysisError("Enter a public website URL.")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebsiteAnalysisError("Use a valid public HTTP or HTTPS website URL.")
    if parsed.username or parsed.password:
        raise WebsiteAnalysisError("Website URLs containing credentials are not supported.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise WebsiteAnalysisError("The website URL contains an invalid port.") from exc
    if port not in {None, 80, 443}:
        raise WebsiteAnalysisError("Only standard website ports are supported.")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))


async def _validate_public_url(value: str) -> str:
    value = normalize_url(value)
    host = urlparse(value).hostname or ""
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebsiteAnalysisError("The website address could not be resolved.") from exc
    addresses = {record[4][0] for record in records}
    if not addresses:
        raise WebsiteAnalysisError("The website address could not be resolved.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise WebsiteAnalysisError("Private, local, or reserved website addresses are not allowed.")
    return value


async def _fetch_public(value: str) -> tuple[str, str]:
    current = await _validate_public_url(value)
    headers = {
        "User-Agent": "ViralizerWebsiteAnalyzer/1.0 (+https://viralizer.ai)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.8",
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers=headers) as client:
        for _ in range(5):
            response = await client.get(current)
            stream = response.extensions.get("network_stream")
            if stream is not None:
                peer = stream.get_extra_info("server_addr")
                if peer and not ipaddress.ip_address(peer[0]).is_global:
                    raise WebsiteAnalysisError("The website resolved to a private or reserved network address.")
            if response.status_code in {301, 302, 303, 307, 308}:
                target = response.headers.get("location")
                if not target:
                    raise WebsiteAnalysisError("The website returned an invalid redirect.")
                current = await _validate_public_url(urljoin(current, target))
                continue
            if response.status_code >= 400:
                raise WebsiteAnalysisError(f"The website returned HTTP {response.status_code}.")
            content_type = response.headers.get("content-type", "").lower()
            if not any(kind in content_type for kind in ("text/html", "application/xhtml", "application/xml", "text/xml")):
                raise WebsiteAnalysisError("The URL did not return a readable web page.")
            raw = response.content
            if len(raw) > MAX_PAGE_BYTES:
                raw = raw[:MAX_PAGE_BYTES]
            declared = response.encoding or "utf-8"
            decoded = raw.decode("utf-8", errors="replace")
            if decoded.count("�") > 3 and declared.lower() not in {"utf-8", "utf8"}:
                decoded = raw.decode(declared, errors="replace")
            return str(response.url), decoded
    raise WebsiteAnalysisError("The website redirected too many times.")


async def fetch_public_image(value: str, max_bytes: int = 10 * 1024 * 1024) -> tuple[bytes, str]:
    current = await _validate_public_url(value)
    headers = {"User-Agent": "ViralizerLogoFetcher/1.0 (+https://viralizer.ai)", "Accept": "image/png,image/jpeg,image/webp"}
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers=headers) as client:
        for _ in range(5):
            response = await client.get(current)
            stream = response.extensions.get("network_stream")
            if stream is not None:
                peer = stream.get_extra_info("server_addr")
                if peer and not ipaddress.ip_address(peer[0]).is_global:
                    raise WebsiteAnalysisError("The logo resolved to a private or reserved network address.")
            if response.status_code in {301, 302, 303, 307, 308}:
                target = response.headers.get("location")
                if not target:
                    raise WebsiteAnalysisError("The logo returned an invalid redirect.")
                current = await _validate_public_url(urljoin(current, target))
                continue
            if response.status_code >= 400:
                raise WebsiteAnalysisError(f"The logo returned HTTP {response.status_code}.")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
                raise WebsiteAnalysisError("The logo URL did not return a supported image.")
            raw = response.content
            if not raw or len(raw) > max_bytes:
                raise WebsiteAnalysisError("The logo image is empty or larger than 10 MB.")
            return raw, content_type
    raise WebsiteAnalysisError("The logo redirected too many times.")


def _same_site(a: str, b: str) -> bool:
    left = (urlparse(a).hostname or "").removeprefix("www.")
    right = (urlparse(b).hostname or "").removeprefix("www.")
    return left == right


def _news_score(url: str, title: str, index: int) -> int:
    path = urlparse(url).path.lower()
    words = set(re.findall(r"[a-z]+", f"{path} {title.lower()}"))
    score = max(0, 60 - index)
    score += 22 * len(words & NEWS_WORDS)
    score += 25 if re.search(r"/20\d{2}/(?:0?[1-9]|1[0-2])/", path) else 0
    score += 18 if len(title) >= 35 else 0
    score += 12 if path.count("/") >= 3 else 0
    navigation_title = title.strip().lower()
    if any(term in path for term in ("/tag/", "/author/", "/category/", "/privacy", "/contact", "/login")):
        score -= 80
    if navigation_title.startswith("skip to ") or any(term in navigation_title for term in ("news brasil", "news mundo", "privacy policy", "sign in")):
        score -= 100
    if path.rstrip("/") in {"", "/news", "/world", "/latest", "/breaking-news"}:
        score -= 45
    if len([segment for segment in path.split("/") if segment]) <= 2 and not re.search(r"\d", path):
        score -= 25
    return score


def _looks_like_news(page: Page) -> bool:
    haystack = " ".join([page.title, page.description, page.article_type, *page.headings[:12]]).lower()
    article_links = sum(1 for index, (url, title) in enumerate(page.links[:100]) if _news_score(url, title, index) >= 70)
    return "article" in page.article_type or len(set(re.findall(r"[a-z]+", haystack)) & NEWS_WORDS) >= 2 or article_links >= 5


def _summary(page: Page) -> str:
    if page.description:
        return page.description
    return _clean(" ".join(page.paragraphs[:3]), 850)


async def analyze_website(url: str) -> dict[str, Any]:
    final_url, html = await _fetch_public(url)
    home = parse_page(final_url, html)
    is_news = _looks_like_news(home)
    selected = home
    alternatives: list[dict[str, str]] = []

    if is_news:
        candidates: list[tuple[int, str, str]] = []
        seen: set[str] = set()
        for index, (link, title) in enumerate(home.links):
            try:
                clean_link = normalize_url(link)
            except WebsiteAnalysisError:
                continue
            if clean_link in seen or not _same_site(final_url, clean_link):
                continue
            seen.add(clean_link)
            score = _news_score(clean_link, title, index)
            if score >= 55:
                candidates.append((score, clean_link, title))
        candidates.sort(reverse=True)
        candidates = candidates[:8]

        async def inspect(candidate: tuple[int, str, str]) -> tuple[int, Page] | None:
            score, link, title = candidate
            try:
                resolved, article_html = await _fetch_public(link)
                page = parse_page(resolved, article_html)
                page.title = page.title or title
                article_score = score + (35 if "article" in page.article_type else 0) + (20 if page.published_at else 0)
                return article_score, page
            except (WebsiteAnalysisError, httpx.HTTPError):
                return None

        inspected = [item for item in await asyncio.gather(*(inspect(item) for item in candidates)) if item]
        if inspected:
            inspected.sort(key=lambda item: item[0], reverse=True)
            selected = inspected[0][1]
            alternatives = [
                {"title": page.title, "url": page.url, "published_at": page.published_at, "summary": _summary(page)}
                for _, page in inspected[1:8]
            ]

    source_type = "news" if is_news else "company"
    site_name = selected.site_name or home.site_name or (urlparse(final_url).hostname or "").removeprefix("www.")
    title = selected.title or (selected.headings[0] if selected.headings else site_name)
    summary = _summary(selected) or _summary(home)
    if not is_news:
        seen_angles = {title.lower()}
        alternatives = []
        for heading in home.headings:
            clean_heading = _clean(heading, 180)
            if len(clean_heading) < 12 or clean_heading.lower() in seen_angles:
                continue
            seen_angles.add(clean_heading.lower())
            alternatives.append({"title": clean_heading, "url": home.url, "published_at": "", "summary": summary})
            if len(alternatives) >= 7:
                break
    if is_news:
        idea = (
            f"Turn the verified article into a concise visual news explainer. Open with the central development, "
            f"show the people, place, product, or event directly supported by the source, explain why it matters, "
            f"and end with the clearest confirmed takeaway. Avoid unsupported claims."
        )
        hook = f"The latest from {site_name}: {title}"
        category = "News"
    else:
        supporting = "; ".join((selected.headings or home.headings)[:4])
        idea = (
            f"Create a grounded brand or product explainer from this public website. Show what {site_name} offers, "
            f"the customer problem it addresses, its most concrete benefit, and a clean closing brand moment. "
            f"Use only claims supported by the source page."
        )
        if supporting:
            idea += f" Relevant page themes: {supporting}."
        hook = f"What {site_name} offers—and why it may matter"
        category = "Brand / Product"

    content = {
        "topic": title,
        "suggested_title": title,
        "hook": hook,
        "summary": summary,
        "why_it_matters": summary,
        "video_idea": idea,
        "creator_angle": idea,
        "category": category,
        "source_type": source_type,
        "source_site": site_name,
        "source_url": selected.url,
        "source_logo_url": selected.logo_url or home.logo_url,
        "source_urls": [selected.url],
        "published_at": selected.published_at,
    }
    return {
        "source_type": source_type,
        "site_name": site_name,
        "source_url": selected.url,
        "source_logo_url": selected.logo_url or home.logo_url,
        "selected": {
            "title": title,
            "summary": summary,
            "published_at": selected.published_at,
        },
        "alternatives": alternatives,
        "content": content,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
