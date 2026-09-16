from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


SCENE_TYPES = (
    "UI_ANIMATION", "CHARACTER_IDLE", "PRODUCT", "PORTRAIT", "GAMING",
    "CINEMATIC", "AUTOMOTIVE", "BEAUTY", "TECH", "NEWS", "FINANCE",
    "LANDSCAPE", "ENVIRONMENT", "MECHANICAL_OBJECT", "ABSTRACT", "ACTION",
)

KEYWORDS: dict[str, tuple[str, ...]] = {
    "UI_ANIMATION": ("interface", "dashboard", "music player", "app screen", "ui ", "progress bar", "button", "menu", "hud"),
    "GAMING": ("gaming", "game", "moba", "rpg", "hero selection", "character selection", "playstation", "xbox", "esports"),
    "AUTOMOTIVE": ("car", "automotive", "vehicle", "motorcycle", "truck", "road", "driving"),
    "BEAUTY": ("beauty", "cosmetic", "skincare", "makeup", "fragrance", "perfume"),
    "FINANCE": ("finance", "bank", "market", "stock", "trading", "investment", "crypto"),
    "NEWS": ("news", "breaking", "report", "journalism", "headline"),
    "TECH": ("technology", "software", "ai ", "platform", "chip", "device", "computer", "smartphone"),
    "PORTRAIT": ("portrait", "headshot", "face", "person", "model", "creator", "presenter"),
    "PRODUCT": ("product", "commercial", "advertisement", "packaging", "bottle", "watch", "phone", "shoe"),
    "MECHANICAL_OBJECT": ("vinyl", "record", "turntable", "gear", "clock", "machine", "mechanical"),
    "LANDSCAPE": ("landscape", "mountain", "ocean", "forest", "desert", "nature"),
    "ENVIRONMENT": ("city", "street", "room", "stadium", "interior", "architecture", "environment"),
    "ABSTRACT": ("abstract", "surreal", "particle", "geometric", "dreamlike"),
    "ACTION": ("action", "fight", "battle", "explosion", "chase", "sprint", "combat"),
    "CHARACTER_IDLE": ("character", "warrior", "hero", "mage", "athlete", "player", "avatar"),
    "CINEMATIC": ("cinematic", "film", "story", "documentary", "dramatic"),
}

PRIORITY = ("UI_ANIMATION", "GAMING", "AUTOMOTIVE", "BEAUTY", "FINANCE", "NEWS", "TECH", "PRODUCT", "PORTRAIT", "MECHANICAL_OBJECT", "ACTION", "CHARACTER_IDLE", "LANDSCAPE", "ENVIRONMENT", "ABSTRACT", "CINEMATIC")


@dataclass
class MotionLayer:
    name: str
    category: str
    intensity: str
    motion: str
    anchor: str = "composition"
    relationship: str = "independent"
    cause: str = "natural scene motion"


@dataclass
class MotionPlan:
    generation_type: str
    scene_type: str
    subject: str
    intent: str
    duration: int
    preservation_map: dict[str, str]
    layers: list[MotionLayer]
    relationship_graph: list[str]
    cause_effect_graph: list[str]
    camera: dict[str, str]
    motion_budget: int
    loop_strategy: str
    negative_constraints: list[str]
    quality_mode: bool
    source_content: str = ""
    core_subject: str = ""
    secondary_subjects: list[str] = field(default_factory=list)
    content_intent: str = ""
    category: str = "General"
    visualizable_information: list[str] = field(default_factory=list)
    non_visual_information: list[str] = field(default_factory=list)
    interaction_information: list[str] = field(default_factory=list)
    brand_entities: list[str] = field(default_factory=list)
    people_entities: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    important_exact_text: list[str] = field(default_factory=list)
    important_numbers: list[str] = field(default_factory=list)
    candidate_visual_concepts: list[str] = field(default_factory=list)
    selected_visual_concept: str = ""
    visual_action_candidates: list[str] = field(default_factory=list)
    concrete_visual_action: str = ""
    action_validation: dict[str, Any] = field(default_factory=dict)
    creative_style: str = ""
    semantic_validation: dict[str, Any] = field(default_factory=dict)
    final_prompt: str = ""

    def debug(self) -> dict[str, Any]:
        data = asdict(self)
        data["object_layer_map"] = {layer.name: layer.intensity for layer in self.layers}
        data["motion_intensity"] = {layer.name: layer.intensity for layer in self.layers}
        data["primary_motion"] = [asdict(layer) for layer in self.layers if layer.category == "primary"]
        data["secondary_motion"] = [asdict(layer) for layer in self.layers if layer.category in {"secondary", "reactive", "optional"}]
        data["locked_objects"] = [layer.name for layer in self.layers if layer.category == "locked"]
        data["camera_mode"] = self.camera["level"]
        data["final_pixverse_prompt"] = self.final_prompt
        return data


def _clean(value: Any, limit: int = 60) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" .:-")
    return " ".join(value.split()[:limit])


def _content_text(content: dict[str, Any], user_prompt: str = "") -> str:
    values = [user_prompt]
    for key in ("topic", "suggested_title", "hook", "category", "entity_type_label", "video_idea", "creator_angle", "why_it_matters", "product", "brand", "company"):
        values.append(str(content.get(key) or ""))
    return " ".join(values).lower()


GROUNDING_PROFILES: tuple[dict[str, Any], ...] = (
    {"category":"Food / Seafood","keywords":("prawn","prawns","shrimp","seafood","lobster","crab","shellfish"),"style":"premium seafood commercial"},
    {"category":"Food / Confectionery","keywords":("chocolate","wonka","candy","confectionery","dessert","truffle","praline"),"style":"premium food commercial"},
    {"category":"Gaming","keywords":("gaming","game","playstation","xbox","moba","esports","console","hero","player"),"style":"premium gaming commercial"},
    {"category":"Automotive","keywords":("car","automotive","vehicle","motorcycle","driving","road","launch"),"style":"premium automotive commercial"},
    {"category":"Beauty / Product","keywords":("perfume","fragrance","beauty","cosmetic","skincare","makeup"),"style":"luxury beauty commercial"},
    {"category":"Finance / Business","keywords":("stock market","stocks","trading","finance","banking","earnings","investment","investor"),"style":"financial editorial"},
    {"category":"Technology / Business","keywords":("artificial intelligence"," ai ","technology","software","chip","platform","startup","tech company"),"style":"technology business editorial"},
    {"category":"News","keywords":("breaking news","news update","report","journalism"),"style":"editorial documentary"},
    {"category":"Fashion","keywords":("fashion","clothing","silk","outfit","apparel"),"style":"fashion editorial"},
    {"category":"Sports","keywords":("football","soccer","match","league","tournament","athlete","stadium","wrestling","wwe","wweraw","wrestler","arena ring","takedown"),"style":"sports documentary"},
    {"category":"UI / Interface","keywords":("interface","dashboard","music player","app screen","progress bar","playback controls"," ui "),"style":"clean interface animation"},
)

NON_VISUAL_TERMS = ("history", "significance", "fun fact", "trivia", "flavor description", "background information", "analysis")
INTERACTION_TERMS = ("poll", "comments", "comment", "subscribe", "call to action", "cta", "like and share")
VISUAL_TERMS = (
    "chocolate", "assortment", "tasting", "break", "texture", "filling", "prawn", "shrimp", "seafood", "shellfish", "pan", "tongs", "hand", "bottle", "perfume", "product",
    "car", "vehicle", "road", "wheel", "character", "hero", "game", "interface", "vinyl", "record", "person",
    "portrait", "phone", "computer", "chip", "office", "market", "city", "landscape", "water", "fire", "smoke",
)


def _source_content(content: dict[str, Any], user_prompt: str = "") -> str:
    ordered = []
    for key in ("topic", "suggested_title", "hook", "video_idea", "creator_angle", "why_it_matters", "category", "entity_type_label", "brand", "company", "product", "location"):
        value = _clean(content.get(key), 180)
        if value and value not in ordered:
            ordered.append(value)
    if user_prompt:
        ordered.append(_clean(user_prompt, 180))
    return ". ".join(ordered)


def _terms_present(text: str, terms: tuple[str, ...]) -> list[str]:
    lower = f" {text.lower()} "
    return [term for term in terms if term in lower]


def _ground_content(content: dict[str, Any], duration: int, user_prompt: str = "") -> dict[str, Any]:
    source = _source_content(content, user_prompt)
    lower = f" {source.lower()} "
    scored = []
    for profile in GROUNDING_PROFILES:
        hits = [term for term in profile["keywords"] if term in lower]
        scored.append((len(hits), profile, hits))
    score, profile, category_hits = max(scored, key=lambda item: item[0])
    if not score:
        profile = {"category":"General / Editorial","style":"realistic editorial"}
        category_hits = []
    # Technology plus investment describes a technology business unless the subject is explicitly the stock market.
    if any(term in lower for term in ("artificial intelligence", " ai ", "technology", "software", "chip", "platform")) and "stock market" not in lower and "stocks" not in lower:
        profile = next(item for item in GROUNDING_PROFILES if item["category"] == "Technology / Business")
    topic = _clean(content.get("topic") or content.get("suggested_title") or content.get("hook"), 22)
    if profile["category"] == "Food / Seafood":
        core = topic or "seafood cooking technique"
        intent = "demonstrate one specific seafood cooking technique and present the finished result"
    elif profile["category"] == "Food / Confectionery":
        core = "chocolate tasting and review" if "chocolate" in lower else topic or "confectionery tasting and presentation"
        intent = "taste, review and present the featured confectionery varieties"
    elif profile["category"] == "Gaming":
        core = topic or "gaming update"
        intent = "show the relevant game, player experience or gaming product update"
    elif profile["category"] == "Automotive":
        core = topic or "vehicle launch"
        intent = "present the vehicle and its defining real-world movement"
    elif profile["category"] == "Beauty / Product":
        core = topic or "beauty product review"
        intent = "present and review the featured beauty product"
    elif profile["category"] == "Finance / Business":
        core = topic or "financial market update"
        intent = "represent the business or market development with grounded human and financial context"
    elif profile["category"] == "Technology / Business":
        core = topic or "technology business update"
        intent = "show the named technology subject and its business impact"
    elif profile["category"] == "Sports":
        if any(term in lower for term in ("wrestling", "wwe", "wweraw", "wrestler")):
            core = "professional wrestling match"
            profile = {**profile, "style":"premium professional-wrestling documentary"}
        else:
            core = topic or "sports match"
        intent = "show one decisive, physically coherent match moment involving the relevant athletes"
    else:
        core = topic or _clean(source, 22) or "the supplied story"
        intent = _clean(content.get("video_idea") or content.get("creator_angle") or content.get("hook"), 35) or f"show {core} clearly"
    visual = _terms_present(source, VISUAL_TERMS)
    non_visual = _terms_present(source, NON_VISUAL_TERMS)
    interaction = _terms_present(source, INTERACTION_TERMS)
    brands = [value for key in ("brand", "company") if (value := _clean(content.get(key), 8))]
    if "wonka" in lower and not any(value.lower() == "wonka" for value in brands):
        brands.append("Wonka")
    products = [value for key in ("product",) if (value := _clean(content.get(key), 10))]
    if "chocolate" in lower and "chocolate" not in products:
        products.append("chocolate")
    locations = [value for key in ("location",) if (value := _clean(content.get(key), 12))]
    numbers = list(dict.fromkeys(re.findall(r"(?<!\w)(?:[$£€₹]?\d[\d,.]*%?)(?!\w)", source)))
    exact_text = list(dict.fromkeys(re.findall(r"[\"“]([^\"”]{2,80})[\"”]", source)))
    secondary = list(dict.fromkeys(category_hits + visual))[:8]
    return {"source_content":source,"core_subject":core,"secondary_subjects":secondary,"content_intent":intent,"category":profile["category"],"creative_style":profile["style"],"visualizable_information":visual,"non_visual_information":non_visual,"interaction_information":interaction,"brand_entities":brands,"people_entities":[],"products":products,"locations":locations,"important_exact_text":exact_text,"important_numbers":numbers,"duration":duration}


def _concept_candidates(grounding: dict[str, Any], duration: int) -> list[str]:
    subject = grounding["core_subject"]
    category = grounding["category"]
    if category == "Food / Seafood":
        candidates = [f"one nearly cooked prawn sizzling in a premium pan as a chef turns it once with tongs", f"a chef glazing one prawn with herb butter in a controlled pan-cooking close-up", f"a finished prawn presented with its cooking surface and restrained garnish"]
    elif category == "Food / Confectionery":
        if "chocolate" in grounding["source_content"].lower():
            candidates = ["an inviting chocolate assortment arranged on an elegant tasting surface", "a hand selecting one chocolate piece from a varied assortment", "a hand selecting and gently breaking one chocolate piece to reveal its detailed interior texture and filling", "different chocolate pieces presented through their contrasting shapes, textures and fillings"]
        else:
            candidates = [f"a carefully arranged tasting presentation centered on {subject}", f"a hand selects and reveals the texture of {subject}", f"a macro view of the most recognizable food detail in {subject}"]
    elif category == "Gaming":
        candidates = [f"a player interacting with the relevant gaming experience for {subject}", f"a recognizable game-world or console moment centered on {subject}", f"a gaming setup with one clear player action representing {subject}"]
    elif category == "Automotive":
        candidates = [f"the featured vehicle from {subject} moving through a relevant real road environment", f"a clean exterior vehicle reveal centered on {subject}", f"a controlled detail-to-hero view of the vehicle in {subject}"]
    elif category == "Beauty / Product":
        candidates = [f"the featured beauty product from {subject} presented with stable geometry and material detail", f"a hand naturally demonstrates the product in {subject}", f"a macro product reveal showing material, packaging and application context for {subject}"]
    elif category == "Finance / Business":
        candidates = [f"a financial professional reviewing market movement relevant to {subject} with screens kept unreadable", f"a grounded business environment showing the human consequence of {subject}", f"physical market activity and a focused investor reaction representing {subject}"]
    elif category == "Technology / Business":
        candidates = [f"the named technology product, company or service in a directly relevant working context for {subject}", f"people using the relevant technology connected to {subject}", f"a grounded business scene showing the practical impact of {subject}"]
    elif category == "UI / Interface":
        candidates = [f"the supplied interface for {subject} preserved exactly while only its intended focal control animates", f"one precise state change within the existing interface for {subject}"]
    elif category == "Sports":
        if any(term in grounding["source_content"].lower() for term in ("wrestling", "wwe", "wweraw", "wrestler")):
            candidates = ["two athletic professional wrestlers engaged in a decisive exchange inside a brightly lit arena ring", "one professional wrestler completing a controlled takedown against an opponent inside the ring", "two wrestlers facing each other during a tense match moment in a live arena"]
        else:
            candidates = [f"athletes completing one decisive match moment directly connected to {subject}", f"one controlled piece of competitive action in the relevant sports environment for {subject}"]
    else:
        candidates = [f"one recognizable real-world scene directly representing {subject}", f"a person handling one recognizable real-world object associated with {subject}", f"one material detail in an authentic environment strongly associated with {subject}"]
    return candidates


def _select_concept(candidates: list[str], grounding: dict[str, Any], duration: int) -> str:
    # Short clips favor one reliable physical action over broad exposition.
    action_terms = ("break", "break", "takedown", "takedown", "executes", "select", "interacting", "moving", "demonstrates", "using", "state change", "action")
    if duration <= 5:
        return max(candidates, key=lambda item: (sum(term in item.lower() for term in action_terms), -len(item)))
    return candidates[0]


ABSTRACT_TERMS = ("analysis", "review", "update", "growth", "success", "competition", "innovation", "performance", "popularity", "investment", "comparison", "trend", "storyline", "impact")
PLACEHOLDER_ACTIONS = ("perform one action", "show the topic", "make the subject visible", "show relevant activity", "perform appropriate movement", "show a representative scene", "interact naturally", "one clear human action", "one physically believable action")
PHYSICAL_VERBS = ("selects", "selecting", "breaks", "breaking", "lifts", "places", "picks up", "begins playing", "executes", "rebounds", "accelerates", "drives", "turn", "turns", "uses", "spoons", "opens", "applies", "reviews", "tracks", "rotates", "faces", "steps", "raises", "moves", "holds", "walks", "demonstrates", "operates", "completes", "secures", "pivots", "brings", "breathes", "blinks", "shifts")


def _visual_action_candidates(grounding: dict[str, Any], concept: str, generation_type: str) -> list[str]:
    source = grounding["source_content"].lower()
    category = grounding["category"]
    if category == "Food / Seafood":
        return ["A chef uses tongs to turn one nearly cooked prawn once in the hot pan, spoons glossy herb butter over it, and lets it settle naturally.", "A chef turns one nearly cooked prawn once with tongs while butter sizzles around it."]
    if category == "Food / Confectionery":
        return ["A hand selects one chocolate piece and gently breaks it open to reveal the interior texture and filling.", "A hand lifts one tasting piece from the assortment and turns it slightly to reveal its texture."]
    if category == "Sports" and any(term in source for term in ("wrestling", "wwe", "wweraw", "wrestler")):
        return ["One athletic professional wrestler executes a controlled, physically believable takedown while the opponent reacts naturally inside the arena ring.", "One wrestler rebounds from the ropes toward an opponent, who braces naturally for the approaching movement.", "Two professional wrestlers exchange one controlled offensive sequence inside the ring."]
    if category == "Gaming":
        if generation_type == "image_to_video" and any(term in source for term in ("hero", "character", "selection", "moba")):
            return ["The hero holds the original pose while breathing gently, blinking once, and allowing hair, cloth and existing energy effects to move subtly."]
        return ["A player picks up a controller and begins playing in a premium console gaming setup.", "A player leans toward the display and presses the controller buttons with restrained, natural hand movement."]
    if category == "Beauty / Product":
        return ["A hand gently lifts and turns the featured perfume bottle so controlled highlights move across its glass without changing its shape.", "A hand places the featured beauty product into a clean hero position and releases it naturally."]
    if category == "Automotive":
        return ["The featured performance car accelerates smoothly along a controlled road while the camera tracks alongside.", "The vehicle rounds one gentle road curve as its wheels rotate consistently with its speed."]
    if category == "Finance / Business":
        return ["A financial professional reviews changing market activity on an unreadable display, then makes one focused note while colleagues move subtly behind.", "An investor studies the market display and points to one changing trend while the camera moves closer."]
    if category == "Technology / Business":
        return ["A team member demonstrates the named technology in a directly relevant working context while colleagues observe its practical result.", "A user operates the relevant technology and completes one clear task that demonstrates its practical impact."]
    if category == "UI / Interface" or "vinyl" in source:
        return ["The vinyl record rotates clockwise at a slow constant turntable speed while its centered artwork moves with it and the remaining interface stays fixed."]
    if "portrait" in source or "creator" in source:
        return ["The person breathes gently, blinks once and shifts their gaze slightly while remaining in the original portrait composition."]
    if "city" in source:
        return ["A person walks through the city foreground as sunrise light shifts gradually across the surrounding buildings."]
    if generation_type == "image_to_video":
        return [f"The main subject maintains the original composition while completing the restrained movement already implied by {concept}."]
    return [f"The main subject completes one specific physical movement within {concept}."]


def _validate_visual_action(action: str, grounding: dict[str, Any]) -> dict[str, Any]:
    lower = action.lower()
    unresolved = [phrase for phrase in PLACEHOLDER_ACTIONS if phrase in lower]
    has_actor = any(term in lower for term in ("hand", "person", "player", "wrestler", "opponent", "car", "vehicle", "professional", "user", "subject", "hero", "record", "investor", "team member"))
    has_verb = any(verb in lower for verb in PHYSICAL_VERBS)
    has_context = any(term in lower for term in ("surface", "setup", "ring", "road", "display", "working context", "interface", "composition", "bottle", "chocolate", "filling", "city", "studio", "environment", "pose"))
    passed = has_actor and has_verb and has_context and not unresolved
    return {"status":"PASS" if passed else "FAIL","has_actor":has_actor,"has_physical_action":has_verb,"has_environment_or_target":has_context,"unresolved_phrases":unresolved}


def _resolve_visual_action(grounding: dict[str, Any], concept: str, generation_type: str) -> tuple[list[str], str, dict[str, Any]]:
    candidates = _visual_action_candidates(grounding, concept, generation_type)
    for action in candidates:
        validation = _validate_visual_action(action, grounding)
        if validation["status"] == "PASS":
            return candidates, action, validation
    fallback = f"The main subject moves through the directly relevant environment and physically reveals the central detail in {concept}."
    validation = _validate_visual_action(fallback, grounding)
    return candidates, fallback, validation

UNSUPPORTED_BY_CATEGORY = {
    "Food / Confectionery": ("technology engineer", "product designer", "prototype", "ai laboratory", "technology studio", "engineering equipment"),
    "Gaming": ("chocolate tasting", "perfume bottle", "stock trader"),
    "Automotive": ("chocolate tasting", "beauty serum", "game character"),
    "Beauty / Product": ("technology engineer", "stock trader", "gaming setup"),
    "Finance / Business": ("chocolate assortment", "perfume application", "game hero"),
}


def _semantic_validate(text: str, grounding: dict[str, Any], stage: str) -> dict[str, Any]:
    lower = text.lower()
    unsupported = [term for term in UNSUPPORTED_BY_CATEGORY.get(grounding["category"], ()) if term in lower]
    core_tokens = [word for word in re.findall(r"[a-z0-9]+", grounding["core_subject"].lower()) if len(word) > 3]
    relevant = any(token in lower for token in core_tokens) or any(item in lower for item in grounding["visualizable_information"])
    passed = not unsupported and relevant
    return {"stage":stage,"status":"PASS" if passed else "FAIL","unsupported_concepts":unsupported,"core_subject_present":relevant,"repaired":False}

def classify_scene(content: dict[str, Any], user_prompt: str = "") -> str:
    text = f" {_content_text(content, user_prompt)} "
    scores = {scene: sum(2 if phrase in text else 0 for phrase in phrases) for scene, phrases in KEYWORDS.items()}
    # A game-character or visible interface needs stronger structural protection than a generic category.
    if scores["GAMING"] and any(word in text for word in ("character", "hero", "warrior", "mage", "selection", "hud")):
        return "GAMING"
    ranked = sorted(PRIORITY, key=lambda scene: (scores[scene], -PRIORITY.index(scene)), reverse=True)
    return ranked[0] if scores[ranked[0]] else "CINEMATIC"


def _subject(content: dict[str, Any]) -> str:
    return _clean(content.get("topic") or content.get("suggested_title") or content.get("hook") or "the main subject", 22)


def _preservation(scene: str) -> dict[str, str]:
    base = {
        "composition": "STRICT", "framing": "STRICT", "identity": "NORMAL",
        "pose": "NORMAL", "geometry": "STRICT", "background": "STRICT",
        "ui": "NORMAL", "text": "STRICT", "colors": "STRICT",
    }
    if scene in {"PORTRAIT", "CHARACTER_IDLE", "GAMING", "BEAUTY"}:
        base.update(identity="STRICT", pose="STRICT")
    if scene in {"UI_ANIMATION", "GAMING", "FINANCE", "NEWS"}:
        base.update(ui="STRICT", text="STRICT", composition="STRICT")
    if scene in {"PRODUCT", "AUTOMOTIVE", "TECH", "MECHANICAL_OBJECT"}:
        base.update(geometry="STRICT", colors="STRICT")
    return base


def _camera(scene: str, quality: bool) -> dict[str, str]:
    if scene in {"UI_ANIMATION", "GAMING", "MECHANICAL_OBJECT"}:
        return {"level": "LOCKED", "direction": "No camera movement, zoom, pan, tilt, orbit, perspective shift or reframing; keep the camera completely locked."}
    if scene in {"PORTRAIT", "CHARACTER_IDLE", "BEAUTY"}:
        return {"level": "MICRO", "direction": "Use only an almost imperceptible cinematic push-in; preserve the original framing and perspective."}
    if scene in {"PRODUCT", "TECH"}:
        return {"level": "SUBTLE", "direction": "Use one very slow controlled push-in, with no orbit or lens change."}
    if scene == "AUTOMOTIVE":
        return {"level": "CONTROLLED", "direction": "Use one smooth tracking move matched to the vehicle speed; avoid sudden acceleration or angle changes."}
    return {"level": "CONTROLLED" if quality else "SUBTLE", "direction": "Use one motivated, smooth camera move only, then settle into a stable end frame."}


def _budget(scene: str) -> int:
    return {
        "UI_ANIMATION": 15, "CHARACTER_IDLE": 20, "GAMING": 20,
        "PRODUCT": 35, "BEAUTY": 30, "PORTRAIT": 20, "TECH": 35,
        "MECHANICAL_OBJECT": 25, "AUTOMOTIVE": 55, "CINEMATIC": 55,
        "NEWS": 25, "FINANCE": 20, "LANDSCAPE": 40, "ENVIRONMENT": 40,
        "ABSTRACT": 60, "ACTION": 75,
    }[scene]


def _generic_layers(scene: str) -> list[MotionLayer]:
    profiles: dict[str, list[MotionLayer]] = {
        "UI_ANIMATION": [
            MotionLayer("primary interface focal object", "primary", "SUBTLE", "one coherent state change or precisely anchored rotation", "object center axis", "child elements inherit parent transform", "active interface state"),
            MotionLayer("progress indicator or active control", "secondary", "MICRO", "advance smoothly without changing labels or layout", "existing control bounds", "attached_to interface", "playback or system progress"),
            MotionLayer("all typography, icons, buttons, panels and album artwork", "locked", "LOCKED", "remain perfectly legible, unchanged and fixed to their containers", "original UI coordinates", "inherits_motion from parent only", "none"),
            MotionLayer("lighting accents", "reactive", "MICRO", "soft synchronized glow and reflection pulse", "existing highlights", "reacts_to primary motion", "primary state change"),
        ],
        "GAMING": [
            MotionLayer("hero character", "primary", "SUBTLE", "natural breathing and minute posture settling without changing the pose", "feet and body center", "parent character rig", "breathing"),
            MotionLayer("hair, cloth strips and loose costume parts", "secondary", "MICRO", "gentle delayed sway with believable inertia", "attachment points", "attached_to character and inherits_motion", "body settling and ambient air"),
            MotionLayer("energy, particles and reflections", "reactive", "MICRO", "restrained pulsing and drifting along existing effect paths", "existing effect origins", "reacts_to character energy", "ambient energy"),
            MotionLayer("HUD, stats, currency, labels, buttons, portraits and icons", "locked", "LOCKED", "remain pixel-stable, readable and unchanged", "screen coordinates", "independent locked layer", "none"),
        ],
        "CHARACTER_IDLE": [
            MotionLayer("character", "primary", "SUBTLE", "natural breathing, one soft blink and minute posture settling", "feet and body center", "parent character rig", "breathing"),
            MotionLayer("hair and clothing", "secondary", "MICRO", "delayed natural sway with restrained inertia", "attachment points", "attached_to character", "body motion and ambient air"),
            MotionLayer("background atmosphere", "optional", "MICRO", "very slow depth-separated environmental movement", "background plane", "independent", "ambient environment"),
        ],
        "PORTRAIT": [
            MotionLayer("person", "primary", "MICRO", "subtle breathing, one natural blink and an almost imperceptible eye refocus", "face and torso", "identity-locked subject", "natural life motion"),
            MotionLayer("hair and fabric edges", "secondary", "MICRO", "minimal delayed movement without obscuring the face", "attachment points", "attached_to person", "breath and ambient air"),
            MotionLayer("background depth", "optional", "MICRO", "soft optical bokeh drift only", "background plane", "independent", "ambient light"),
        ],
        "PRODUCT": [
            MotionLayer("product", "primary", "SUBTLE", "remain geometrically exact while highlights travel slowly across the material", "product center", "geometry-locked object", "controlled studio light"),
            MotionLayer("supporting particles or fabric", "secondary", "MICRO", "restrained motion that frames rather than covers the product", "existing contact points", "reacts_to product reveal", "air displacement"),
            MotionLayer("surface reflections and shadows", "reactive", "SUBTLE", "respond consistently to the camera and key light", "product surfaces", "reacts_to light and camera", "camera movement"),
        ],
        "AUTOMOTIVE": [
            MotionLayer("vehicle body", "primary", "NORMAL", "move forward with stable design, proportions, badges and body panels", "vehicle center of mass", "parent vehicle", "engine propulsion"),
            MotionLayer("wheels", "secondary", "NORMAL", "rotate around each wheel axle at the exact speed implied by travel", "wheel axles", "attached_to vehicle and inherits translation", "vehicle movement"),
            MotionLayer("road, reflections and environment", "reactive", "NORMAL", "show consistent parallax, moving reflections and light direction", "world coordinates", "reacts_to vehicle speed", "vehicle travel"),
        ],
        "MECHANICAL_OBJECT": [
            MotionLayer("mechanism", "primary", "SUBTLE", "move only through its physically intended axis, hinge or pivot", "mechanical pivot", "parent mechanism", "motor or applied force"),
            MotionLayer("attached components", "secondary", "SUBTLE", "inherit the parent transform without slipping, warping or detaching", "attachment points", "attached_to mechanism and inherits_motion", "parent motion"),
            MotionLayer("reflections and indicator light", "reactive", "MICRO", "respond smoothly to the mechanism", "existing surfaces", "reacts_to primary motion", "mechanical movement"),
        ],
    }
    if scene in profiles:
        return profiles[scene]
    if scene in {"BEAUTY", "TECH"}:
        return profiles["PRODUCT"]
    if scene in {"NEWS", "FINANCE"}:
        return profiles["UI_ANIMATION"]
    if scene in {"LANDSCAPE", "ENVIRONMENT"}:
        return [MotionLayer("environment", "primary", "SUBTLE", "natural wind, water, cloud or foliage movement appropriate to the scene", "world space", "environment system", "weather"), MotionLayer("light and atmosphere", "reactive", "MICRO", "slow coherent atmospheric depth and reflection changes", "scene lighting", "reacts_to environment", "environmental motion")]
    return [MotionLayer("main subject", "primary", "NORMAL", "perform one clear physically believable action", "subject center of mass", "parent subject", "story intent"), MotionLayer("secondary elements", "secondary", "SUBTLE", "respond with delayed natural inertia", "attachment or contact points", "reacts_to main subject", "primary action"), MotionLayer("environment", "reactive", "SUBTLE", "continue restrained coherent background motion", "world space", "reacts_to action", "subject movement")]


def _specialize_layers(layers: list[MotionLayer], text: str) -> list[MotionLayer]:
    if any(term in text for term in ("wrestling", "wwe", "wweraw", "wrestler")):
        return [
            MotionLayer("attacking wrestler", "primary", "NORMAL", "executes one controlled takedown with physically coherent balance and body mechanics", "feet and body center", "maintains contact with opponent", "deliberate wrestling movement"),
            MotionLayer("opponent", "reactive", "NORMAL", "responds naturally to the takedown while maintaining believable contact and anatomy", "contact point and body center", "reacts_to attacking wrestler", "takedown force"),
            MotionLayer("clothing and hair", "secondary", "SUBTLE", "respond naturally to body movement, inertia and gravity", "body attachment points", "attached_to wrestlers", "athlete movement"),
            MotionLayer("ring ropes and audience", "reactive", "MICRO", "show only restrained impact response and soft background activity", "ring posts and arena background", "reacts_to nearby movement", "ring action"),
        ]
    if any(term in text for term in ("prawn", "prawns", "shrimp", "seafood", "shellfish")):
        return [
            MotionLayer("chef tongs and one prawn", "primary", "SUBTLE", "turn the nearly cooked prawn once with stable tong contact, then spoon herb butter over it", "prawn center and tong tips", "tongs maintain contact with prawn", "deliberate cooking action"),
            MotionLayer("pan and supporting ingredients", "locked", "LOCKED", "remain stable in their established positions without duplication or shape change", "pan surface", "independent locked arrangement", "none"),
            MotionLayer("butter and pan juices", "reactive", "MICRO", "sizzle and flow naturally around the prawn after the butter is added", "hot pan surface", "reacts_to added butter and heat", "heat"),
            MotionLayer("steam and highlights", "reactive", "MICRO", "a small amount of steam rises while highlights shift subtly across the shell", "prawn and pan surface", "reacts_to heat and camera motion", "heat and controlled light"),
        ]
    if "chocolate" in text:
        return [
            MotionLayer("hand and chocolate piece", "primary", "SUBTLE", "a hand naturally selects one piece and gently breaks it open to reveal the interior texture or filling", "finger contact and chocolate center", "hand holds chocolate at stable contact points", "deliberate tasting action"),
            MotionLayer("chocolate assortment", "locked", "LOCKED", "remain arranged on the tasting surface with stable shapes, materials and placement", "tasting surface", "independent locked arrangement", "none"),
            MotionLayer("tiny crumbs", "reactive", "MICRO", "a few tiny crumbs fall naturally from the break point under gravity", "chocolate break point", "reacts_to chocolate break", "break force and gravity"),
            MotionLayer("surface highlights", "reactive", "MICRO", "soft highlights shift subtly across the chocolate texture", "chocolate surfaces", "reacts_to hand and camera motion", "controlled tasting light"),
        ]
    if any(word in text for word in ("vinyl", "record", "turntable")):
        return [
            MotionLayer("vinyl record", "primary", "SUBTLE", "rotate clockwise continuously at a slow constant turntable speed, approximately one complete rotation every 2–3 seconds", "record center axis", "parent rotating disc", "turntable motor"),
            MotionLayer("center label or album artwork", "secondary", "SUBTLE", "rotate at exactly the same angular speed with no sliding or independent drift", "record center axis", "attached_to record and inherits_motion", "record rotation"),
            MotionLayer("tonearm, controls, typography and remaining interface", "locked", "LOCKED", "remain completely fixed, crisp, readable and unchanged", "original coordinates", "independent locked layer", "none"),
            MotionLayer("record highlights and soft glow", "reactive", "MICRO", "move subtly with the rotating surface", "record surface", "reacts_to rotation", "record rotation"),
        ]
    if "door" in text:
        return [MotionLayer("door", "primary", "SUBTLE", "open or close only through its natural arc without stretching", "door hinge", "attached_to frame", "hinge force"), MotionLayer("handle and attached hardware", "secondary", "SUBTLE", "inherit the door rotation without slipping or deforming", "door hinge", "attached_to door and inherits_motion", "door rotation")]
    if any(word in text for word in ("phone in hand", "holding a phone", "handheld phone")):
        return [MotionLayer("person and hand", "primary", "SUBTLE", "move with restrained natural body mechanics while maintaining the grip", "hand contact", "parent body rig", "intentional hand movement"), MotionLayer("phone", "secondary", "SUBTLE", "remain firmly attached to the hand with stable design and alignment", "hand contact", "attached_to hand and inherits_motion", "hand movement")]
    if any(word in text for word in ("water", "ocean", "river", "liquid")):
        layers.append(MotionLayer("water", "reactive", "SUBTLE", "flow with coherent fluid motion, connected ripples and stable reflections", "water surface", "reacts_to wind and contact", "gravity and wind"))
    if any(word in text for word in ("smoke", "mist", "fog")):
        layers.append(MotionLayer("smoke or mist", "secondary", "SUBTLE", "rise and curl in slow coherent turbulent flow", "emission source", "reacts_to air flow", "heat and ambient air"))
    if "fire" in text or "flame" in text:
        layers.append(MotionLayer("fire", "secondary", "NORMAL", "flicker upward with connected flame shapes and restrained light response", "fuel source", "attached_to emission source", "heat and combustion"))
    if "flag" in text:
        layers.append(MotionLayer("flag", "secondary", "SUBTLE", "ripple as cloth under gravity and consistent wind direction", "flagpole attachment", "attached_to pole", "ambient wind"))
    return layers


def _negatives(scene: str, category: str = "", text: str = "") -> list[str]:
    common = ["no cuts", "no morphing", "no duplicated or disappearing subjects", "no flicker or abrupt camera movement", "no readable text, numbers, captions, watermarks or generated logos"]
    if category == "Food / Seafood":
        return common + ["no distorted hands or tongs", "no duplicated or malformed prawns", "no floating garnish", "no sudden raw-to-cooked transformation"]
    if category == "Food / Confectionery":
        return common + ["no distorted fingers", "no melting or deforming chocolate unless explicitly requested", "no duplicated chocolate pieces", "no floating crumbs"]
    if category == "Sports":
        return common + ["no duplicated limbs", "no identity morphing", "no impossible anatomy or body deformation"]
    if category == "Automotive":
        return common + ["no vehicle geometry changes", "no wheel deformation or inconsistent wheel rotation"]
    if category == "Beauty / Product":
        return common + ["no hand or finger distortion", "no bottle, packaging, material or logo deformation"]
    if scene in {"UI_ANIMATION", "GAMING", "NEWS", "FINANCE"}:
        common += ["do not alter, rewrite, regenerate or move existing text, numbers, icons, buttons or panels", "no new interface elements"]
    if scene in {"PORTRAIT", "CHARACTER_IDLE", "GAMING", "BEAUTY", "ACTION"}:
        common += ["no facial identity or anatomy changes", "no duplicated limbs"]
    if scene in {"PRODUCT", "TECH", "MECHANICAL_OBJECT"}:
        common += ["no geometry, material, proportion or part-count changes"]
    return common


def _loop(scene: str, intent: str) -> str:
    text = intent.lower()
    if "loop" in text or scene in {"UI_ANIMATION", "CHARACTER_IDLE", "GAMING", "PORTRAIT", "ABSTRACT"}:
        return "seamless loop: return naturally to a frame compatible with the opening pose and state"
    if scene in {"PRODUCT", "BEAUTY", "TECH", "AUTOMOTIVE"}:
        return "hero end: settle on a clean, stable final product composition"
    if "transition" in text:
        return "transition: finish with motivated continuing movement for the next shot"
    return "natural end: complete the action and settle without freezing unnaturally"


def _relationships(layers: list[MotionLayer]) -> tuple[list[str], list[str]]:
    relationships = [f"{layer.name}: {layer.relationship}; anchor={layer.anchor}" for layer in layers]
    causes = [f"{layer.cause} -> {layer.name}: {layer.motion}" for layer in layers if layer.category != "locked"]
    return relationships, causes


def build_motion_plan(content: dict[str, Any], duration: int = 5, *, generation_type: str = "text_to_video", quality_mode: bool = True, user_prompt: str = "") -> MotionPlan:
    duration = max(5, min(60, int(duration or 5)))
    generation_type = "image_to_video" if str(generation_type).replace("-", "_").lower() == "image_to_video" else "text_to_video"
    grounding = _ground_content(content, duration, user_prompt)
    candidates = _concept_candidates(grounding, duration)
    selected = _select_concept(candidates, grounding, duration)
    concept_validation = _semantic_validate(selected, grounding, "visual_concept")
    if concept_validation["status"] == "FAIL":
        selected = f"one clear physical moment directly showing {grounding['core_subject']}"
        concept_validation = _semantic_validate(selected, grounding, "visual_concept")
        concept_validation["repaired"] = True
    action_candidates, concrete_action, action_validation = _resolve_visual_action(grounding, selected, generation_type)
    category_scene = {"Food / Seafood":"PRODUCT", "Food / Confectionery":"PRODUCT", "Gaming":"GAMING", "Automotive":"AUTOMOTIVE", "Beauty / Product":"BEAUTY", "Finance / Business":"FINANCE", "Technology / Business":"TECH", "News":"NEWS", "UI / Interface":"UI_ANIMATION", "Sports":"ACTION"}
    scene = category_scene.get(grounding["category"], classify_scene(content, user_prompt))
    text = grounding["source_content"].lower()
    layers = _specialize_layers(_generic_layers(scene), text)
    relationships, causes = _relationships(layers)
    subject = grounding["core_subject"]
    intent = grounding["content_intent"]
    camera_plan = _camera(scene, quality_mode)
    if grounding["category"] == "Sports" and any(term in text for term in ("wrestling", "wwe", "wweraw", "wrestler")):
        camera_plan = {"level":"CONTROLLED", "direction":"Use one smooth ringside tracking move that follows the action and settles as the wrestlers complete the sequence."}
    plan = MotionPlan(
        generation_type=generation_type,
        scene_type=scene,
        subject=subject,
        intent=intent,
        duration=duration,
        preservation_map=_preservation(scene),
        layers=layers,
        relationship_graph=relationships,
        cause_effect_graph=causes,
        camera=camera_plan,
        motion_budget=_budget(scene) if quality_mode else max(10, round(_budget(scene) * .65)),
        loop_strategy=_loop(scene, intent),
        negative_constraints=_negatives(scene, grounding["category"], text),
        quality_mode=quality_mode,
        source_content=grounding["source_content"],
        core_subject=grounding["core_subject"],
        secondary_subjects=grounding["secondary_subjects"],
        content_intent=grounding["content_intent"],
        category=grounding["category"],
        visualizable_information=grounding["visualizable_information"],
        non_visual_information=grounding["non_visual_information"],
        interaction_information=grounding["interaction_information"],
        brand_entities=grounding["brand_entities"],
        people_entities=grounding["people_entities"],
        products=grounding["products"],
        locations=grounding["locations"],
        important_exact_text=grounding["important_exact_text"],
        important_numbers=grounding["important_numbers"],
        candidate_visual_concepts=candidates,
        selected_visual_concept=selected,
        visual_action_candidates=action_candidates,
        concrete_visual_action=concrete_action,
        action_validation=action_validation,
        creative_style=grounding["creative_style"],
        semantic_validation={"concept": concept_validation},
    )
    compiled_prompt = compile_pixverse_prompt(plan)
    plan.final_prompt, polish_report = _final_prompt_polish(plan, compiled_prompt)
    plan.semantic_validation["final_prompt_polish"] = polish_report
    final_validation = _semantic_validate(plan.final_prompt, grounding, "final_prompt")
    if final_validation["status"] == "FAIL":
        for phrase in final_validation["unsupported_concepts"]:
            plan.final_prompt = re.sub(re.escape(phrase), plan.core_subject, plan.final_prompt, flags=re.I)
        if not final_validation["core_subject_present"]:
            plan.final_prompt = f"Center the footage strictly on {plan.core_subject}. " + plan.final_prompt
        final_validation = _semantic_validate(plan.final_prompt, grounding, "final_prompt")
        final_validation["repaired"] = True
    plan.semantic_validation["final"] = final_validation
    plan.semantic_validation["status"] = "PASS" if concept_validation["status"] == "PASS" and final_validation["status"] == "PASS" and polish_report["status"] == "PASS" else "FAIL"
    return plan


def _natural_motion_sentence(layer: MotionLayer) -> str:
    name = layer.name
    motion = layer.motion.rstrip(" .")
    if layer.category == "locked" or layer.intensity == "LOCKED":
        return f"Keep the {name} completely still and fixed in their established position; {motion}."
    if layer.category == "reactive":
        cause = layer.cause if layer.cause != "natural scene motion" else "the primary movement"
        return f"Let the {name} respond naturally to {cause}: {motion}."
    if layer.category == "secondary":
        return f"Keep the {name} physically connected and limit its movement to this natural response: {motion}."
    return motion[:1].upper() + motion[1:] + "."


def _preservation_language(plan: MotionPlan) -> str:
    if plan.category == "Food / Seafood":
        return "Maintain stable hand anatomy, tong geometry, prawn count, shell shape, pan arrangement, composition and lighting throughout."
    if plan.category == "Food / Confectionery":
        return "Maintain stable hand anatomy, chocolate shapes, materials, composition and lighting throughout."
    if plan.category == "Sports":
        return "Maintain consistent athlete identity, anatomy, wardrobe, ring geometry, arena lighting and spatial continuity throughout."
    if plan.category == "Automotive":
        return "Maintain the vehicle's exact design, proportions, wheel geometry, materials and reflections throughout."
    if plan.category == "Beauty / Product":
        return "Maintain stable hand anatomy, product shape, packaging, materials, logo placement, composition and lighting throughout."
    if plan.scene_type in {"UI_ANIMATION", "GAMING"} and plan.generation_type == "image_to_video":
        return "Preserve the original identity, pose, composition, framing, interface layout, text, icons and color palette exactly."
    if plan.scene_type in {"PORTRAIT", "CHARACTER_IDLE"}:
        return "Preserve the original facial identity, expression, anatomy, pose, framing, wardrobe and color palette."
    return "Keep subject identity, object geometry, wardrobe, composition, palette, lighting direction and environment consistent throughout."


def _supporting_direction(plan: MotionPlan) -> str:
    if plan.category == "Food / Seafood":
        return "As herb butter reaches the hot pan, let it sizzle and flow naturally around the prawn while a small amount of steam rises. Keep the pan and surrounding cooking surface completely still."
    if plan.category == "Food / Confectionery":
        return "As the chocolate breaks, allow a few tiny crumbs to fall naturally under gravity while soft highlights shift subtly across the chocolate surface. Keep the remaining assortment completely still and fixed in its arrangement."
    if plan.category == "Sports":
        return "Let clothing and hair respond naturally to body movement while the ring ropes react subtly to nearby impact. Keep the surrounding audience softly active in the background without distracting from the athletes."
    if plan.category == "Gaming" and plan.generation_type == "text_to_video":
        return "As the player presses the controls, let screen light shift subtly across their hands and face while minimal background activity continues."
    if plan.category == "Automotive":
        return "Rotate the wheels consistently with vehicle speed while road parallax and reflections respond naturally to forward movement."
    if plan.category == "Beauty / Product":
        return "Let controlled highlights travel gently across the product material while the background remains soft and undistracting."
    if plan.category == "Finance / Business":
        return "Keep displays and documents unreadable while restrained workplace movement supports the main action."
    if plan.category == "Technology / Business":
        return "As the demonstration progresses, let visible screen light and nearby reflections respond subtly while background activity remains restrained and relevant."
    secondary = [layer for layer in plan.layers if layer.category in {"secondary", "reactive"}]
    return " ".join(_natural_motion_sentence(layer) for layer in secondary[:2])


def _negative_language(plan: MotionPlan) -> str:
    shared = "No cuts, flicker, abrupt camera movement, readable text, captions, watermarks or generated logos."
    if plan.category == "Food / Seafood":
        return shared + " No distorted hands or tongs, duplicated or malformed prawns, floating garnish, shell deformation or sudden raw-to-cooked transformation."
    if plan.category == "Food / Confectionery":
        return shared + " No distorted fingers, duplicated or disappearing chocolate pieces, floating crumbs or unintended melting."
    if plan.category == "Sports":
        return shared + " No identity changes, duplicated or disappearing wrestlers or limbs, or anatomy distortion."
    if plan.category == "Automotive":
        return shared + " No vehicle geometry changes, wheel deformation or inconsistent wheel rotation."
    if plan.category == "Beauty / Product":
        return shared + " No distorted hands, duplicated products, or bottle, packaging, material or logo deformation."
    if plan.scene_type in {"UI_ANIMATION", "GAMING"} and plan.generation_type == "image_to_video":
        return shared + " No jitter, interface changes, duplicated elements, identity changes or anatomy distortion. Do not alter existing text, numbers, icons, buttons or panels."
    if plan.scene_type in {"PORTRAIT", "CHARACTER_IDLE"}:
        return shared + " No facial identity changes, duplicated limbs or anatomy distortion."
    return shared + " No morphing, geometry drift, or duplicated or disappearing subjects."

def _clean_prompt(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result, seen = [], set()
    for sentence in sentences:
        key = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(sentence.strip())
    return " ".join(result)


def _explicit_primary_action(plan: MotionPlan) -> str:
    action = plan.concrete_visual_action.rstrip(" .")
    lower = action.lower()
    if plan.category == "Sports" and "takedown" in lower:
        return "One wrestler secures the opponent, pivots with controlled balance, and brings them onto the mat inside the arena ring in one believable takedown as the opponent reacts naturally"
    if plan.category == "Food / Seafood":
        return "A chef uses tongs to turn one nearly cooked prawn once in the hot pan, spoons glossy herb butter over it, and lets it settle naturally"
    if plan.category == "Food / Confectionery" and any(term in lower for term in ("tastes", "selects", "breaks")):
        return "A hand selects one chocolate piece, gently breaks it open, and reveals the interior texture and filling"
    if plan.category == "Beauty / Product" and any(term in lower for term in ("demonstrates", "interacts", "lifts", "turns")):
        return "A hand picks up the bottle, turns it slightly toward the light, and places it back into its hero position"
    if plan.category == "Automotive" and "accelerates" in lower:
        return "The featured car accelerates smoothly along the road as the camera tracks alongside"
    return action


def _final_prompt_polish(plan: MotionPlan, prompt: str) -> tuple[str, dict[str, Any]]:
    polished = _clean_prompt(prompt)
    # Remove subject/category repetition without changing the selected concept.
    if plan.category == "Sports":
        polished = re.sub(r"(premium professional-wrestling documentary shot) centered on (?:a )?professional wrestling match\. ", r"\1. ", polished, flags=re.I)
    polished = re.sub(r"\b(?:stunning|immersive|emotionally engaging|masterpiece|ultra quality)\b[ ,]*", "", polished, flags=re.I)
    polished = re.sub(r"\s+", " ", polished).strip()
    lower = polished.lower()
    action = _explicit_primary_action(plan).lower()
    internal_terms = [term for term in ("(primary", "(secondary", "(reactive", "(locked", "reacts_to", "attached_to", "inherits_motion", "motion budget", "/100") if term in lower]
    subject_terms = [word for word in re.findall(r"[a-z0-9]+", plan.core_subject.lower()) if len(word) > 3 and word not in ABSTRACT_TERMS]
    checks = {
        "subject_obvious": any(word in lower for word in subject_terms) or plan.category == "Sports" and "wrestler" in lower,
        "physical_action_obvious": any(verb in action for verb in PHYSICAL_VERBS),
        "action_fits_duration": plan.duration > 5 or len(action.split()) <= 32,
        "camera_explicit": any(term in lower for term in ("camera", "push-in", "tracking", "locked", "pan", "zoom")),
        "cause_effect_preserved": any(term in lower for term in ("as the", "while", "respond", "react", "under gravity", "consistent with vehicle speed")),
        "preservation_relevant": any(term in lower for term in ("maintain", "preserve", "keep the remaining", "stable")),
        "negative_constraints_concise": lower.count("no cuts") == 1 and len(re.findall(r"\b(?:morph|duplicat|anatomy distortion)\w*", lower)) <= 4,
        "no_internal_terminology": not internal_terms,
        "no_placeholder_action": not any(term in lower for term in PLACEHOLDER_ACTIONS),
        "semantic_validation_passed": plan.semantic_validation.get("concept", {}).get("status") == "PASS",
    }
    return polished, {"status":"PASS" if all(checks.values()) else "FAIL", "checks":checks, "internal_terms_found":internal_terms, "polished_once":True}

def compile_pixverse_prompt(plan: MotionPlan) -> str:
    action = _explicit_primary_action(plan).rstrip(" .") + "."
    preservation = _preservation_language(plan)
    support = _supporting_direction(plan) if plan.quality_mode else ""
    if plan.generation_type == "image_to_video":
        opening = (
            f"Use the supplied image as the visual source of truth for a {plan.duration}-second animation centered on {plan.core_subject}. "
            "Preserve the original composition, crop, camera perspective, subject placement, background layout, color palette, lighting direction and visible design details. "
            f"{action} "
        )
        included_categories = {"locked"} if not plan.quality_mode else {"locked", "secondary", "reactive"}
        layer_directions = " ".join(_natural_motion_sentence(layer) for layer in plan.layers if layer.category in included_categories)
        body = f"{opening}{layer_directions} {support} {plan.camera['direction']} {preservation}"
    else:
        setting = {
            "Food / Seafood": "Stage a clean premium cooking close-up with one clearly defined nearly cooked prawn in a dark elegant pan, restrained herb butter, warm restaurant lighting, shallow depth of field and a softly blurred kitchen background.",
            "Food / Confectionery": "Stage an inviting assortment of richly detailed pieces on an elegant tasting surface with warm premium confectionery lighting, shallow depth of field and a softly blurred tasting environment.",
            "Sports": "Place the athletes inside a brightly lit professional arena with a clearly defined competition area and a softly active audience.",
            "Gaming": "Use a premium console gaming environment with controlled screen light and stable recognizable gaming objects.",
            "Technology / Business": "Use a grounded working context directly connected to the named technology, without inventing unrelated devices or laboratories.",
            "Finance / Business": "Use a credible financial workplace with all screen and document content kept unreadable for later overlays.",
            "Beauty / Product": "Use a refined beauty-review setting with controlled material highlights and stable product geometry.",
            "Automotive": "Use a relevant real road or launch environment with stable vehicle design and physically consistent reflections.",
        }.get(plan.category, "Use a real-world environment directly supported by the source content.")
        body = (
            f"Create one uninterrupted {plan.duration}-second vertical 9:16 {plan.creative_style} shot centered on {plan.core_subject}. "
            f"{setting} {action} {plan.camera['direction']} {support} {preservation}"
        )
    if plan.loop_strategy.startswith("seamless loop"):
        ending = "Maintain smooth continuous motion through the final frame and return naturally to an opening-compatible state for a seamless loop."
    elif plan.loop_strategy.startswith("hero end"):
        ending = "End on a clean, stable hero view."
    elif plan.loop_strategy.startswith("transition"):
        ending = "Finish with motivated continuing movement suitable for the next shot."
    else:
        ending = "Complete the action naturally and settle without freezing unnaturally."
    prompt = _clean_prompt(f"{body} {ending} {_negative_language(plan)}")
    unresolved = [phrase for phrase in PLACEHOLDER_ACTIONS if phrase in prompt.lower()]
    if unresolved:
        raise ValueError("PixVerse prompt contains unresolved visual-action language: " + ", ".join(unresolved))
    return prompt

def build_shot_specification(plan: MotionPlan) -> dict[str, Any]:
    source = plan.source_content.lower()
    if plan.category == "Sports" and any(term in source for term in ("wrestling", "wwe", "wweraw", "wrestler")):
        return {"category":plan.category,"core_subject":plan.core_subject,"subjects":["two athletic professional wrestlers"],"environment":"brightly lit professional wrestling arena","location":"inside a clearly defined wrestling ring","important_objects":["ring ropes","wrestling mat"],"forbidden_objects":["soccer player","soccer ball","football goal","football pitch","football tunnel","football kit"],"start_state":"both wrestlers standing in contact at the beginning of a grapple, balanced on their feet","primary_action":"controlled grapple, pivot and takedown","camera":"ringside tracking view","composition":"vertical 9:16, both wrestlers fully readable with ring ropes and mat visible","lighting":"bright realistic arena lighting","style":plan.creative_style}
    if plan.category == "Food / Seafood":
        return {"category":plan.category,"core_subject":plan.core_subject,"subjects":["one natural chef hand with metal tongs","one nearly cooked prawn"],"environment":"premium seafood cooking setting","location":"inside a clean dark pan","important_objects":["single prawn","metal tongs","herb butter","pan juices"],"forbidden_objects":["chocolate","confectionery","candy","dessert","filling","wrapper"],"start_state":"one nearly cooked prawn resting in the hot pan as stable tongs make contact","primary_action":"turn the prawn once, spoon herb butter over it, and settle","camera":"one slow controlled macro push-in","composition":"vertical 9:16 premium seafood close-up","lighting":"warm controlled restaurant lighting","style":plan.creative_style}
    if plan.category == "Food / Confectionery":
        return {"category":plan.category,"core_subject":plan.core_subject,"subjects":["one natural hand","assorted chocolate pieces"],"environment":"premium confectionery tasting setting","location":"elegant tasting surface","important_objects":["chocolate assortment","opened chocolate filling","tiny crumbs"],"forbidden_objects":["computer","technology laboratory","prototype","engineering equipment","vehicle"],"start_state":"hand reaching toward an intact chocolate piece in the assortment","primary_action":"select, break and reveal the chocolate filling","camera":"controlled macro push-in","composition":"vertical 9:16 macro food composition","lighting":"warm premium confectionery lighting","style":plan.creative_style}
    if plan.category == "Automotive":
        return {"category":plan.category,"core_subject":plan.core_subject,"subjects":["featured car"],"environment":"real controlled road environment","location":"on the road","important_objects":["car body","four wheels","road"],"forbidden_objects":["motorcycle","bicycle","aircraft"],"start_state":"car aligned on the road before smooth acceleration","primary_action":plan.concrete_visual_action,"camera":plan.camera["direction"],"composition":"vertical 9:16 vehicle hero composition","lighting":"physically consistent road lighting","style":plan.creative_style}
    if plan.category == "Beauty / Product":
        return {"category":plan.category,"core_subject":plan.core_subject,"subjects":["one natural hand","featured beauty product"],"environment":"refined beauty-review setting","location":"clean product surface","important_objects":["product bottle","packaging"],"forbidden_objects":["food","cooking utensils","vehicle","gaming controller"],"start_state":"product resting in a clean hero position before the hand lifts it","primary_action":plan.concrete_visual_action,"camera":plan.camera["direction"],"composition":"vertical 9:16 product composition","lighting":"controlled beauty lighting","style":plan.creative_style}
    if plan.category == "Gaming":
        return {"category":plan.category,"core_subject":plan.core_subject,"subjects":["relevant player or game character"],"environment":"premium gaming environment","location":"gaming setup or supplied game interface","important_objects":["controller or existing game interface"],"forbidden_objects":["stock chart","trading desk","food tasting","perfume bottle"],"start_state":"subject ready immediately before the selected gaming action","primary_action":plan.concrete_visual_action,"camera":plan.camera["direction"],"composition":"vertical 9:16 gaming composition","lighting":"controlled screen light","style":plan.creative_style}
    return {"category":plan.category,"core_subject":plan.core_subject,"subjects":[plan.core_subject],"environment":"real-world environment directly supported by the current content","location":"current story location","important_objects":plan.products or plan.visualizable_information[:4],"forbidden_objects":[],"start_state":"a stable moment immediately before the primary action begins","primary_action":plan.concrete_visual_action,"camera":plan.camera["direction"],"composition":"vertical 9:16 with one clear focal subject","lighting":"stable realistic lighting","style":plan.creative_style}


def compile_reference_image_prompt(spec: dict[str, Any]) -> str:
    subjects = ", ".join(spec["subjects"])
    objects = ", ".join(spec["important_objects"])
    forbidden = ", ".join(spec["forbidden_objects"])
    prompt = (f"Create a {spec['composition']} reference start frame for {spec['core_subject']}. Show {subjects} {spec['location']} within {spec['environment']}. Starting state: {spec['start_state']}. Important visible objects: {objects}. Camera viewpoint: {spec['camera']}. Lighting: {spec['lighting']}. Style: {spec['style']}. Use stable realistic anatomy, geometry and spatial relationships. This is the moment immediately before the action, not the completed action. No readable text, captions, watermarks or generated logos.")
    if forbidden:
        prompt += f" Exclude conflicting objects and domains: {forbidden}."
    return _clean_prompt(prompt)


def validate_shot_consistency(spec: dict[str, Any], reference_prompt: str, motion_prompt: str) -> dict[str, Any]:
    reference_lower, motion_lower = reference_prompt.lower(), motion_prompt.lower()
    reference_positive = reference_lower.split("exclude conflicting objects and domains:", 1)[0]
    required = [str(spec["core_subject"]).lower(), *[str(item).lower() for item in spec["subjects"]], *[str(item).lower() for item in spec["important_objects"][:2]]]
    conflicts = [item for item in spec["forbidden_objects"] if item.lower() in reference_positive or item.lower() in motion_lower]
    # Singular/plural and descriptive variants are accepted when their meaningful tokens are present.
    missing = []
    combined = reference_lower + " " + motion_lower
    for item in required:
        tokens = [token for token in re.findall(r"[a-z0-9]+", item) if len(token) > 3]
        if tokens and not any(token in combined for token in tokens):
            missing.append(item)
    passed = not conflicts and not missing
    return {"status":"PASS" if passed else "FAIL","missing_semantics":missing,"conflicting_objects":conflicts,"core_subject":spec["core_subject"],"category":spec["category"]}

def build_motion_directed_prompt(content: dict[str, Any], duration: int = 5, *, generation_type: str = "text_to_video", quality_mode: bool = True, user_prompt: str = "") -> tuple[str, dict[str, Any]]:
    plan = build_motion_plan(content, duration, generation_type=generation_type, quality_mode=quality_mode, user_prompt=user_prompt)
    return plan.final_prompt, plan.debug()
