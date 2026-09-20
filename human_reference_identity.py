from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import httpx


REFERENCE_IDENTITY_GATES = (
    "SUBJECT_COUNT_MATCH",
    "GENDER_PRESENTATION_MATCH",
    "AGE_BAND_MATCH",
    "ROLE_MATCH",
    "WARDROBE_MATCH",
    "HAND_STATE_MATCH",
    "REQUIRED_OBJECTS_PRESENT",
    "NO_FORBIDDEN_IDENTITY",
    "NO_EXTRA_PERSON",
    "NO_MAJOR_ANATOMY_FAILURE",
)


def _clean(value: Any, limit: int = 1000) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _evidence_text(shot: dict[str, Any], evidence: dict[str, Any] | None) -> str:
    return json.dumps({"shot": shot, "approved_evidence": evidence or {}}, ensure_ascii=True).lower()


def build_human_reference_identity_spec(shot: dict[str, Any], approved_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _evidence_text(shot, approved_evidence)
    gender = "female" if re.search(r"\b(?:female|girl|woman|she|her)\b", text) else "male" if re.search(r"\b(?:male|boy|man|he|his)\b", text) else "unspecified"
    age_match = re.search(r"\b(\d{1,2})[- ]year[- ]old\b", text)
    age_band = "adolescent" if age_match and 13 <= int(age_match.group(1)) < 18 else "child" if age_match and int(age_match.group(1)) < 13 else "adult" if age_match else "unspecified"
    martial_arts = any(term in text for term in ("martial arts", "martial artist", "punch", "karate"))
    eggs = "egg" in text
    if gender == "unspecified" or age_band == "unspecified" or not martial_arts:
        return {}
    objects = ["intact eggs"] if eggs else []
    return {
        "authority": "approved_article_and_story_evidence",
        "subject_count": 1,
        "gender_presentation": gender,
        "age_band": age_band,
        "role": "martial arts performer" if martial_arts else "human subject",
        "wardrobe": "plain age-appropriate unbranded athletic martial-arts training top and trousers with no rank-signifying belt, medals, badges, logos, or readable text",
        "pose": "stable front-facing S1 setup posture with the upper body and both hands clearly visible",
        "hand_state": "both anatomically correct hands fully visible, each securely holding an intact egg before the punching action begins" if eggs else "both hands visible in the approved S1 start pose",
        "objects": objects,
        "composition": _clean(shot.get("composition") or "medium eye-level view", 300),
        "environment": _clean(shot.get("environment") or "neutral restrained training background", 300),
        "forbidden_identity_changes": [
            "adult male subject" if gender == "female" else "adult female subject",
            "male-presenting subject" if gender == "female" else "female-presenting subject",
            "multiple performers",
            "incorrect age band",
            "identity ambiguity",
        ],
        "forbidden_visuals": [
            "second person", "crowd", "extra limbs", "malformed hands", "missing eggs",
            "broken eggs", "black belt or rank insignia", "trophies", "medals", "certificates", "badges", "judges",
            "logos", "readable generated text",
        ],
        "unsupported_personal_traits_prohibited": True,
    }


def compile_human_reference_prompt(spec: dict[str, Any], base_reference_prompt: str) -> tuple[str, str]:
    if not spec:
        return base_reference_prompt, ""
    objects = ", ".join(spec.get("objects") or [])
    prompt = (
        f"IDENTITY PRIORITY ONE: show exactly {spec['subject_count']} {spec['gender_presentation']}-presenting "
        f"{spec['age_band']} {spec['role']}. This identity is mandatory and overrides generic words such as athlete, performer, or martial artist. "
        f"WARDROBE: {spec['wardrobe']}. POSE: {spec['pose']}. HANDS: {spec['hand_state']}. "
        f"REQUIRED OBJECTS: {objects}. COMPOSITION: {spec['composition']}. ENVIRONMENT: {spec['environment']}. "
        "Create an article-supported visual representation only; do not claim an exact real-person likeness or invent unsupported personal traits. "
        + base_reference_prompt
    )
    negative = ", ".join("no " + item for item in [
        *(spec.get("forbidden_identity_changes") or []),
        *(spec.get("forbidden_visuals") or []),
    ])
    return " ".join(prompt.split()), negative


def strengthen_human_reference_prompt(prompt: str, failed_gates: list[str], correction: str = "") -> str:
    return " ".join((
        "REFERENCE IDENTITY RETRY. Identity compliance is mandatory before style. Correct these failed gates:",
        ", ".join(failed_gates) + ".",
        correction,
        prompt,
    )).strip()


async def score_human_reference_identity(image: bytes, spec: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return {"available": False, "status": "unavailable", "reason": "OPENAI_API_KEY is not configured"}
    instruction = (
        "Evaluate the supplied generated reference image against this approved Human Reference Identity Spec: "
        + json.dumps(spec, ensure_ascii=True)
        + ". Identity is the highest-priority fatal gate. Return JSON only. Include each of these keys with exactly PASS or FAIL: "
        + ", ".join(REFERENCE_IDENTITY_GATES)
        + ". Also return observed_identity_description, gender_presentation_result, age_band_result, hand_egg_result, "
        "subject_count_result, factual_evidence_result, failure_reasons (array), and corrective_instruction. "
        "Do not identify the real person or infer ethnicity, nationality, religion, health, or personality."
    )
    payload = {
        "model": os.getenv("OPENAI_QC_MODEL", "gpt-4.1-mini"),
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": instruction},
            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(image).decode()},
        ]}],
        "text": {"format": {"type": "json_object"}},
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": "Bearer " + key}, json=payload)
        if response.is_error:
            return {"available": False, "status": "unavailable", "reason": "Reference identity QC service rejected the request"}
        data = response.json()
        raw = data.get("output_text", "") or "".join(
            part.get("text", "") for item in data.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text"
        )
        result = json.loads(raw)
        result.update(available=True, status="complete")
        return result
    except Exception as exc:
        return {"available": False, "status": "unavailable", "reason": str(exc)[:240]}


def human_reference_identity_decision(result: dict[str, Any], attempt: int, max_attempts: int = 3) -> dict[str, Any]:
    if not result.get("available"):
        return {"status": "REFERENCE_IDENTITY_QC_UNAVAILABLE", "retry": False, "failed_gates": list(REFERENCE_IDENTITY_GATES)}
    failed = [gate for gate in REFERENCE_IDENTITY_GATES if str(result.get(gate) or "").upper() != "PASS"]
    if not failed:
        return {"status": "PASS", "retry": False, "failed_gates": []}
    final = attempt + 1 >= max_attempts
    return {
        "status": "REFERENCE_PROVIDER_IDENTITY_LIMITATION" if final else "REFERENCE_IDENTITY_FAIL",
        "retry": not final,
        "failed_gates": failed,
    }
