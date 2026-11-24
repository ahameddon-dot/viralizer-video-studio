"""Variable-length storyboard planning and safe scene edits (stdlib only).

PixVerse renders fixed 5-second clips, so every video is a whole number of
5-second scenes: 5s = 1 scene ... 300s = 60 scenes. Durations that are not a
multiple of five are rounded UP so the promised length matches the real video.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

SECONDS_PER_SCENE = 5
MIN_DURATION, MAX_DURATION = 5, 300


def normalize_duration(seconds: Any) -> int:
    """Clamp to 5..300 and round up to a whole number of 5-second scenes."""
    try:
        value = int(float(seconds))
    except (TypeError, ValueError):
        value = 15
    value = max(MIN_DURATION, min(MAX_DURATION, value))
    return math.ceil(value / SECONDS_PER_SCENE) * SECONDS_PER_SCENE


def scene_plan(seconds: Any) -> list[tuple[int, int]]:
    total = normalize_duration(seconds)
    return [(start, start + SECONDS_PER_SCENE) for start in range(0, total, SECONDS_PER_SCENE)]


# purpose, narration template, visual, motion (all grounded; no invented facts)
_MIDDLE_BEATS = (
    ("context", "Here is what is happening with {title}.",
     "A concrete real-world scene that shows the verified development in context",
     "Gentle lateral track while the subject performs one clear action"),
    ("relevance", "Why this matters for {audience}.",
     "A close, relatable moment showing why the development matters to the audience",
     "Slow controlled push-in with restrained environmental motion"),
    ("insight", "Here is the part most people overlook.",
     "A clear visual contrast that reveals the key insight without any generated labels",
     "Slow pull-back that reveals the full scene"),
    ("proof", "What the verified details show.",
     "A grounded detail shot of the verified subject matter",
     "Slow drifting arc around the focal subject with no cuts"),
    ("implication", "What to watch next.",
     "A forward-looking frame that shows the next step or consequence",
     "Gentle upward tilt with soft parallax"),
)


def scaled_storyboard(hook: str, title: str, audience: str, cta: str, seconds: Any,
                      scene: Callable[[int, int, str, str, str, str], dict[str, Any]],
                      direction: str = "Fast Insight") -> list[dict[str, Any]]:
    """Build N five-second scenes while preserving the chosen creative direction."""
    plan = scene_plan(seconds)
    count = len(plan)
    scenes: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(plan):
        if direction == "Myth vs Reality" and index == 0:
            scenes.append(scene(start, end, "myth", hook,
                                "A cool-toned composition showing the common mistaken assumption through one clear action, without generated labels",
                                "Slow push toward the mistaken action while keeping the unresolved result visible"))
        elif direction == "Myth vs Reality" and index == count - 1:
            scenes.append(scene(start, end, "takeaway", cta,
                                "A warm outcome composition showing the audience applying the evidence-grounded reality",
                                "Gentle pull-back from the credible result to a confident closing frame"))
        elif direction == "Myth vs Reality":
            purpose, narration, visual, motion = _MIDDLE_BEATS[(index - 1) % len(_MIDDLE_BEATS)]
            scenes.append(scene(start, end, "reality" if index == 1 else purpose,
                                "The evidence reveals what actually matters." if index == 1 else narration.format(title=title, audience=audience),
                                "A clearly different side-angle composition demonstrating the corrected, source-grounded reality" if index == 1 else visual,
                                "A motivated lateral reveal into the corrected action" if index == 1 else motion))
        elif direction == "Before & After" and index == 0:
            scenes.append(scene(start, end, "before", hook,
                                "A cool, wide environmental composition showing the old process and its unresolved obstacle",
                                "Mostly locked frame with one restrained action that exposes the problem"))
        elif direction == "Before & After" and index == count - 1:
            scenes.append(scene(start, end, "after", cta,
                                "A warm, confident hero composition showing the credible completed outcome",
                                "Begin on the finished result, then gently reveal the confident subject"))
        elif direction == "Before & After":
            scenes.append(scene(start, end, "transformation", "Now the verified conditions are changing.",
                                "A distinct side-angle composition showing one visible cause-and-effect step in the transformation",
                                "Decisive lateral tracking through one complete transformation action"))
        elif index == 0:
            scenes.append(scene(start, end, "hook", hook or f"Here is what {title} changes.",
                                "A striking close editorial view of the central subject at the moment of change",
                                "Slow controlled push-in with restrained environmental motion"))
        elif index == count - 1:
            scenes.append(scene(start, end, "action", cta,
                                "A confident outcome frame connecting the result to the audience",
                                "Slow settle with a subtle pull-back"))
        else:
            purpose, narration, visual, motion = _MIDDLE_BEATS[(index - 1) % len(_MIDDLE_BEATS)]
            scenes.append(scene(start, end, purpose, narration.format(title=title, audience=audience), visual, motion))
    return scenes


# --------------------------------------------------------------------------
# Safe scene edits. Edits are stored as tagged suffixes so repeated edits
# replace the previous direction instead of piling up.
# --------------------------------------------------------------------------
_DIRECTION = re.compile(r"\s*\[Direction: [^\]]*\]")
_STYLE = re.compile(r"\s*\[Style: [^\]]*\]")
_MOTION = re.compile(r"\s*\[Motion: [^\]]*\]")


def clean_text(value: Any, limit: int = 300) -> str:
    text = " ".join(str(value or "").replace("[", "(").replace("]", ")").split())
    return text[:limit]


def _tag(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    if not match:
        return ""
    return re.sub(r"^\s*\[\w+: |\]$", "", match.group(0)).strip()


def scene_patch(scene: dict[str, Any], narration: Any = None, visual: Any = None,
                motion: Any = None, style: Any = None) -> dict[str, Any]:
    """Return a hybrid-project scene patch for the requested change (or {})."""
    patch: dict[str, Any] = {}
    narration, visual, motion, style = (clean_text(v) if v else "" for v in (narration, visual, motion, style))
    if narration:
        patch["narration"] = narration
        patch["on_screen_text"] = narration[:60]
    keyframe = str(scene.get("keyframe_prompt") or "")
    if visual or style:
        base = _STYLE.sub("", _DIRECTION.sub("", keyframe)).rstrip()
        new_visual = visual or _tag(_DIRECTION, keyframe)
        new_style = style or _tag(_STYLE, keyframe)
        patch["keyframe_prompt"] = (base + (f" [Direction: {new_visual}]" if new_visual else "")
                                    + (f" [Style: {new_style}]" if new_style else ""))[:3900]
    if motion:
        base = _MOTION.sub("", str(scene.get("motion_prompt") or "")).rstrip()
        patch["motion_prompt"] = f"{base} [Motion: {motion}]"[:3900]
        patch["camera"] = motion[:200]
    return patch


