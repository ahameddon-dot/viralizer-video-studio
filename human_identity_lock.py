from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import httpx


IDENTITY_QC_FIELDS = (
    "SAME_PERSON",
    "GENDER_PRESENTATION_PRESERVED",
    "AGE_BAND_PRESERVED",
    "FACE_PRESERVED",
    "HAIR_PRESERVED",
    "CLOTHING_PRESERVED",
    "BODY_BUILD_PRESERVED",
    "SUBJECT_COUNT_PRESERVED",
    "HAND_IDENTITY_STRUCTURE_ACCEPTABLE",
    "EGGS_PRESERVED",
)

PROHIBITED_IDENTITY_CHANGES = (
    "gender-presentation change",
    "face replacement or identity change",
    "additional person",
    "wardrobe change",
    "hairstyle change",
    "body-type or body-proportion change",
    "skin-tone appearance change",
)

_HUMAN_TERMS = re.compile(
    r"\b(?:person|people|performer|athlete|martial artist|fighter|wrestler|woman|women|"
    r"girl|girls|female|man|men|male|boy|boys|child|teen|teenager|adult|model|creator|"
    r"presenter|chef|player|human|hand|hands|face|body)\b",
    re.IGNORECASE,
)


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def shot_contains_human(shot: dict[str, Any]) -> bool:
    specification = shot.get("shot_specification") if isinstance(shot.get("shot_specification"), dict) else {}
    parts = [
        shot.get("visual_subject"),
        shot.get("visual_description"),
        shot.get("action"),
        specification.get("core_subject"),
        *(specification.get("subjects") or []),
    ]
    return bool(_HUMAN_TERMS.search(" ".join(_clean(part) for part in parts)))


def _story_gender(shot: dict[str, Any]) -> str:
    evidence = " ".join(
        _clean(value, 1500)
        for value in (
            shot.get("visual_subject"),
            shot.get("visual_description"),
            shot.get("source_support"),
            shot.get("approved_storyboard_shot"),
            shot.get("reference_frame_plan"),
        )
    ).lower()
    if re.search(r"\b(?:female|woman|girl|her|she)\b", evidence):
        return "female-presenting"
    if re.search(r"\b(?:male|man|boy|his|he)\b", evidence):
        return "male-presenting"
    return "preserve exactly as shown in the approved reference"


def _story_age_band(shot: dict[str, Any]) -> str:
    evidence = json.dumps(shot, ensure_ascii=True).lower()
    match = re.search(r"\b(\d{1,2})[- ]year[- ]old\b", evidence)
    if match:
        age = int(match.group(1))
        if age < 13:
            return "child"
        if age < 18:
            return "adolescent"
    return "preserve the visually apparent age band from the approved reference"


def fallback_human_identity_lock(shot: dict[str, Any]) -> dict[str, Any]:
    """Build a safe lock when visual description service is unavailable.

    Unknown appearance details remain explicitly reference-bound rather than inferred.
    """
    story_gender = _story_gender(shot)
    prohibited = list(PROHIBITED_IDENTITY_CHANGES)
    if "female" in story_gender:
        prohibited.insert(0, "male subject replacing the approved female-presenting subject")
    elif "male" in story_gender:
        prohibited.insert(0, "female subject replacing the approved male-presenting subject")
    return {
        "source_of_truth": "approved_reference_image",
        "gender_presentation": _story_gender(shot),
        "approximate_age_band": _story_age_band(shot),
        "face_visibility_requirements": "preserve the same face visibility, angle, and facial structure shown in the approved reference",
        "hair": "preserve the exact visible hairstyle, length, color appearance, and coverage from the approved reference",
        "skin_tone_appearance_from_reference": "preserve the exact visible skin-tone appearance from the approved reference",
        "clothing": "preserve the exact visible clothing, colors, fit, and coverage from the approved reference",
        "body_build": "preserve the exact visible body build and proportions from the approved reference",
        "pose_start_posture": "begin from the exact pose and posture shown in the approved reference",
        "hand_visibility": "preserve the same visible hands, grip, anatomy, and held objects from the approved reference",
        "distinguishing_visual_traits": ["all visually distinguishing traits in the approved reference"],
        "subject_count": 1,
        "approved_story_gender_presentation": story_gender,
        "reference_visual_gender_presentation": "not independently described",
        "identity_authority_conflict": False,
        "prohibited_identity_changes": prohibited,
        "derivation_status": "REFERENCE_BOUND_FALLBACK",
    }


def normalize_human_identity_lock(value: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    base = fallback_human_identity_lock(shot)
    if not isinstance(value, dict):
        return base
    for key in (
        "approximate_age_band", "face_visibility_requirements", "hair",
        "skin_tone_appearance_from_reference", "clothing", "body_build", "pose_start_posture",
        "hand_visibility",
    ):
        cleaned = _clean(value.get(key), 500)
        if cleaned:
            base[key] = cleaned
    traits = value.get("distinguishing_visual_traits")
    if isinstance(traits, list):
        cleaned_traits = [_clean(item, 180) for item in traits if _clean(item, 180)]
        if cleaned_traits:
            base["distinguishing_visual_traits"] = cleaned_traits[:8]
    try:
        count = int(value.get("subject_count"))
        if count > 0:
            base["subject_count"] = count
    except (TypeError, ValueError):
        pass
    visual_gender = _clean(value.get("gender_presentation"), 120) or base["gender_presentation"]
    story_gender = _story_gender(shot)
    expected = "female" if "female" in story_gender else "male" if "male" in story_gender else ""
    observed = "female" if "female" in visual_gender.lower() else "male" if "male" in visual_gender.lower() else ""
    gender_conflict = bool(expected and observed and expected != observed)
    story_age = _story_age_band(shot)
    visual_age = _clean(value.get("approximate_age_band"), 120) or base["approximate_age_band"]
    age_conflict = story_age in {"child", "adolescent"} and any(term in visual_age.lower() for term in ("adult", "20", "25", "30", "35", "40", "50"))
    prohibited = list(PROHIBITED_IDENTITY_CHANGES)
    if expected == "female":
        prohibited.insert(0, "male subject replacing the approved female-presenting subject")
    elif expected == "male":
        prohibited.insert(0, "female subject replacing the approved male-presenting subject")
    base["gender_presentation"] = visual_gender
    base["approximate_age_band"] = visual_age
    base["approved_story_gender_presentation"] = story_gender
    base["reference_visual_gender_presentation"] = visual_gender
    base["approved_story_age_band"] = story_age
    base["identity_authority_conflict"] = gender_conflict or age_conflict
    base["identity_authority_conflict_reasons"] = [
        reason for condition,reason in (
            (gender_conflict,f"reference appears {visual_gender}, but approved story evidence requires {story_gender}"),
            (age_conflict,f"reference appears {visual_age}, but approved story evidence requires {story_age}"),
        ) if condition
    ]
    base["source_of_truth"] = "approved_reference_image"
    base["prohibited_identity_changes"] = prohibited
    base["derivation_status"] = "DERIVED_FROM_APPROVED_REFERENCE"
    return base


async def derive_human_identity_lock(reference_image: bytes, shot: dict[str, Any]) -> dict[str, Any]:
    if not shot_contains_human(shot):
        return {}
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return fallback_human_identity_lock(shot)
    story_evidence = {
        "visual_subject": shot.get("visual_subject") or (shot.get("approved_storyboard_shot") or {}).get("visual_subject"),
        "source_support": (shot.get("approved_storyboard_shot") or {}).get("source_support"),
        "must_show": (shot.get("approved_storyboard_shot") or {}).get("must_show"),
    }
    instruction = (
        "Describe only visually necessary identity-preservation features of the human in this approved reference image. "
        "The image is authoritative for appearance; approved story evidence may establish gender presentation or age band. "
        "Do not identify the real person, infer ethnicity, nationality, religion, health, personality, or other unsupported personal attributes. "
        "Return JSON only with: gender_presentation, approximate_age_band, face_visibility_requirements, hair, "
        "skin_tone_appearance_from_reference, clothing, body_build, pose_start_posture, hand_visibility, "
        "distinguishing_visual_traits (array), subject_count (integer). Approved story evidence: " + json.dumps(story_evidence, ensure_ascii=True)
    )
    payload = {
        "model": os.getenv("OPENAI_QC_MODEL", "gpt-4.1-mini"),
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": instruction},
            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(reference_image).decode()},
        ]}],
        "text": {"format": {"type": "json_object"}},
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": "Bearer " + key},
                json=payload,
            )
        if response.is_error:
            return fallback_human_identity_lock(shot)
        data = response.json()
        raw = data.get("output_text", "") or "".join(
            part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        return normalize_human_identity_lock(json.loads(raw), shot)
    except Exception:
        return fallback_human_identity_lock(shot)


def identity_negative_constraints(lock: dict[str, Any]) -> str:
    if not lock:
        return ""
    gender = _clean(lock.get("approved_story_gender_presentation") or lock.get("gender_presentation"), 80).lower()
    first = "male subject" if "female" in gender else "female subject" if "male" in gender else "gender change"
    return ", ".join((
        f"no {first}", "no gender change", "no face replacement", "no identity change",
        "no additional person", "no wardrobe change", "no hairstyle change", "no body-type change",
    ))


def apply_human_identity_lock(prompt: str, lock: dict[str, Any], *, retry: bool = False) -> str:
    if not lock:
        return prompt
    rewritten = re.sub(
        r"(shot centered strictly on )[^.]+\.",
        r"\1the exact person in the approved reference image.",
        prompt,
        count=1,
        flags=re.IGNORECASE,
    )
    traits = "; ".join(
        _clean(lock.get(key), 120)
        for key in (
            "gender_presentation", "approximate_age_band", "face_visibility_requirements", "hair",
            "skin_tone_appearance_from_reference", "clothing", "body_build", "pose_start_posture", "hand_visibility",
        )
        if _clean(lock.get(key), 120)
    )
    prefix = (
        "Animate the exact person shown in the supplied approved reference image. "
        "The approved reference image is authoritative for WHO appears. Preserve the same person, gender presentation, "
        "face, hairstyle, clothing, body proportions, skin appearance, hands, and subject count throughout. "
        "Do not replace, transform, reinterpret, or add to this person. "
    )
    if retry:
        prefix += "IDENTITY LOCK RETRY: use restrained motion; any identity or gender-presentation change is a failed result. "
    return " ".join(f"{prefix}Locked appearance: {traits}. {rewritten}".split())


def identity_qc_decision(result: dict[str, Any], attempt: int, max_attempts: int) -> dict[str, Any]:
    if not result.get("available"):
        return {"status": "IDENTITY_QC_UNAVAILABLE", "retry": False, "failed_checks": list(IDENTITY_QC_FIELDS)}
    failed = [field for field in IDENTITY_QC_FIELDS if str(result.get(field) or "").upper() != "PASS"]
    if not failed:
        return {"status": "PASS", "retry": False, "failed_checks": []}
    final_attempt = attempt + 1 >= max_attempts
    return {
        "status": "PROVIDER_IDENTITY_LIMITATION" if final_attempt else "IDENTITY_DRIFT",
        "retry": not final_attempt,
        "failed_checks": failed,
    }
