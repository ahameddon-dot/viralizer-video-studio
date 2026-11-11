"""Safe, provider-free analysis of customer-supplied public brand URLs."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections import Counter
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

MAX_BYTES = 1_000_000
SOCIAL_HOSTS = {"youtube.com", "www.youtube.com", "instagram.com", "www.instagram.com", "tiktok.com", "www.tiktok.com", "linkedin.com", "www.linkedin.com", "x.com", "www.x.com"}
STOP = {"about","after","also","and","are","been","being","best","but","can","from","have","into","more","our","that","the","their","this","through","use","using","what","when","where","which","with","you","your"}


class PageSignals(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.title=""; self.description=""; self.headings=[]; self.text=[]; self._tag=""; self._skip=0
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag=tag
        if tag in {"script","style","svg","noscript"}: self._skip += 1
        values={k.lower():v or "" for k,v in attrs}
        if tag=="meta" and values.get("name","").lower() in {"description","twitter:description"}: self.description=values.get("content","")[:1000]
        if tag=="meta" and values.get("property","").lower()=="og:description" and not self.description: self.description=values.get("content","")[:1000]
    def handle_endtag(self, tag: str) -> None:
        if tag in {"script","style","svg","noscript"} and self._skip: self._skip-=1
        self._tag=""
    def handle_data(self, data: str) -> None:
        value=" ".join(data.split())
        if not value or self._skip: return
        if self._tag=="title" and not self.title: self.title=value[:300]
        if self._tag in {"h1","h2","h3"}: self.headings.append(value[:300])
        if len(value)>2: self.text.append(value)


async def _public_url(url: str) -> str:
    parsed=urlparse(url.strip())
    if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public http(s) URLs without embedded credentials are allowed.")
    host=parsed.hostname.casefold()
    try: addresses={item[4][0] for item in await asyncio.to_thread(socket.getaddrinfo,host,parsed.port or (443 if parsed.scheme=="https" else 80),type=socket.SOCK_STREAM)}
    except socket.gaierror as exc: raise ValueError(f"Could not resolve {host}.") from exc
    if not addresses: raise ValueError(f"Could not resolve {host}.")
    for address in addresses:
        ip=ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global: raise ValueError("Local, private, and reserved network addresses are not allowed.")
    return parsed.geturl()


async def _fetch(url: str, client: httpx.AsyncClient) -> tuple[str,str]:
    current=await _public_url(url)
    for _ in range(4):
        async with client.stream("GET",current,headers={"User-Agent":"ViralizerBrandIntelligence/1.0 (+customer-requested analysis)","Accept":"text/html,application/xhtml+xml"}) as response:
            if response.status_code in {301,302,303,307,308}:
                target=response.headers.get("location","")
                if not target: raise ValueError("Redirect did not include a destination.")
                current=await _public_url(urljoin(current,target)); continue
            response.raise_for_status()
            kind=response.headers.get("content-type","").lower()
            if "html" not in kind: raise ValueError("The URL did not return an HTML page.")
            chunks=[]; size=0
            async for chunk in response.aiter_bytes():
                size+=len(chunk)
                if size>MAX_BYTES: raise ValueError("The page exceeded the 1 MB analysis limit.")
                chunks.append(chunk)
            return current,b"".join(chunks).decode(response.encoding or "utf-8",errors="replace")
    raise ValueError("Too many redirects.")


def _analyse(url: str, html: str) -> dict[str, Any]:
    parser=PageSignals(); parser.feed(html)
    text=" ".join(parser.text)[:120_000]
    words=[w for w in re.findall(r"[a-z][a-z0-9-]{2,}",text.casefold()) if w not in STOP]
    themes=[word for word,_ in Counter(words).most_common(12)]
    combined=" ".join([parser.title,parser.description,*parser.headings[:8]]).strip()
    tone=[]
    lower=text.casefold()
    for label,terms in {"professional":["expert","professional","solutions","industry"],"educational":["learn","guide","how to","insights"],"energetic":["exciting","fast","power","transform"],"friendly":["welcome","community","together","help"]}.items():
        if any(term in lower for term in terms): tone.append(label)
    return {"url":url,"title":parser.title,"description":parser.description,"positioning_evidence":combined[:1200],"content_themes":themes,"interests":themes[:8],"voice_signals":tone or ["not confidently detected"],"heading_samples":parser.headings[:8],"text_characters_analyzed":len(text)}


async def analyze_brand_sources(website_url: str, social_urls: list[str], client: httpx.AsyncClient | None=None) -> dict[str, Any]:
    urls=list(dict.fromkeys([u.strip() for u in [website_url,*social_urls] if u.strip()]))[:21]
    owned=client is None
    session=client or httpx.AsyncClient(timeout=httpx.Timeout(12),follow_redirects=False)
    sources=[]
    try:
        for url in urls:
            host=(urlparse(url).hostname or "").casefold()
            try:
                final,html=await _fetch(url,session); signals=_analyse(final,html)
                signals.update({"source_type":"social" if host in SOCIAL_HOSTS else "website","status":"analyzed"}); sources.append(signals)
            except (ValueError,httpx.HTTPError) as exc:
                sources.append({"url":url,"source_type":"social" if host in SOCIAL_HOSTS else "website","status":"connection_required" if host in SOCIAL_HOSTS else "unavailable","reason":str(exc)[:300]})
    finally:
        if owned: await session.aclose()
    analyzed=[s for s in sources if s["status"]=="analyzed"]
    themes=list(dict.fromkeys(theme for source in analyzed for theme in source.get("content_themes",[])))[:15]
    voices=list(dict.fromkeys(tone for source in analyzed for tone in source.get("voice_signals",[]) if tone!="not confidently detected"))[:8]
    descriptions=[s.get("description") or s.get("title") for s in analyzed if s.get("description") or s.get("title")]
    return {"status":"draft_requires_confirmation","sources":sources,"draft":{"positioning":" ".join(descriptions)[:1500],"content_themes":themes,"areas_of_interest":themes[:10],"voice":voices},"disclosure":"This is evidence-based extraction, not a verified fact. The customer must review and confirm every field."}
