from __future__ import annotations

from numbers import Real
from typing import Any


SCORE_FIELDS = (
    "relevance",
    "visual_quality",
    "composition",
    "stability",
    "artifacts",
    "overall_quality_score",
    "semantic_alignment_score",
    "identity_confidence",
)


def _scale_hint(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace(" ", "")
    aliases = {
        "0-1": "0-1", "0to1": "0-1", "1": "0-1",
        "0-10": "0-10", "0to10": "0-10", "10": "0-10",
        "0-100": "0-100", "0to100": "0-100", "100": "0-100",
    }
    return aliases.get(text)


def _strong_pass_context(payload: dict[str, Any]) -> bool:
    categorical = [
        value.upper()
        for key, value in payload.items()
        if isinstance(value, str)
        and (
            key == "decision"
            or key.endswith("_PASS")
            or key.startswith(("SAME_", "GENDER_", "AGE_", "FACE_", "HAIR_", "CLOTHING_", "BODY_", "SUBJECT_"))
            or key in {
                "APPROVED_S1_ACTION_ONLY", "MODEST_CONTROLLED_PREPARATION_VISIBLE",
                "FACE_AND_BOTH_HANDS_READABLE", "EGG_COUNT_AND_PLACEMENT_PRESERVED",
                "ONE_SUBJECT_ONLY", "CAMERA_AND_COMPOSITION_STABLE",
                "BACKGROUND_AND_LIGHTING_PRESERVED", "UNSUPPORTED_ELEMENTS_ABSENT",
                "TECHNICAL_QUALITY_ACCEPTABLE",
            }
        )
        and value.upper() in {"PASS", "FAIL"}
    ]
    issues = payload.get("issues", payload.get("failure_reasons", []))
    return bool(categorical) and all(value == "PASS" for value in categorical) and not issues


def detect_score_scale(values: list[float], payload: dict[str, Any]) -> str:
    explicit = _scale_hint(payload.get("score_scale") or payload.get("detected_scale"))
    if explicit:
        return explicit
    if not values or any(value < 0 or value > 100 for value in values):
        return "SCORE_SCALE_AMBIGUOUS"
    maximum = max(values)
    if maximum > 10:
        return "0-100"
    if maximum <= 1 and any(0 < value < 1 for value in values):
        return "0-1"
    if 1 < maximum <= 10 and _strong_pass_context(payload) and maximum >= 9:
        return "0-10"
    return "SCORE_SCALE_AMBIGUOUS"


def normalize_qc_scores(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize known QC score fields to 0-100 without changing PASS/FAIL fields."""
    result = dict(payload)
    present = {
        field: float(result[field])
        for field in SCORE_FIELDS
        if isinstance(result.get(field), Real) and not isinstance(result.get(field), bool)
    }
    if not present:
        return result
    detected = detect_score_scale(list(present.values()), result)
    result["raw_scores"] = {
        field: payload[field] for field in present
    }
    result["detected_scale"] = detected
    if detected == "SCORE_SCALE_AMBIGUOUS":
        result["normalized_scores"] = {field: None for field in present}
        result["score_normalization_status"] = "SCORE_SCALE_AMBIGUOUS"
        if "overall_quality_score" in present:
            result["raw_score"] = payload["overall_quality_score"]
            result["normalized_score"] = None
        return result
    factor = {"0-1": 100.0, "0-10": 10.0, "0-100": 1.0}[detected]
    normalized = {
        field: round(value * factor, 4) for field, value in present.items()
    }
    for field, value in normalized.items():
        result[field] = int(value) if value.is_integer() else value
    result["normalized_scores"] = {
        field: result[field] for field in present
    }
    result["score_normalization_status"] = "NORMALIZED"
    if "overall_quality_score" in present:
        result["raw_score"] = payload["overall_quality_score"]
        result["normalized_score"] = result["overall_quality_score"]
    return result
