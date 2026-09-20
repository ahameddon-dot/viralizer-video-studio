from __future__ import annotations

import asyncio
import html as html_lib
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx

from website_to_video import WebsiteAnalysisError, _validate_public_url
from storyboard_director import build_storyboard_package
from achievement_representation import apply_achievement_representation
from scene_evidence import build_source_evidence_locks
from scene_evidence import collect_source_visual_evidence
from visualizability_analyzer import normalize_visualizability, symbolism_is_supported
from visual_specificity_analyzer import analyze_visual_specificity

try:
    import trafilatura
except ImportError:  # The built-in parser remains a safe fallback during rolling deploys.
    trafilatura = None


ARTICLE_CACHE_TTL = int(os.getenv("ARTICLE_CACHE_TTL", "21600"))
MAX_ARTICLE_BYTES = 3_000_000
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_STORY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass
class NormalizedArticle:
    discovery_url: str = ""
    canonical_url: str = ""
    headline: str = ""
    standfirst: str = ""
    author: str = ""
    published_at: str = ""
    publisher: str = ""
    article_body: str = ""
    image_captions: list[str] = field(default_factory=list)
    source_visual_evidence: list[dict[str, Any]] = field(default_factory=list)
    json_ld: dict[str, Any] = field(default_factory=dict)
    extraction_state: str = "failed"
    extraction_note: str = ""
    word_count: int = 0


def _clean(value: Any, limit: int = 20_000) -> str:
    text = html_lib.unescape(str(value or "")).replace("\ufffd", "'")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_as_text(item) for item in value if _as_text(item))
    if isinstance(value, dict):
        return _as_text(value.get("name") or value.get("headline") or value.get("text"))
    return _clean(value, 1000)


class ArticleParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.description = ""
        self.publisher = ""
        self.author = ""
        self.published_at = ""
        self.canonical_url = base_url
        self.paragraphs: list[str] = []
        self.captions: list[str] = []
        self.images: list[dict[str, str]] = []
        self.json_ld: dict[str, Any] = {}
        self._capture = ""
        self._parts: list[str] = []
        self._skip = 0
        self._json = False
        self._json_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag in {"style", "svg", "noscript"}:
            self._skip += 1
        if tag == "script":
            self._skip += 1
            if "ld+json" in data.get("type", "").lower():
                self._json = True
                self._json_parts = []
        if tag in {"title", "h1", "p", "figcaption"}:
            self._capture = tag
            self._parts = []
        if tag == "link" and "canonical" in data.get("rel", "").lower() and data.get("href"):
            self.canonical_url = urljoin(self.base_url, data["href"])
        if tag == "meta":
            key = (data.get("property") or data.get("name") or data.get("itemprop") or "").lower()
            value = _clean(data.get("content"), 2000)
            if key in {"description", "og:description", "twitter:description"} and not self.description:
                self.description = value
            elif key in {"og:title", "twitter:title"} and not self.title:
                self.title = value
            elif key == "og:site_name" and not self.publisher:
                self.publisher = value
            elif key in {"author", "article:author", "byl"} and not self.author:
                self.author = value
            elif key in {"article:published_time", "datepublished", "date", "pubdate"} and not self.published_at:
                self.published_at = value
            elif key in {"og:image", "twitter:image"} and value:
                self.images.append({"type": "publisher_metadata_image", "url": urljoin(self.base_url, value), "description": "", "context_verified": False})
        if tag == "img" and data.get("src"):
            self.images.append({"type": "article_image_reference", "url": urljoin(self.base_url, data["src"]), "description": _clean(data.get("alt"), 1000), "context_verified": bool(data.get("alt"))})

    def handle_data(self, data: str) -> None:
        if self._json:
            self._json_parts.append(data)
        if not self._skip and self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            if self._json:
                self._consume_json_ld("".join(self._json_parts))
            self._json = False
            self._skip = max(0, self._skip - 1)
        elif tag in {"style", "svg", "noscript"}:
            self._skip = max(0, self._skip - 1)
        if tag != self._capture:
            return
        text = _clean(" ".join(self._parts), 4000)
        if tag == "title" and text and not self.title:
            self.title = text
        elif tag == "h1" and len(text) >= 8:
            self.title = text
        elif tag == "p" and len(text.split()) >= 8:
            self.paragraphs.append(text)
        elif tag == "figcaption" and len(text) >= 5:
            self.captions.append(text)
        self._capture = ""
        self._parts = []

    def _consume_json_ld(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return
        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                queue.extend(item["@graph"])
            kind = _as_text(item.get("@type")).lower()
            if "article" not in kind and "news" not in kind and "reportage" not in kind:
                continue
            if not self.json_ld:
                self.json_ld = item
            self.title = _clean(item.get("headline") or self.title, 500)
            self.description = _clean(item.get("description") or self.description, 2000)
            self.author = _as_text(item.get("author")) or self.author
            self.publisher = _as_text(item.get("publisher")) or self.publisher
            self.published_at = _clean(item.get("datePublished") or self.published_at, 100)
            body = _clean(item.get("articleBody"), 100_000)
            if body:
                self.paragraphs.insert(0, body)
            main = item.get("mainEntityOfPage")
            if isinstance(main, dict):
                main = main.get("@id")
            if isinstance(main, str) and main.startswith(("http://", "https://")):
                self.canonical_url = main


def extract_article_html(discovery_url: str, final_url: str, html: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    parser = ArticleParser(final_url)
    parser.feed(html)
    parser.close()
    fallback = fallback or {}
    extracted: dict[str, Any] = {}
    if trafilatura is not None:
        try:
            raw = trafilatura.extract(html, url=final_url, output_format="json", with_metadata=True, include_comments=False, include_tables=False, favor_precision=True)
            extracted = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            extracted = {}
    body_parts = [_clean(extracted.get("text"), 100_000)] if extracted.get("text") else []
    body_parts.extend(_clean(item, 5000) for item in parser.paragraphs if item)
    body_parts = list(dict.fromkeys(item for item in body_parts if item))
    body = "\n\n".join(body_parts)
    # Navigation/cookie pages produce many tiny fragments; require prose density.
    words = len(re.findall(r"\b[\w''-]+\b", body))
    state = "complete" if words >= 250 else "partial" if words >= 80 else "snippet_only"
    if state == "snippet_only":
        body = ""
    article = NormalizedArticle(
        discovery_url=discovery_url,
        canonical_url=parser.canonical_url or final_url,
        headline=_clean(extracted.get("title"), 500) or parser.title or _clean(fallback.get("topic"), 500),
        standfirst=_clean(extracted.get("description"), 2000) or parser.description or _clean(fallback.get("summary"), 2000),
        author=_clean(extracted.get("author"), 500) or parser.author,
        published_at=_clean(extracted.get("date"), 100) or parser.published_at or _clean(fallback.get("published_at"), 100),
        publisher=_clean(extracted.get("sitename") or extracted.get("hostname"), 300) or parser.publisher or _publisher_name(final_url, fallback),
        article_body=body,
        image_captions=list(dict.fromkeys(parser.captions))[:20],
        source_visual_evidence=parser.images[:20],
        json_ld=parser.json_ld,
        extraction_state=state,
        extraction_note="Publisher article body extracted." if state == "complete" else "A partial publisher article was extracted." if state == "partial" else "Only discovery metadata or a short publisher snippet was available.",
        word_count=words if body else 0,
    )
    return asdict(article)


def _publisher_name(url: str, fallback: dict[str, Any]) -> str:
    platforms = fallback.get("source_platforms") or []
    non_google = next((str(item) for item in platforms if "google" not in str(item).lower()), "")
    if non_google:
        return non_google
    host = (urlparse(url).hostname or "").removeprefix("www.")
    return host.split(".")[0].replace("-", " ").title() if host else ""


async def fetch_article_page(value: str) -> tuple[str, str, int]:
    """Fetch a public article without bypassing access controls or unsafe redirects."""
    current = await _validate_public_url(value)
    headers = {
        "User-Agent": "ViralizerArticleReader/1.0 (+https://viralizer.ai)",
        "Accept": "text/html,application/xhtml+xml;q=0.9",
    }
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers=headers) as client:
        for _ in range(6):
            response = await client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                target = response.headers.get("location")
                if not target:
                    return current, "", response.status_code
                current = await _validate_public_url(urljoin(current, target))
                continue
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code >= 400 or "html" not in content_type:
                return str(response.url), "", response.status_code
            raw = response.content[:MAX_ARTICLE_BYTES]
            encoding = response.encoding or "utf-8"
            return str(response.url), raw.decode(encoding, errors="replace"), response.status_code
    return current, "", 310


def _find_external_url(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            found = _find_external_url(item)
            if found:
                return found
    elif isinstance(value, dict):
        for item in value.values():
            found = _find_external_url(item)
            if found:
                return found
    elif isinstance(value, str):
        text = value.replace("\\/", "/")
        for match in re.findall(r"https?://[^\"'\\\s\]]+", text):
            host = (urlparse(match).hostname or "").lower()
            if host and not any(domain in host for domain in ("google.", "gstatic.", "googleusercontent.")):
                return match
        if text[:1] in {"[", "{"}:
            try:
                return _find_external_url(json.loads(text))
            except (TypeError, ValueError):
                pass
    return ""


async def resolve_google_news_publisher(discovery_url: str, page_html: str) -> str:
    """Resolve Google's signed article token to its publisher URL; no publisher access control is bypassed."""
    host = (urlparse(discovery_url).hostname or "").lower()
    if "news.google." not in host:
        return discovery_url
    token = urlparse(discovery_url).path.rstrip("/").split("/")[-1]
    timestamp = re.search(r'data-n-a-ts="([^"]+)"', page_html)
    signature = re.search(r'data-n-a-sg="([^"]+)"', page_html)
    if not token or not timestamp or not signature:
        return ""
    request_value = [
        "garturlreq",
        [["en-US", "US", ["FINANCE_TOP_INDICES", "WEB_TEST_1_0_0"], None, None, 1, 1, "US:en", None, 180, None, None, None, None, None, 0, None, None, [1608992183, 723341000]], "en-US", "US", 1, [2, 3, 4, 8], 1, 0, "655000234", 0, 0, None, 0],
        token,
        int(timestamp.group(1)),
        signature.group(1),
    ]
    batch = [[["Fbv4je", json.dumps(request_value, separators=(",", ":")), None, "generic"]]]
    endpoint = "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(endpoint, data={"f.req": json.dumps(batch, separators=(",", ":"))}, headers={"User-Agent": "ViralizerArticleReader/1.0 (+https://viralizer.ai)"})
        response.raise_for_status()
        text = response.text
        start = text.find("[[")
        if start < 0:
            return ""
        decoded = json.loads(text[start:])
        target = _find_external_url(decoded)
        return await _validate_public_url(target) if target else ""
    except (httpx.HTTPError, WebsiteAnalysisError, TypeError, ValueError, json.JSONDecodeError):
        return ""


def _blocked_page(html: str, status: int) -> bool:
    if status in {401, 402, 403, 407, 423, 429, 451}:
        return True
    text = _clean(re.sub(r"<[^>]+>", " ", html), 8000).lower()
    signals = (
        "enable javascript and cookies to continue", "verify you are human", "captcha",
        "subscribe to continue reading", "sign in to continue", "access denied",
    )
    return any(signal in text for signal in signals)


def _fallback_article(content: dict[str, Any], discovery_url: str, state: str, note: str) -> dict[str, Any]:
    return asdict(NormalizedArticle(
        discovery_url=discovery_url,
        canonical_url="" if "google" in (urlparse(discovery_url).hostname or "") else discovery_url,
        headline=_clean(content.get("topic") or content.get("suggested_title"), 500),
        standfirst=_clean(content.get("summary") or content.get("description") or content.get("video_idea"), 2000),
        published_at=_clean(content.get("published_at"), 100),
        publisher=_publisher_name(discovery_url, content),
        extraction_state=state,
        extraction_note=note,
    ))


async def resolve_and_extract_article(
    content: dict[str, Any],
    fetcher: Callable[[str], Awaitable[tuple[str, str, int]]] | None = None,
) -> dict[str, Any]:
    urls = content.get("source_urls") or []
    discovery_url = _clean(content.get("discovery_url") or (urls[0] if urls else ""), 2000)
    if not discovery_url:
        return _fallback_article(content, "", "snippet_only", "No article URL was supplied; discovery metadata is being used.")
    cache_key = hashlib.sha256(discovery_url.encode("utf-8")).hexdigest()
    cached = _CACHE.get(cache_key)
    if cached and time.time() - cached[0] < ARTICLE_CACHE_TTL:
        return dict(cached[1])
    try:
        active_fetcher = fetcher or fetch_article_page
        final_url, html, status = await active_fetcher(discovery_url)
        if fetcher is None and "news.google." in (urlparse(final_url).hostname or "") and html:
            publisher_url = await resolve_google_news_publisher(discovery_url, html)
            if publisher_url:
                final_url, html, status = await active_fetcher(publisher_url)
        if _blocked_page(html, status):
            result = _fallback_article(content, discovery_url, "blocked", "The publisher blocked automated reading or requires authentication; discovery metadata is being used.")
            result["canonical_url"] = final_url if "google" not in (urlparse(final_url).hostname or "") else ""
        elif not html:
            result = _fallback_article(content, discovery_url, "failed", f"The publisher page could not be read (HTTP {status}); discovery metadata is being used.")
        else:
            result = extract_article_html(discovery_url, final_url, html, content)
            # Google News interstitials are not publisher articles.
            if "news.google." in (urlparse(result.get("canonical_url") or final_url).hostname or ""):
                result = _fallback_article(content, discovery_url, "snippet_only", "The Google News URL did not resolve to a readable publisher page; discovery metadata is being used.")
    except (WebsiteAnalysisError, httpx.HTTPError, ValueError) as exc:
        result = _fallback_article(content, discovery_url, "failed", f"Article extraction failed safely: {_clean(exc, 180)}")
    if result["extraction_state"] in {"complete", "partial", "snippet_only"}:
        _CACHE[cache_key] = (time.time(), dict(result))
    return result


def _evidence(article: dict[str, Any]) -> str:
    parts = [article.get("headline"), article.get("standfirst"), article.get("article_body")]
    return _clean("\n\n".join(str(part or "") for part in parts), 50_000)


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if len(item.split()) >= 4]


def fallback_story_understanding(article: dict[str, Any]) -> dict[str, Any]:
    evidence = _evidence(article)
    body_lines = list(dict.fromkeys(_sentences(_clean(article.get("article_body"), 50_000))))
    lines = body_lines or _sentences(evidence)
    headline = _clean(article.get("headline"), 500)
    development = next((line for line in lines[:8] if re.search(r"\b(?:will|now|new|first|announc|expect|unveil|auction|launch|open|return)\w*\b", line, re.I)), lines[0] if lines else headline)
    core = headline if not development or development.lower() in headline.lower() else f"{headline}. {development}"
    context = lines[1] if len(lines) > 1 else _clean(article.get("standfirst"), 1000)
    quoted = [item for item in re.findall(r"[\"'“‘]([^\"'”’]{3,80})[\"'”’]", headline) if len(item.split()) <= 10]
    proper = list(dict.fromkeys(re.findall(r"\b[A-Z][A-Za-z0-9&'’-]+(?:\s+[A-Z][A-Za-z0-9&'’-]+){0,3}", evidence)))
    proper = [item for item in proper if item.lower() not in {"the", "new york", "pix11"}]
    subjects = list(dict.fromkeys(quoted + proper))[:8]
    return {
        "what_happened": lines[0] if lines else headline,
        "main_subjects": subjects or ([headline] if headline else []),
        "important_context": context,
        "new_development": development,
        "core_message": core or headline,
        "viewer_takeaway": " ".join(lines[:2]) or core or headline,
        "key_visual_facts": [item for item in lines[:5] if item][:5],
        "factual_boundaries": [f"Source extraction is {article.get('extraction_state') or 'unknown'}; show only people, places, objects and developments supported by the available evidence."],
        "unsupported_visuals": ["Invented locations", "invented products", "unverified events", "readable fabricated statistics"],
        "analysis_mode": "evidence_fallback",
    }


def fallback_visual_story(story: dict[str, Any], duration: int, visualizability: dict[str, Any] | None = None) -> dict[str, Any]:
    visualizability = normalize_visualizability(visualizability, story)
    subjects = story.get("main_subjects") or ["the named subject"]
    subject = _clean(subjects[0], 160)
    facts = story.get("key_visual_facts") or [story.get("core_message")]
    beats = []
    beat_limit = max(1, min(4, (duration + 4) // 5))
    for index, fact in enumerate(facts[:beat_limit]):
        if fact:
            if index == 0:
                visual = f"Begin with {subject} clearly present in the source-supported setting, then use one controlled reveal to make this sourced development visible: {fact}"
            else:
                visual = f"Move closer to {subject} and reveal only the material, object, person, or location detail supported by this sourced fact: {fact}"
            beats.append({"beat": index + 1, "purpose": "hook" if index == 0 else "development", "visual": _clean(visual, 1200)})
    if not beats:
        beats = [{"beat": 1, "purpose": "hook", "visual": f"Reveal {subject} in the real setting named by the source."}]
    beats[-1]["purpose"] = "payoff"
    return {
        "core_visual_subject": subject,
        "visual_message": _clean(visualizability.get("primary_visual_story") or story.get("core_message"), 1200),
        "selected_creative_concept": _clean(f"Use a source-supported before-to-after relationship around {subject}: begin on one evidence detail, let the new development visibly change the surrounding context, and end on its article-specific meaning.", 1200),
        "creative_concept_selection_reason": "It keeps the sourced subject central, makes the article''s development visible, and can remain continuous without inventing events.",
        "visual_hook": beats[0]["visual"],
        "story_beats": beats,
        "continuity_strategy": f"Keep the same {subject}, location, wardrobe, object geometry and lighting logic across every beat.",
        "hero_payoff": _clean(f"Settle on a clean, source-faithful hero view of {subject} that resolves the confirmed development: {story.get('core_message')}", 1200),
        "visual_style": "specific factual editorial cinema grounded in the publisher story",
        "must_show": [_clean(item, 500) for item in facts[:4] if item],
        "must_avoid": list(dict.fromkeys((story.get("unsupported_visuals") or []) + ["fabricated archival photographs or historical reenactments presented as real footage"])),
        "story_type": visualizability.get("story_type"),
        "visualizability_analysis": visualizability,
        "narration_gap": visualizability.get("narration_gap"),
        "muted_test_explanation": "The ordered beats communicate the primary visualizable story; identified abstract meanings may remain for narration.",
        "analysis_mode": "evidence_fallback",
    }


def _json_response_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    return "".join(
        str(part.get("text") or "")
        for item in data.get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


async def _ask_story_model(article: dict[str, Any], duration: int, feedback: str = "") -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = (
        os.getenv("OPENAI_STORY_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip()
        or os.getenv("OPENAI_QC_MODEL", "").strip()
        or "gpt-4.1-mini"
    )
    source = {
        "headline": article.get("headline"),
        "standfirst": article.get("standfirst"),
        "publisher": article.get("publisher"),
        "published_at": article.get("published_at"),
        "article_body": _clean(article.get("article_body"), 40_000),
        "image_captions": article.get("image_captions") or [],
        "source_visual_evidence": collect_source_visual_evidence(article),
        "extraction_state": article.get("extraction_state"),
    }
    max_beats = max(1, min(8, (duration + 4) // 5 + 1))
    instruction = f"""You are the Viralizer Story Understanding, Visualizability Analyzer, and Visual Story Director. Perform those stages in that order.
Analyze only the supplied publisher evidence. Never invent a person, place, product, quote, statistic, event, or visual fact. If evidence is incomplete, stay conservative and record the limitation in factual_boundaries.
 Classify what can be shown truthfully before directing visuals. Visuals must communicate the strongest truthful, article-specific portion of the story, not every abstract meaning. Put abstract or detailed meanings that cannot be shown safely into the narration gap. Do not create symbolism merely to erase that gap.
 Create an article-specific visual plan for a {duration}-second video around the primary_visual_story. Use story-type-appropriate visual progression. Physical action is only one valid mechanism; context reveal, relational reveal, environmental recontextualization, process progression, temporal contrast, scale reveal, cause/effect, state change, and object-state transition are also valid when they add meaning. Camera or lighting change alone is not progression. Keep every beat achievable within the duration and return no more than {max_beats} story beats.
Return one JSON object with exactly three objects:
story_understanding: what_happened (string), main_subjects (array), important_context (string), new_development (string), core_message (string), viewer_takeaway (string), key_visual_facts (array), factual_boundaries (array), unsupported_visuals (array).
 visualizability_analysis: story_type (PERSON_ACTION, OBJECT_SIGNIFICANCE, EVENT, PROCESS, TRANSFORMATION, PRODUCT, PLACE, COMPARISON, RELATIONSHIP, EXPLANATION, or OTHER), visualizable_facts (array), partially_visualizable_meanings (array), narration_dependent_meanings (array), unsafe_to_visualize_without_source_media (array), primary_visual_story (string), supporting_narration_story (string), narration_gap (object: visual_story_target string, viewer_should_understand_visually array, narration_must_explain array, visual_semantic_coverage_target 0-100, narration_gap_acceptable boolean).
 visual_story_plan: core_visual_subject (string), visual_message (string equal to the primary visual story), selected_creative_concept (string), creative_concept_selection_reason (string), visual_hook (string), story_beats (array of objects with beat, purpose, visual, progression_mechanism), continuity_strategy (string), hero_payoff (string), visual_style (string), must_show (array), must_avoid (array), muted_test_explanation (string).
 Internally consider multiple truthful concepts using article specificity, visual impact, scroll-stopping power, core-message clarity, factual safety, continuity, short-form suitability, and AI-video feasibility. Return only the selected concept and a concise selection reason; do not expose candidate reasoning.
 The selected concept must visibly connect the article's new development or viewer takeaway to the core visual subject; a spotlighted subject, material close-up, pan, zoom, or hero display by itself is not a concept. The first second must use the strongest truthful, article-specific visual available. Avoid generic aerials, exteriors, walking, newspapers, phone screens, laptops, crowds, or product rotations unless the evidence makes one essential.
 The core_visual_subject is the exact object, person, event, process, transformation, or relationship that must carry the story visually. Choose it from the full article, not merely the first named person. Every story beat must preserve it.
 Do not request fabricated archival or historical photographs. Unless actual source assets are supplied, keep generated beats focused on visuals that can be represented safely and put fabricated archival imagery or reenactments in must_avoid. Reject unsupported symbolic inventions such as crown-shaped shadows, broken chains, phoenix imagery, shattering glass, a clearing storm, or a spotlight presented as empowerment. Prefer literal factual context whenever it can communicate the primary visual story.
 Do not mention internal engine terminology. Do not instruct the video model to show readable text, headlines, logos, dashboards, or fabricated UI. {feedback}"""
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": instruction}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(source, ensure_ascii=False)}]},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"}, json=payload)
    response.raise_for_status()
    result = json.loads(_json_response_text(response.json()))
    result["model"] = model
    return result


def validate_story_package(story: dict[str, Any], plan: dict[str, Any], duration: int, visualizability: dict[str, Any] | None = None) -> dict[str, Any]:
    visualizability = normalize_visualizability(visualizability or plan.get("visualizability_analysis") or story.get("visualizability_analysis"), story)
    subjects = " ".join(str(item) for item in story.get("main_subjects") or [])
    subject_terms = {word.lower() for word in re.findall(r"[A-Za-z0-9''-]{4,}", subjects)}
    visual_text = json.dumps(plan, ensure_ascii=False).lower()
    beats = plan.get("story_beats") if isinstance(plan.get("story_beats"), list) else []
    beat_text = " ".join(_clean(item.get("visual"), 80) for item in beats if isinstance(item, dict))
    generic_phrases = ("generic footage", "relevant activity", "dynamic visuals", "engaging scene", "show the topic")
    unsupplied_asset_phrases = ("archival footage", "archival image", "archival photo", "historical photograph", "photo frame", "vintage invitation", "handwriting", "reenactment", "map animation", "gavel fades", "gavel softly fades")
    muted = bool(plan.get("visual_hook") and plan.get("hero_payoff") and beat_text and (not subject_terms or any(term in visual_text for term in subject_terms)))
    progression_terms = ("physical_action", "state_change", "context_reveal", "relational_reveal", "environmental_recontextualization", "process_progression", "temporal_contrast", "scale_reveal", "cause_effect", "object_state_transition", "reveal", "compare", "before-to-after", "relationship", "process", "context")
    progression = any(term in visual_text.replace("-", "_").replace(" ", "_") for term in progression_terms)
    generic = any(phrase in visual_text for phrase in generic_phrases) or not progression
    max_beats = max(1, min(8, (duration + 4) // 5 + 1))
    factual = bool(story.get("core_message") and story.get("factual_boundaries") and plan.get("must_avoid"))
    core_visual_subject = _clean(plan.get("core_visual_subject"), 200)
    concept = _clean(plan.get("selected_creative_concept"), 500).lower()
    positive_visual_text = " ".join((concept, _clean(plan.get("visual_hook"), 1000).lower(), beat_text.lower(), _clean(plan.get("hero_payoff"), 1000).lower()))
    subject_words = {word.lower() for word in re.findall(r"[A-Za-z0-9'-]{5,}", core_visual_subject)}
    specificity_words = {word.lower() for word in re.findall(r"[A-Za-z0-9'-]{5,}", f"{story.get('new_development','')} {story.get('viewer_takeaway','')}")} - subject_words
    specificity_words -= {"about", "through", "being", "shown", "their", "which", "where", "story", "visual", "public", "important"}
    concept_specific = bool(concept and specificity_words and any(word in concept for word in specificity_words))
    concept_mechanism = any(term in concept for term in ("reflection", "threshold", "before-to-after", "comparison", "contrast", "transforms", "transformation", "relationship", "match transition", "environmental transition", "cause and effect", "physically changes", "visibly change"))
    checks = {
        "structured_story": all(key in story for key in ("what_happened", "core_message", "viewer_takeaway", "key_visual_facts", "factual_boundaries", "unsupported_visuals")),
        "structured_visual_plan": bool(core_visual_subject) and all(key in plan for key in ("core_visual_subject", "visual_message", "selected_creative_concept", "creative_concept_selection_reason", "visual_hook", "story_beats", "continuity_strategy", "hero_payoff", "must_show", "must_avoid")),
        "muted_visual_story_pass": muted,
        "muted_test_pass": muted,
        "generic_video_pass": not generic,
        "duration_fit": 1 <= len(beats) <= max_beats,
        "factual_boundaries_present": factual,
        "generated_visuals_safe": not any(phrase in beat_text.lower() for phrase in unsupplied_asset_phrases),
        "symbolism_safe": symbolism_is_supported(positive_visual_text, visualizability),
        "article_specific_visual_progression": progression,
        "narration_gap_declared": bool(visualizability.get("narration_gap", {}).get("visual_story_target")),
        "creative_concept_article_specific": concept_specific and concept_mechanism,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "beat_count": len(beats), "duration": duration}


async def build_story_package(article: dict[str, Any], duration: int) -> dict[str, Any]:
    cache_material = json.dumps({"duration": duration, "url": article.get("canonical_url"), "evidence": _evidence(article)}, ensure_ascii=False, sort_keys=True)
    cache_key = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
    cached = _STORY_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < ARTICLE_CACHE_TTL:
        return json.loads(json.dumps(cached[1]))
    result: dict[str, Any] | None = None
    error = ""
    for attempt in range(2):
        try:
            feedback = ""
            if attempt:
                max_beats = max(1, min(8, (duration + 4) // 5 + 1))
                feedback = f"The first plan failed validation. Make the subject unmistakable and choose an article-specific visual mechanism such as a truthful reflection, threshold, comparison, cause/effect, object match, or environmental transformation that makes the new development visible. A close-up, pan, spotlight, zoom, or hero display alone is not a creative concept. Replace generic footage with observable sourced action, preserve factual boundaries, use no more than {max_beats} story beats, and fit the duration. Keep generated beats on the core visual subject. Do not use invitations, documents, handwriting, photo frames, archival or historical images, reenactments, gavel overlays, maps, or readable text when no real source assets are supplied."
            candidate = await _ask_story_model(article, duration, feedback)
            story = candidate.get("story_understanding") or {}
            visualizability = normalize_visualizability(candidate.get("visualizability_analysis"), story)
            story["visualizability_analysis"] = visualizability
            plan = candidate.get("visual_story_plan") or {}
            plan["story_type"] = visualizability.get("story_type")
            plan["visualizability_analysis"] = visualizability
            plan["narration_gap"] = visualizability.get("narration_gap")
            plan["source_visual_evidence"] = collect_source_visual_evidence(article)
            specificity = analyze_visual_specificity(story, visualizability, plan["source_visual_evidence"])
            visualizability["visual_specificity_analysis"] = specificity
            visualizability["narration_gap"].update(
                identity_narration_required=specificity["identity_narration_required"],
                identity_details_for_narration=specificity["identity_details_for_narration"],
                abstract_meanings_for_narration=specificity["abstract_meanings_for_narration"],
                factual_details_for_narration=specificity["factual_details_for_narration"],
            )
            plan["visual_specificity_analysis"] = specificity
            plan["visual_message"] = visualizability.get("primary_visual_story") or plan.get("visual_message")
            story["analysis_mode"] = "llm"
            plan["analysis_mode"] = "llm"
            validation = validate_story_package(story, plan, duration, visualizability)
            result = {"story_understanding": story, "visualizability_analysis": visualizability, "visual_story_plan": plan, "validation": validation, "model": candidate.get("model"), "attempts": attempt + 1}
            if validation["status"] == "PASS":
                _STORY_CACHE[cache_key] = (time.time(), result)
                return result
        except Exception as exc:
            error = _clean(exc, 240)
            break
    story = fallback_story_understanding(article)
    visualizability = normalize_visualizability(None, story)
    story["visualizability_analysis"] = visualizability
    plan = fallback_visual_story(story, duration, visualizability)
    plan["source_visual_evidence"] = collect_source_visual_evidence(article)
    specificity = analyze_visual_specificity(story, visualizability, plan["source_visual_evidence"])
    visualizability["visual_specificity_analysis"] = specificity
    visualizability["narration_gap"].update(
        identity_narration_required=specificity["identity_narration_required"],
        identity_details_for_narration=specificity["identity_details_for_narration"],
        abstract_meanings_for_narration=specificity["abstract_meanings_for_narration"],
        factual_details_for_narration=specificity["factual_details_for_narration"],
    )
    plan["visual_specificity_analysis"] = specificity
    validation = validate_story_package(story, plan, duration, visualizability)
    result = {"story_understanding": story, "visualizability_analysis": visualizability, "visual_story_plan": plan, "validation": validation, "model": "deterministic-evidence-fallback", "attempts": 0, "fallback_reason": error or "The generated plan did not pass validation."}
    _STORY_CACHE[cache_key] = (time.time(), result)
    return result


async def prepare_article_intelligence(content: dict[str, Any], duration: int, aspect_ratio: str = "9:16") -> dict[str, Any]:
    existing = content.get("article_intelligence")
    if isinstance(existing, dict) and existing.get("version") == 3 and existing.get("duration") == duration and existing.get("aspect_ratio") == aspect_ratio:
        return dict(content)
    article = await resolve_and_extract_article(content)
    package = await build_story_package(article, duration)
    achievement = apply_achievement_representation(
        article, package["story_understanding"], package["visual_story_plan"]
    )
    evidence_locks = build_source_evidence_locks(
        package["story_understanding"], package["visual_story_plan"]
    )
    package["story_understanding"]["source_evidence_locks"] = evidence_locks
    package["visual_story_plan"]["source_evidence_locks"] = evidence_locks
    storyboard = await build_storyboard_package(article, package["story_understanding"], package["visual_story_plan"], duration, aspect_ratio)
    effective_visual_plan = storyboard.get("effective_visual_story_plan") or package["visual_story_plan"]
    enriched = dict(content)
    enriched.update(
        article=article,
        article_body=article.get("article_body", ""),
        canonical_url=article.get("canonical_url", ""),
        extraction_state=article.get("extraction_state", "failed"),
        story_understanding=package["story_understanding"],
        visualizability_analysis=package.get("visualizability_analysis", {}),
        source_visual_evidence=collect_source_visual_evidence(article),
        visual_story_plan=effective_visual_plan,
        selected_creative_concept=effective_visual_plan.get("selected_creative_concept", ""),
        creative_concept_selection_reason=effective_visual_plan.get("creative_concept_selection_reason", ""),
        storyboard=storyboard["storyboard"],
        reference_frame_plans=storyboard["reference_frame_plans"],
        visual_qc_specs=storyboard["visual_qc_specs"],
        muted_test_v2=storyboard["muted_test_v2"],
        generic_video_test_v2=storyboard["generic_video_test_v2"],
        core_message=package["story_understanding"].get("core_message", ""),
        visual_message=effective_visual_plan.get("visual_message", ""),
        core_visual_subject=effective_visual_plan.get("core_visual_subject", ""),
        factual_boundaries=package["story_understanding"].get("factual_boundaries", []),
        unsupported_visuals=package["story_understanding"].get("unsupported_visuals", []),
        achievement_representation=achievement,
        source_evidence_locks=evidence_locks,
        generated_text_routing=storyboard.get("generated_text_routing") or {},
        story_type_qc=storyboard.get("story_type_qc") or {},
        article_intelligence={
            "version": 3,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "extraction_state": article.get("extraction_state"),
            "extraction_note": article.get("extraction_note"),
            "word_count": article.get("word_count", 0),
            "visualizability_analysis": package.get("visualizability_analysis", {}),
            "source_visual_evidence": collect_source_visual_evidence(article),
            "analysis_model": package.get("model"),
            "analysis_attempts": package.get("attempts"),
            "validation": package["validation"],
            "storyboard_model": storyboard.get("model"),
            "storyboard_attempts": storyboard.get("attempts"),
            "storyboard_validation": storyboard.get("validation"),
            "storyboard_fallback_reason": storyboard.get("fallback_reason", ""),
            "creative_story_qc": storyboard.get("creative_story_qc"),
            "achievement_representation": achievement,
            "source_evidence_locks": evidence_locks,
            "generated_text_routing": storyboard.get("generated_text_routing") or {},
            "story_type_qc": storyboard.get("story_type_qc") or {},
            "creative_revision_count": storyboard.get("creative_revision_count", 0),
            "creative_revision_history": storyboard.get("creative_revision_history", []),
            "approved_for_media_generation": storyboard.get("approved_for_media_generation", False),
            "fallback_reason": package.get("fallback_reason", ""),
        },
    )
    return enriched
