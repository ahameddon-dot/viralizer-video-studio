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

MAX_BYTES = 4_000_000
SOCIAL_HOSTS = {"youtube.com", "www.youtube.com", "instagram.com", "www.instagram.com", "tiktok.com", "www.tiktok.com", "linkedin.com", "www.linkedin.com", "x.com", "www.x.com"}
STOP = {"about","after","also","and","are","been","being","best","but","can","contact","copyright","creator","featured","from","have","into","join","more","our","press","that","the","their","this","through","use","using","videos","want","what","when","where","which","with","you","your","youtube"}


class PageSignals(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.title=""; self.description=""; self.image=""; self.author=""; self.keywords=""; self.headings=[]; self.text=[]; self._tag=""; self._skip=0
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag=tag
        if tag in {"script","style","svg","noscript"}: self._skip += 1
        values={k.lower():v or "" for k,v in attrs}
        if tag=="meta" and values.get("name","").lower() in {"description","twitter:description"}: self.description=values.get("content","")[:1000]
        if tag=="meta" and values.get("property","").lower()=="og:description" and not self.description: self.description=values.get("content","")[:1000]
        if tag=="meta" and values.get("property","").lower()=="og:title" and not self.title: self.title=values.get("content","")[:300]
        if tag=="meta" and values.get("property","").lower()=="og:image" and not self.image: self.image=values.get("content","")[:1000]
        if tag=="meta" and values.get("name","").lower()=="author": self.author=values.get("content","")[:300]
        if tag=="meta" and values.get("name","").lower()=="keywords": self.keywords=values.get("content","")[:1000]
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


def _clean_json_text(value: str) -> str:
    try:
        import json
        return " ".join(json.loads(f'"{value}"').split())
    except Exception:
        return " ".join(value.replace("\\n", " ").replace("\\u0026", "&").split())


def _youtube_signals(html: str) -> dict[str, Any]:
    channel_id = next(iter(re.findall(r'"channelId"\s*:\s*"([A-Za-z0-9_-]{10,})"', html)), "")
    owner = next(iter(re.findall(r'"ownerChannelName"\s*:\s*"((?:\\.|[^"\\])*)"', html)), "")
    descriptions = re.findall(r'"description"\s*:\s*"((?:\\.|[^"\\]){20,2000})"', html)
    titles = re.findall(r'"title"\s*:\s*\{\s*"runs"\s*:\s*\[\s*\{\s*"text"\s*:\s*"((?:\\.|[^"\\]){3,240})"', html)
    return {
        "channel_id": channel_id,
        "owner_name": _clean_json_text(owner),
        "channel_description": _clean_json_text(descriptions[0]) if descriptions else "",
        "recent_content": list(dict.fromkeys(_clean_json_text(value) for value in titles))[:12],
    }


CATEGORY_TERMS = {
    "Food & Cooking": {"food","recipe","cooking","restaurant","biryani","chicken","kitchen","chef","streetfood","cuisine","eat"},
    "Technology": {"technology","tech","ai","software","gadget","phone","computer","digital","app","coding"},
    "Business & Finance": {"business","finance","marketing","sales","entrepreneur","founder","founders","investment","money","startup","commerce","ecommerce","conversion","store"},
    "Travel & Places": {"travel","tour","trip","hotel","destination","places","vlog","vacation"},
    "Entertainment": {"movie","cinema","music","comedy","celebrity","entertainment","show","reaction"},
    "Education": {"education","learn","tutorial","course","student","teaching","guide","explained"},
    "Health & Fitness": {"health","fitness","workout","wellness","medical","nutrition","gym"},
    "Beauty & Fashion": {"beauty","fashion","makeup","style","skincare","clothing"},
    "Home & Design": {"home","interior","design","decor","architecture","furniture","granite"},
    "Gaming": {"gaming","game","gamer","esports","playstation","xbox"},
}


def _category(words: list[str]) -> tuple[str, int]:
    counts={name:sum(words.count(term) for term in terms) for name,terms in CATEGORY_TERMS.items()}
    name,score=max(counts.items(),key=lambda item:item[1])
    return (name,score) if score else ("General content",0)


def _analyse(url: str, html: str) -> dict[str, Any]:
    parser=PageSignals(); parser.feed(html)
    host=(urlparse(url).hostname or "").casefold()
    youtube=_youtube_signals(html) if "youtube.com" in host else {}
    recent=youtube.get("recent_content",[])
    text=" ".join([*parser.text, parser.keywords, youtube.get("channel_description",""), *recent])[:300_000]
    words=[w for w in re.findall(r"[a-z][a-z0-9-]{2,}",text.casefold()) if w not in STOP]
    themes=[word for word,_ in Counter(words).most_common(12)]
    combined=" ".join([parser.title,parser.description,*parser.headings[:8]]).strip()
    tone=[]
    lower=text.casefold()
    for label,terms in {"professional":["expert","professional","solutions","industry"],"educational":["learn","guide","how to","insights","review"],"energetic":["exciting","celebration","fast","power","transform"],"friendly":["welcome","community","together","help","vlog","living"]}.items():
        if any(term in lower for term in terms): tone.append(label)
    category,category_score=_category(words)
    brand_name=youtube.get("owner_name") or parser.author or re.sub(r"\s*[-|–].*$", "", parser.title).strip()
    description=youtube.get("channel_description") or parser.description
    audience_map={"Food & Cooking":"food lovers, home cooks, and restaurant explorers","Technology":"technology enthusiasts, creators, and digital professionals","Business & Finance":"business owners, founders, and growth-focused professionals","Travel & Places":"travelers and destination explorers","Entertainment":"entertainment audiences and pop-culture followers","Education":"learners seeking practical guidance","Health & Fitness":"health-conscious and fitness-focused audiences","Beauty & Fashion":"beauty and style audiences","Home & Design":"homeowners, designers, and renovation audiences","Gaming":"gamers and gaming communities"}
    return {"url":url,"title":parser.title,"brand_name":brand_name,"description":description,"image_url":parser.image,"channel_id":youtube.get("channel_id",""),"recent_content":recent,"category":category,"category_score":category_score,"suggested_audience":audience_map.get(category,"people interested in " + ", ".join(themes[:3])),"positioning_evidence":combined[:1200],"content_themes":themes,"interests":themes[:8],"voice_signals":tone or ["not confidently detected"],"heading_samples":parser.headings[:8],"text_characters_analyzed":len(text)}


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
    categories=Counter(s.get("category") for s in analyzed if s.get("category"))
    category=categories.most_common(1)[0][0] if categories else "Unknown"
    brand_name=next((s.get("brand_name") for s in analyzed if s.get("brand_name")),"")
    audiences=list(dict.fromkeys(s.get("suggested_audience") for s in analyzed if s.get("suggested_audience")))
    recent=list(dict.fromkeys(item for source in analyzed for item in source.get("recent_content",[])))[:12]
    hashtags=["#"+re.sub(r"[^A-Za-z0-9]","",theme.title()) for theme in themes[:8] if theme]
    confidence="high" if len(analyzed)>1 else "medium" if analyzed else "none"
    offer=(descriptions[0] if descriptions else (f"{category} content focused on {', '.join(themes[:5])}" if themes else ""))[:500]
    return {"status":"draft_requires_confirmation","sources":sources,"draft":{"brand_name":brand_name,"identity_type":"creator" if any(s.get("source_type")=="social" for s in analyzed) else "business","category":category,"positioning":offer,"products_services":[offer] if offer else [],"audiences":audiences,"content_themes":themes,"areas_of_interest":themes[:10],"voice":voices,"keywords":themes[:12],"hashtags":hashtags,"recent_content":recent,"confidence":confidence},"disclosure":"This is evidence-based extraction, not a verified fact. The customer must review and confirm every field."}
