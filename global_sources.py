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
    "from", "with", "for", "and", "or", "in", "of", "to", "as", "at", "on", "by",
    "how", "why", "what", "when", "where", "who",
    "age", "become", "becomes", "becoming", "interrupt", "interrupts", "interrupted",
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

_COMPANY_BRANDS = (
    ("Accenture", ("accenture", "acn stock", "acn"), "Company", "accenture.com", ""),
    ("SAIC", ("science applications international corporation", "saic"), "Company", "saic.com", ""),
    ("Thomson Reuters", ("thomson reuters",), "Company", "thomsonreuters.com", ""),
    ("CloudEQ", ("cloudeq",), "Company", "cloudeq.com", ""),
    ("Bannerbear", ("bannerbear",), "Company", "bannerbear.com", ""),
    ("Kingfisher Learning Trust", ("kingfisher learning trust",), "Organization", "kingfisherlearningtrust.co.uk", ""),
    ("Bloomberg", ("bloomberg",), "Company", "bloomberg.com", ""),
    ("LexisNexis", ("lexisnexis", "lexis nexis"), "Company", "lexisnexis.com", ""),
    ("Wolters Kluwer", ("wolters kluwer",), "Company", "wolterskluwer.com", ""),
    ("Booz Allen Hamilton", ("booz allen hamilton", "booz allen"), "Company", "boozallen.com", ""),
    ("Leidos", ("leidos",), "Company", "leidos.com", ""),
    ("CACI", ("caci international", "caci"), "Company", "caci.com", ""),
    ("Kyndryl", ("kyndryl",), "Company", "kyndryl.com", ""),
    ("DXC Technology", ("dxc technology",), "Company", "dxc.com", ""),
    ("Canva", ("canva",), "Company", "canva.com", ""),
    ("Adobe Express", ("adobe express",), "Product brand", "adobe.com/express", ""),
    ("Placid", ("placid app",), "Product brand", "placid.app", ""),
    ("Anthropic", ("anthropic", "claude ai"), "Company", "anthropic.com", ""),
    ("Hexaware", ("hexaware",), "Company", "hexaware.com", ""),
    ("Infosys", ("infosys",), "Company", "infosys.com", ""),
    ("Wipro", ("wipro",), "Company", "wipro.com", ""),
    ("Cognizant", ("cognizant",), "Company", "cognizant.com", ""),
    ("TagMango", ("tagmango",), "Company", "tagmango.com", ""),
    ("Graphy", ("graphy",), "Company", "graphy.com", ""),
    ("Nas.io", ("nas.io", "nas io"), "Company", "nas.io", ""),
    ("Patreon", ("patreon",), "Company", "patreon.com", ""),
    ("Hevo Data", ("hevo data", "hevo"), "Company", "hevodata.com", ""),
    ("Fivetran", ("fivetran",), "Company", "fivetran.com", ""),
    ("Airbyte", ("airbyte",), "Company", "airbyte.com", ""),
    ("Apple", ("apple",), "Company", "apple.com", "apple"),
    ("App Store", ("app store",), "Product brand", "apple.com/app-store", "appstore"),
    ("Spotify", ("spotify",), "Company", "spotify.com", "spotify"),
    ("Nvidia", ("nvidia",), "Company", "nvidia.com", "nvidia"),
    ("Microsoft", ("microsoft",), "Company", "microsoft.com", "microsoft"),
    ("Azure", ("microsoft azure", "azure"), "Product brand", "azure.microsoft.com", "microsoftazure"),
    ("OpenAI", ("openai", "chatgpt"), "Company", "openai.com", "openai"),
    ("Google", ("google",), "Company", "google.com", "google"),
    ("Alphabet", ("alphabet inc", "alphabet"), "Company", "abc.xyz", "alphabet"),
    ("Meta", ("meta platforms", "meta"), "Company", "meta.com", "meta"),
    ("Facebook", ("facebook",), "Product brand", "facebook.com", "facebook"),
    ("Instagram", ("instagram",), "Product brand", "instagram.com", "instagram"),
    ("WhatsApp", ("whatsapp",), "Product brand", "whatsapp.com", "whatsapp"),
    ("Amazon", ("amazon",), "Company", "amazon.com", "amazon"),
    ("AWS", ("amazon web services", "aws"), "Product brand", "aws.amazon.com", "amazonwebservices"),
    ("Tesla", ("tesla",), "Company", "tesla.com", "tesla"),
    ("Samsung", ("samsung",), "Company", "samsung.com", "samsung"),
    ("TikTok", ("tiktok",), "Product brand", "tiktok.com", "tiktok"),
    ("ByteDance", ("bytedance",), "Company", "bytedance.com", "bytedance"),
    ("Netflix", ("netflix",), "Company", "netflix.com", "netflix"),
    ("Disney", ("walt disney", "disney"), "Company", "thewaltdisneycompany.com", "disney"),
    ("Coca-Cola", ("coca-cola", "coca cola", "coke"), "Brand", "coca-cola.com", "cocacola"),
    ("Pepsi", ("pepsico", "pepsi"), "Brand", "pepsi.com", "pepsi"),
    ("Nike", ("nike",), "Brand", "nike.com", "nike"),
    ("Adidas", ("adidas",), "Brand", "adidas.com", "adidas"),
    ("Uber", ("uber",), "Company", "uber.com", "uber"),
    ("Airbnb", ("airbnb",), "Company", "airbnb.com", "airbnb"),
    ("Walmart", ("walmart",), "Company", "walmart.com", "walmart"),
    ("Alibaba", ("alibaba",), "Company", "alibaba.com", "alibabadotcom"),
    ("Temu", ("temu",), "Brand", "temu.com", "temu"),
    ("Shein", ("shein",), "Brand", "shein.com", "shein"),
    ("X", ("twitter", "x corp", "x platform"), "Product brand", "x.com", "x"),
    ("LinkedIn", ("linkedin",), "Product brand", "linkedin.com", "linkedin"),
    ("Intel", ("intel",), "Company", "intel.com", "intel"),
    ("AMD", ("advanced micro devices", "amd"), "Company", "amd.com", "amd"),
    ("Qualcomm", ("qualcomm",), "Company", "qualcomm.com", "qualcomm"),
    ("Oracle", ("oracle",), "Company", "oracle.com", "oracle"),
    ("Salesforce", ("salesforce",), "Company", "salesforce.com", "salesforce"),
    ("Adobe", ("adobe",), "Company", "adobe.com", "adobe"),
    ("IBM", ("international business machines", "ibm"), "Company", "ibm.com", "ibm"),
    ("Sony", ("sony",), "Company", "sony.com", "sony"),
    ("Nintendo", ("nintendo",), "Company", "nintendo.com", "nintendo"),
    ("Xbox", ("xbox",), "Product brand", "xbox.com", "xbox"),
)

_COMPETITIVE_RELATIONSHIPS = {
    "Thomson Reuters": (("Bloomberg", "Competitor", "Professional information and financial-data competitor"), ("LexisNexis", "Competitor", "Legal research and information competitor"), ("Wolters Kluwer", "Competitor", "Legal, tax, and professional-information competitor")),
    "Accenture": (("Booz Allen Hamilton", "Competitor", "Technology consulting competitor"), ("Leidos", "Competitor", "Government technology and services competitor"), ("CACI", "Competitor", "Government IT services competitor")),
    "SAIC": (("Leidos", "Competitor", "Government technology and defense-services competitor"), ("Booz Allen Hamilton", "Competitor", "Government consulting competitor"), ("CACI", "Competitor", "Federal IT services competitor")),
    "CloudEQ": (("Accenture", "Competitor", "Cloud transformation and managed-services competitor"), ("Kyndryl", "Competitor", "Enterprise infrastructure-services competitor"), ("DXC Technology", "Competitor", "Enterprise IT services competitor")),
    "Bannerbear": (("Canva", "Competitor", "Automated visual-content platform competitor"), ("Adobe Express", "Competitor", "Template-based content creation competitor"), ("Placid", "Competitor", "Creative automation competitor")),
    "Anthropic": (("OpenAI", "Competitor", "Foundation-model and AI assistant competitor"), ("Google", "Competitor", "Foundation-model competitor"), ("Microsoft", "Competitor", "Enterprise generative-AI competitor")),
    "Hexaware": (("Infosys", "Competitor", "Global IT services competitor"), ("Wipro", "Competitor", "Technology consulting competitor"), ("Cognizant", "Competitor", "Digital services competitor")),
    "TagMango": (("Graphy", "Competitor", "Creator monetization and course-platform competitor"), ("Nas.io", "Competitor", "Community and creator-business competitor"), ("Patreon", "Competitor", "Creator membership competitor")),
    "Hevo Data": (("Fivetran", "Competitor", "Managed data-pipeline competitor"), ("Airbyte", "Competitor", "Data integration competitor")),
}

_CATEGORY_LANDSCAPES = {
    "Fashion, Apparel & Luxury": (("Nike", "nike.com"), ("Adidas", "adidas.com"), ("LVMH", "lvmh.com")),
    "Beauty, Personal Care & Lifestyle": (("L'Oréal", "loreal.com"), ("Estée Lauder", "elcompanies.com"), ("Sephora", "sephora.com")),
    "Home, Household & Consumer Products": (("IKEA", "ikea.com"), ("Procter & Gamble", "pg.com"), ("Unilever", "unilever.com")),
    "Food, Beverage & Hospitality": (("Nestlé", "nestle.com"), ("Coca-Cola", "coca-cola.com"), ("McDonald's", "mcdonalds.com")),
    "Health, Medicine & Longevity": (("Pfizer", "pfizer.com"), ("Johnson & Johnson", "jnj.com"), ("Roche", "roche.com")),
    "Technology, AI & DeepTech": (("Nvidia", "nvidia.com"), ("Microsoft", "microsoft.com"), ("Google", "google.com")),
    "Apps, Software & Enterprise Products": (("Microsoft", "microsoft.com"), ("Salesforce", "salesforce.com"), ("Oracle", "oracle.com")),
    "Gaming": (("Sony", "sony.com"), ("Nintendo", "nintendo.com"), ("Xbox", "xbox.com")),
    "Finance, Banking & Investment": (("JPMorgan Chase", "jpmorganchase.com"), ("Goldman Sachs", "goldmansachs.com"), ("Visa", "visa.com")),
    "Business, Entrepreneurship & SMB": (("Shopify", "shopify.com"), ("Intuit", "intuit.com"), ("HubSpot", "hubspot.com")),
    "Careers, Skills & Professional Development": (("LinkedIn", "linkedin.com"), ("Coursera", "coursera.org"), ("Udemy", "udemy.com")),
    "Education & Knowledge": (("Pearson", "pearson.com"), ("Coursera", "coursera.org"), ("Khan Academy", "khanacademy.org")),
    "Professional Communities": (("LinkedIn", "linkedin.com"), ("Reddit", "reddit.com"), ("Stack Overflow", "stackoverflow.com")),
    "Industrial & B2B Industries": (("Siemens", "siemens.com"), ("Honeywell", "honeywell.com"), ("Caterpillar", "caterpillar.com")),
    "Automotive & Mobility": (("Toyota", "toyota.com"), ("Tesla", "tesla.com"), ("BYD", "byd.com")),
    "Entertainment, Media & Creator Content": (("Disney", "thewaltdisneycompany.com"), ("Netflix", "netflix.com"), ("Warner Bros. Discovery", "wbd.com")),
    "Arts, Crafts & Creative": (("Adobe", "adobe.com"), ("Canva", "canva.com"), ("Etsy", "etsy.com")),
    "Sports": (("ESPN", "espn.com"), ("Nike", "nike.com"), ("Adidas", "adidas.com")),
    "Travel, Tourism & Events": (("Booking.com", "booking.com"), ("Airbnb", "airbnb.com"), ("Expedia", "expediagroup.com")),
    "Government, Politics, Legal & Social Impact": (("United Nations", "un.org"), ("Amnesty International", "amnesty.org"), ("Human Rights Watch", "hrw.org")),
    "Religion, Spirituality, Culture & Demographic Interests": (("YouTube", "youtube.com"), ("Meta", "meta.com"), ("TikTok", "tiktok.com")),
    "Real-Time & High-Velocity Categories": (("Reuters", "reuters.com"), ("Associated Press", "apnews.com"), ("BBC", "bbc.com")),
}


def _catalog_entity(name: str, relation: str, explanation: str) -> dict[str, Any] | None:
    for catalog_name, aliases, kind, domain, icon in _COMPANY_BRANDS:
        if catalog_name != name:
            continue
        return {
            "name": catalog_name, "kind": kind, "relation": relation, "confidence": 90,
            "official_domain": domain,
            "logo_url": f"https://www.google.com/s2/favicons?domain_url=https://{domain}&sz=128",
            "explanation": explanation,
        }
    return None


def _competitive_landscape(entities: list[dict[str, Any]], super_category: str = "") -> tuple[list[dict[str, Any]], str]:
    primary_order = list(dict.fromkeys(str(entity.get("name", "")) for entity in entities if entity.get("name")))
    primary_names = set(primary_order)
    landscape: list[dict[str, Any]] = []
    seen = set(primary_names)
    for primary in primary_order:
        for name, relation, explanation in _COMPETITIVE_RELATIONSHIPS.get(primary, ()):
            if name in seen:
                continue
            entity = _catalog_entity(name, relation, explanation)
            if entity:
                landscape.append(entity)
                seen.add(name)
            if len(landscape) == 3:
                return landscape, "Direct competitors and related entities"
    if landscape:
        return landscape, "Direct competitors and related entities"
    category_context = []
    for name, domain in _CATEGORY_LANDSCAPES.get(super_category, ()):
        category_context.append({
            "name": name, "kind": "Category reference", "relation": "Category leader", "confidence": 85,
            "official_domain": domain,
            "logo_url": f"https://www.google.com/s2/favicons?domain_url=https://{domain}&sz=128",
            "explanation": f"Verified reference entity in {super_category}; not necessarily a direct competitor in this story",
        })
    return category_context, "Category leaders and comparable entities"


def _key_company_entities(title: str, summary: str, entity_type: str) -> list[dict[str, Any]]:
    """Return up to three clearly mentioned companies or brands, ranked by story relevance."""
    title_text = " ".join(title.split())
    combined = f"{title_text} {summary}".lower()
    title_lower = title_text.lower()
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for name, aliases, kind, domain, icon in _COMPANY_BRANDS:
        positions = [match.start() for alias in aliases for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", combined)]
        if not positions:
            continue
        in_title = any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", title_lower) for alias in aliases)
        position = min(positions)
        matches.append((0 if in_title else 1, position, {
            "name": name,
            "kind": kind,
            "relation": "",
            "confidence": 0,
            "official_domain": domain,
            "logo_url": f"https://www.google.com/s2/favicons?domain_url=https://{domain}&sz=128",
        }))
    matches.sort(key=lambda entry: (entry[0], entry[1]))
    entities = [entry[2] for entry in matches[:3]]
    for index, entity in enumerate(entities):
        entity["relation"] = "Product brand" if "brand" in entity["kind"].lower() else ("Primary company" if index == 0 else "Related company")
        entity["confidence"] = 98 if index == 0 else 91 if index == 1 else 76
    return entities


def _source_media_entity(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Use source media for a confidently typed non-company subject; never guess a company logo."""
    entity_type = str(item.get("entity_type_label", ""))
    source_image = str(item.get("image", ""))
    if not source_image.startswith(("http://", "https://")):
        return []
    if not any(kind in entity_type.lower() for kind in ("person", "celebrity", "product", "movie", "tv show", "event")):
        return []
    name = _entity_label(item.get("topic", ""), item.get("youtube_search_topic", ""))
    bad_words = {"which", "how", "why", "what", "services", "latest", "update", "news", "review"}
    words = {word.lower().strip(".,:;?!") for word in name.split()}
    if not name or words & bad_words:
        return []
    return [{
        "name": name,
        "kind": entity_type,
        "relation": "Primary subject",
        "confidence": 82,
        "official_domain": "",
        "logo_url": "",
        "image_url": source_image,
    }]


def _reputation_label(title: str, summary: str = "") -> tuple[str, list[str]]:
    """Return an explainable editorial signal label, not a factual verdict."""
    text = f"{title} {summary}".lower()
    contains = lambda signal: bool(re.search(rf"(?<!\w){re.escape(signal)}(?!\w)", text))
    positive = [signal for signal in _POSITIVE_REPUTATION_SIGNALS if contains(signal)]
    negative = [signal for signal in _NEGATIVE_REPUTATION_SIGNALS if contains(signal)]
    mixed = [signal for signal in _MIXED_REPUTATION_SIGNALS if contains(signal)]
    if mixed or (positive and negative):
        return "Mixed / debate", list(dict.fromkeys((mixed + positive + negative)[:4]))
    if negative:
        return "Bad news", negative[:4]
    if positive:
        return "Good news", positive[:4]
    return "Neutral", ["No strong positive or negative wording detected"]


def _entity_label(title: str, youtube_topic: str = "") -> str:
    """Extract the concise entity portion already used by the YouTube topic."""
    concise = " ".join((youtube_topic or title).split()[:5]).strip()
    endings = (
        " data leak", " security flaw", " account lockout", " scam controversy",
        " lawsuit", " regulatory action", " outage", " controversy", " complaints",
        " latest update", " explained", " news update",
    )
    lowered = concise.lower()
    for ending in endings:
        if lowered.endswith(ending):
            concise = concise[:-len(ending)].strip()
            break
    return concise or "General subject"


def _detected_entity_type(title: str, summary: str, category: str, selected_type: str) -> tuple[str, str]:
    if selected_type and selected_type.lower() != "everything":
        return selected_type, "selected entity-type filter"
    text = f"{title} {summary}".lower()
    category_text = category.lower()
    rules = (
        ("Movie / TV show", ("movie", "film", "trailer", "box office", "tv show", "series", "episode", "netflix", "cinema")),
        ("App / Software", (" app ", "application", "software", "saas", "platform update", "mobile app")),
        ("Government", ("government", "ministry", "minister", "parliament", "congress", "senate", "president", "governor", "mayor", "regulator")),
        ("Country / Region", ("country", "nation", "border", "capital city", "foreign policy")),
        ("Person / Celebrity", ("celebrity", "actor", "actress", "singer", "rapper", "influencer", "creator", "athlete", "player", "coach")),
        ("Product", ("product", "device", "smartphone", "laptop", "vehicle", "car model", "launches new", "unveils new", "recall")),
        ("Event", ("event", "conference", "festival", "tournament", "championship", "summit", "expo", "election", "match")),
        ("Organization", ("organization", "association", "university", "school", "hospital", "nonprofit", "charity", "foundation")),
        ("Company / Brand", ("company", "brand", "ceo", "startup", "business", "earnings", "stock", "shares", "acquisition", "merger", "ipo")),
    )
    padded = f" {text} "
    for label, signals in rules:
        matched = next((signal.strip() for signal in signals if signal in padded), "")
        if matched:
            return label, f"detected from '{matched}'"
    category_rules = (
        ("App / Software", ("app", "software", "saas")),
        ("Movie / TV show", ("movie", "television", "streaming", "entertainment")),
        ("Person / Celebrity", ("celebrity", "creator", "influencer")),
        ("Government", ("government", "politics", "legal")),
        ("Product", ("product", "automotive", "device", "electronics")),
        ("Company / Brand", ("business", "brand", "startup", "finance", "industry")),
        ("Event", ("event", "sports", "travel")),
    )
    for label, signals in category_rules:
        matched = next((signal for signal in signals if signal in category_text), "")
        if matched:
            return label, f"inferred from category '{category}'"
    return "General topic", "no confident entity-type signal"


def annotate_topic_taxonomy(
    topics: list[dict[str, Any]], categories: list[str], super_category: str = "", entity_type: str = ""
) -> list[dict[str, Any]]:
    """Attach explainable category and entity labels to discovered topics."""
    ignored = {"and", "or", "the", "of", "in", "for", "to", "products", "services", "general", "other"}
    category_tokens = {
        category: {word for word in re.findall(r"[a-z0-9]+", category.lower()) if len(word) > 1 and word not in ignored}
        for category in categories
    }
    ambiguous_context = {
        "watches": {"fashion", "luxury", "style", "wearable", "smartwatch", "rolex", "timepiece", "jewelry", "accessory", "collection"},
    }
    annotated = []
    for item in topics:
        text = f"{item.get('topic', '')} {item.get('summary', '')}".lower()
        text_tokens = set(re.findall(r"[a-z0-9]+", text))
        scores = []
        for category, tokens in category_tokens.items():
            category_key = category.lower().strip()
            score = len(tokens & text_tokens)
            if category_key in text:
                score += 10
            if category_key in ambiguous_context:
                category_aliases = {category_key, category_key.removesuffix("es")}
                if not (ambiguous_context[category_key] & text_tokens):
                    score = 0
                elif category_aliases & text_tokens:
                    score += 20
            scores.append((score, category))
        scored = sorted(scores, key=lambda pair: (pair[0], len(pair[1])), reverse=True)
        best_score, best_category = scored[0] if scored else (0, "")
        if len(categories) == 1:
            best_category, best_score = categories[0], max(1, best_score)
        elif not best_score:
            # Broad searches can produce homonyms such as weather "watches" for
            # Fashion > Watches. Exclude results with no category evidence.
            continue
        item["category_label"] = best_category if best_score else f"{super_category} — General"
        item["category_match"] = "keyword match" if best_score else "super-category fallback"
        item["entity_label"] = _entity_label(item.get("topic", ""), item.get("youtube_search_topic", ""))
        item["entity_type_label"], item["entity_type_match"] = _detected_entity_type(
            item.get("topic", ""), item.get("summary", ""), item["category_label"], entity_type
        )
        item["key_entities"] = _key_company_entities(
            item.get("topic", ""), item.get("summary", ""), item["entity_type_label"]
        )
        if not item["key_entities"]:
            item["key_entities"] = _source_media_entity(item)
        item["competitive_landscape"], item["competitive_landscape_label"] = _competitive_landscape(
            item["key_entities"], super_category
        )
        annotated.append(item)
    return annotated


def _youtube_search_terms(title: str) -> tuple[str, list[str]]:
    """Create an entity-led YouTube query of no more than five words."""
    clean = " ".join(str(title).split())
    clean = re.sub(
        r"^(?:opinion|editorial|analysis|commentary|review|explainer|deep\s+dive)\s*(?:\||:|[-–—])\s*",
        "", clean, flags=re.IGNORECASE,
    ).strip()
    lower = clean.lower()
    issue = ""
    def has_issue(needle: str) -> bool:
        if needle in {"vulnerabil", "penalt", "controvers"}:
            return needle in lower
        return bool(re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", lower))
    for needles, label in (
        (("data breach", "data leak", "exposed", "leaking user data"), "data leak"),
        (("vulnerabil", "security flaw", "security bug", "hijack"), "security flaw"),
        (("locked out", "locks out", "review freeze", "account ban"), "account lockout"),
        (("fake", "scam", "fraud", "stolen"), "scam controversy"),
        (("lawsuit", "sued", "sues", "class action"), "lawsuit"),
        (("fine", "penalt", "regulatory action", "investigation"), "regulatory action"),
        (("outage", "offline", "went down", "service disruption"), "outage"),
        (("backlash",), "backlash"),
        (("criticism",), "criticism"),
        (("controvers",), "controversy"),
        (("complaint", "bad review", "subscription charge", "pricing"), "complaints"),
    ):
        if any(has_issue(needle) for needle in needles):
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

    if not issue:
        entity_words = {word.lower().strip(" -:,.')(") for word in entity.split()}
        filler = _ENTITY_NOISE | {"is", "are", "was", "were", "has", "have", "had", "will", "its", "this", "that", "as", "at", "on", "by", "new", "latest", "update", "news", "powerful"}
        meaningful = []
        keyword_source = re.sub(r"\bartificial intelligence\b", "AI", clean, flags=re.IGNORECASE)
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+&-]*", keyword_source):
            normalized = word.lower().strip(" -:,.')(")
            if normalized in filler or normalized in entity_words or len(normalized) < 2:
                continue
            if normalized not in {item.lower() for item in meaningful}:
                meaningful.append(word.strip(" -:,.')("))
            if len(meaningful) >= 3:
                break
        issue = " ".join(meaningful)

    max_entity_words = max(1, 5 - len(issue.split()))
    entity = " ".join(entity.split()[:max_entity_words])
    primary = " ".join(f"{entity} {issue}".split()[:5]).strip()
    return primary, []


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
                    raw_description = item.findtext("description", "") or ""
                    image_match = re.search(r'<img[^>]+src=["\']([^"\']+)', raw_description, re.IGNORECASE)
                    image_url = html.unescape(image_match.group(1)) if image_match else ""
                    description = html.unescape(re.sub(r"<[^>]+>", " ", raw_description))
                    description = " ".join(description.split())
                    found.append(record(title, search_query, f"Google News {country}", item.findtext("link", ""), published, 1, description, image_url))
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
                    record(item.get("title", ""), search_query, "GDELT Worldwide", item.get("url", ""), parse_date(item.get("seendate")), 1, "", item.get("socialimage", ""))
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
            if not existing.get("image") and item.get("image"):
                existing["image"] = item["image"]
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
    summary: str = "", image_url: str = "",
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
        "image": image_url if str(image_url).lower().startswith(("http://", "https://")) else "",
    }
