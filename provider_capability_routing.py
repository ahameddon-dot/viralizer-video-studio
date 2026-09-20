from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ShotCapability(StrEnum):
    STATIC_OBJECT = "STATIC_OBJECT"
    OBJECT_MOTION = "OBJECT_MOTION"
    CAMERA_REVEAL = "CAMERA_REVEAL"
    HUMAN_LOW_MOTION = "HUMAN_LOW_MOTION"
    HUMAN_HIGH_MOTION = "HUMAN_HIGH_MOTION"
    HUMAN_REPETITIVE_ACTION = "HUMAN_REPETITIVE_ACTION"
    TECHNICAL_PROCESS = "TECHNICAL_PROCESS"
    ENVIRONMENT_TRANSFORMATION = "ENVIRONMENT_TRANSFORMATION"


@dataclass(frozen=True)
class ProviderModeObservation:
    provider: str
    mode: str
    shot_capabilities: tuple[str, ...]
    attempts: int
    identity_preservation: str
    object_preservation: str
    continuity: str
    action_execution: str
    failure_classification: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


def classify_shot_capabilities(shot: dict[str, Any]) -> tuple[str, ...]:
    text = " ".join(
        str(shot.get(key) or "")
        for key in ("purpose", "visual_subject", "visual_description", "action", "camera", "foreground", "background")
    ).lower()
    capabilities: list[ShotCapability] = []
    tokens = set(re.findall("[a-z]+", text))
    human = bool(tokens.intersection({"person", "performer", "woman", "girl", "man", "boy", "athlete", "martial", "human", "hand", "hands", "face"}))
    repetitive = bool(tokens.intersection({"repeated", "repetitive", "rapid", "continuously", "sequence", "alternating", "multiple"}))
    high_motion = bool(tokens.intersection({"rapid", "punch", "punches", "punching", "sprint", "run", "jump", "fight", "dance", "kick", "throw"})) or "high-motion" in text
    if human and repetitive:
        capabilities.append(ShotCapability.HUMAN_REPETITIVE_ACTION)
    if human and high_motion:
        capabilities.append(ShotCapability.HUMAN_HIGH_MOTION)
    elif human:
        capabilities.append(ShotCapability.HUMAN_LOW_MOTION)
    if tokens.intersection({"machine", "assembly", "manufacturing", "workflow", "procedure"}) or "technical process" in text:
        capabilities.append(ShotCapability.TECHNICAL_PROCESS)
    if tokens.intersection({"transform", "transformation"}) or "changes into" in text or "environment shift" in text:
        capabilities.append(ShotCapability.ENVIRONMENT_TRANSFORMATION)
    if tokens.intersection({"pullback", "pan", "orbit", "reveal"}) or "camera reveal" in text or "push-in" in text:
        capabilities.append(ShotCapability.CAMERA_REVEAL)
    if tokens.intersection({"rotates", "falls", "slides", "opens", "closes"}) or "object move" in text:
        capabilities.append(ShotCapability.OBJECT_MOTION)
    if not capabilities:
        capabilities.append(ShotCapability.STATIC_OBJECT)
    return tuple(dict.fromkeys(item.value for item in capabilities))


def capability_route(
    shot: dict[str, Any],
    observations: list[ProviderModeObservation],
    *,
    fusion_supported: bool,
) -> dict[str, Any]:
    capabilities = classify_shot_capabilities(shot)
    same_configuration_failures = [
        item for item in observations
        if item.provider == "pixverse"
        and item.mode == "standard_image_to_video"
        and item.shot_capabilities == capabilities
        and item.attempts >= 2
        and item.identity_preservation == "strong"
        and item.object_preservation == "strong"
        and item.continuity == "strong"
        and item.action_execution == "failed"
    ]
    if same_configuration_failures:
        if fusion_supported and not any(item.mode == "fusion_reference_to_video" for item in observations):
            return {
                "provider": "pixverse",
                "mode": "fusion_reference_to_video",
                "reason": "Benchmark one documented alternate PixVerse mode after repeated action-only failure.",
                "standard_i2v_retry_allowed": False,
                "shot_capabilities": capabilities,
            }
        return {
            "provider": "alternate_video_provider",
            "mode": "capability_routed",
            "reason": "Approved planning and references passed, but PixVerse repeatedly failed the required physical action.",
            "standard_i2v_retry_allowed": False,
            "shot_capabilities": capabilities,
        }
    return {
        "provider": "pixverse",
        "mode": "standard_image_to_video",
        "reason": "No repeated action-only provider failure is recorded for this exact capability configuration.",
        "standard_i2v_retry_allowed": True,
        "shot_capabilities": capabilities,
    }
