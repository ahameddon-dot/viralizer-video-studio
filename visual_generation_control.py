from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from openai_image_client import generate_instagram_image, generate_reference_image
from pixverse_client import PixVerseClient
from human_reference_identity import compile_human_reference_prompt


def _clean(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean(item, 400) for item in value if _clean(item, 400)]
    return [_clean(value, 400)] if _clean(value, 400) else []


MOTION_WORDS = re.compile(
    r"\b(?:moves?|moving|travels?|widens?|extends?|settles?|reveals?|resolves?|"
    r"turns?|lifts?|places?|breaks?|falls?|responds?|push(?:es)?|pulls?|pans?|zooms?)\b",
    re.IGNORECASE,
)


def describe_start_end_frames(shot: dict[str, Any]) -> tuple[str, str]:
    """Translate an approved shot into boundary states without changing its meaning."""
    subject = _clean(shot.get("visual_subject"), 300)
    environment = _clean(shot.get("environment"), 300)
    composition = _clean(shot.get("composition"), 300)
    action = _clean(shot.get("action") or shot.get("visual_description"), 600)
    action_lower = action.lower()
    derived_start = f"Before the approved action: {subject} in {environment}; {composition}."
    derived_end = f"After the approved action ({action}): the same {subject}, environment, composition logic, identity, geometry, and materials remain preserved."
    if "near-shadow" in action_lower and ("silhouette" in action_lower or "light" in action_lower):
        derived_start = f"A dark composition in {environment}, with only a partial silhouette of {subject} visible; {composition}."
        derived_end = f"The same composition with the silhouette of {subject} clearly revealed by the narrow gallery light; identity, geometry, materials, and environment remain unchanged."
    elif "light widens" in action_lower and "public view" in action_lower:
        derived_end = f"A wider exhibition composition shows the same {subject} fully returned to public view as floor reflections extend outward; identity, geometry, materials, lighting direction, and environment remain continuous."
    elif "settle" in action_lower and ("public display" in action_lower or "hero" in action_lower):
        derived_end = f"Clean, stable final hero composition of the same {subject} as the renewed focus of the complete public display; identity, geometry, materials, lighting, and spatial relationships remain fixed."
    start = _clean(
        shot.get("start_frame")
        or derived_start,
        900,
    )
    end = _clean(
        shot.get("end_frame")
        or derived_end,
        1000,
    )
    return start, end


def enrich_storyboard_frames(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    previous_end = ""
    previous_subject = ""
    for original in shots:
        shot = dict(original)
        start, end = describe_start_end_frames(shot)
        subject = _clean(shot.get("visual_subject"), 300).lower()
        can_reuse = bool(previous_end and subject and subject == previous_subject)
        contract = shot.get("action_outcome_contract") if isinstance(shot.get("action_outcome_contract"), dict) else {}
        result_state_required = bool(
            contract.get("result_shot_required")
            and str(shot.get("purpose") or "").strip().upper() == "HERO PAYOFF"
        )
        # A result shot may reuse the previous frame as its image-editing source,
        # but its approved start-state language must remain the observable result.
        # Replacing that language with the previous end frame caused the motion
        # prompt to show an action without proving its article-supported outcome.
        shot["start_frame"] = start if result_state_required else (previous_end if can_reuse else start)
        shot["end_frame"] = end
        if can_reuse and result_state_required:
            shot["continuity_frame_strategy"] = "reuse_previous_end_frame_to_build_result_state"
        else:
            shot["continuity_frame_strategy"] = "reuse_previous_end_frame" if can_reuse else "generate_controlled_start_frame"
        shot["reuse_previous_end_frame"] = can_reuse
        enriched.append(shot)
        previous_end, previous_subject = end, subject
    return enriched


def compile_reference_prompt(
    storyboard_shot: dict[str, Any],
    reference_plan: dict[str, Any],
    factual_boundaries: list[str] | None = None,
    core_visual_subject: str = "",
    human_identity_spec: dict[str, Any] | None = None,
) -> str:
    """Compile a still-image composition prompt from approved upstream authority."""
    shot_id = _clean(storyboard_shot.get("shot_id") or reference_plan.get("shot_id"), 24)
    opening_state = _clean(storyboard_shot.get("start_frame"), 1000)
    approved_description = _clean(storyboard_shot.get("visual_description"), 1000)
    static_description = opening_state or MOTION_WORDS.sub("is visible", approved_description)
    fields = {
        "core visual subject": core_visual_subject or reference_plan.get("subject") or storyboard_shot.get("visual_subject"),
        "approved start-frame state": opening_state,
        "visual description": static_description,
        "environment": reference_plan.get("environment") or storyboard_shot.get("environment"),
        "composition": reference_plan.get("composition") or storyboard_shot.get("composition"),
        "camera position": reference_plan.get("camera_position") or storyboard_shot.get("camera"),
        "lens feel": reference_plan.get("lens_feel"),
        "lighting": reference_plan.get("lighting") or storyboard_shot.get("lighting"),
        "wardrobe or materials": reference_plan.get("wardrobe_or_materials"),
        "important objects": "; ".join(_items(reference_plan.get("important_objects") or storyboard_shot.get("must_show"))),
        "spatial relationships": "; ".join(_items(reference_plan.get("spatial_relationships"))),
        "visual style": reference_plan.get("visual_style"),
        "must preserve": "; ".join(_items(reference_plan.get("must_preserve"))),
        "must not generate": "; ".join(_items(reference_plan.get("must_not_generate") or storyboard_shot.get("must_avoid"))),
        "factual boundaries": "; ".join(_items(factual_boundaries)),
    }
    result_state = reference_plan.get("result_state_reference") if isinstance(reference_plan.get("result_state_reference"), dict) else {}
    if result_state:
        fields["required post-action state"] = result_state.get("post_action_state")
        fields["successful completion proof"] = result_state.get("successful_completion_proof")
        fields["result-state continuity locks"] = "; ".join(_items(result_state.get("must_remain_unchanged")))
        fields["result-state exclusions"] = "; ".join(_items(result_state.get("must_not_appear")))
    # Camera movement belongs to Motion Director. Keep only the static viewpoint language.
    fields["camera position"] = re.sub(
        r"\b(?:slow|controlled|gentle|very slow)?\s*(?:push-in|pullback|pull back|pan|zoom|tracking|lateral move|camera move)\b",
        "static viewpoint",
        _clean(fields["camera position"], 400),
        flags=re.IGNORECASE,
    )
    if " while " in fields["camera position"].lower() or MOTION_WORDS.search(fields["camera position"]):
        fields["camera position"] = "static viewpoint preserving the approved camera orientation and framing"
    parts = [f"{name.title()}: {_clean(value, 1000)}." for name, value in fields.items() if _clean(value, 1000)]
    base_prompt = _clean(
        f"Reference start frame for {shot_id}: render one controlled reference still, not a motion sequence. "
        + " ".join(parts)
        + " Preserve the approved composition exactly. No readable text, captions, watermarks, generated logos, duplicated subjects, or anatomy/geometry failure.",
        5000,
    )
    prompt, negative = compile_human_reference_prompt(human_identity_spec or {}, base_prompt)
    if negative:
        prompt = _clean(prompt + " Negative reference constraints: " + negative + ".", 5000)
    return prompt


def build_reference_qc_spec(shot: dict[str, Any], reference_plan: dict[str, Any], factual_boundaries: list[str] | None = None, human_identity_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "shot_id": shot.get("shot_id"),
        "core_subject_present": reference_plan.get("subject") or shot.get("visual_subject"),
        "composition_match": reference_plan.get("composition") or shot.get("composition"),
        "material_or_wardrobe_match": reference_plan.get("wardrobe_or_materials"),
        "environment_match": reference_plan.get("environment") or shot.get("environment"),
        "important_objects_present": _items(reference_plan.get("important_objects") or shot.get("must_show")),
        "forbidden_objects_absent": _items(reference_plan.get("must_not_generate") or shot.get("must_avoid")),
        "factual_boundaries_respected": _items(factual_boundaries),
        "no_generated_readable_text": True,
        "no_unauthorized_logos": True,
        "no_information_panels_plaques_documents_or_labels": True,
        "no_pseudo_text_surfaces": True,
        "no_subject_duplication": True,
        "no_geometry_or_anatomy_failure": True,
    }
    if reference_plan.get("result_state_reference"):
        result["result_state_reference"] = reference_plan["result_state_reference"]
        result["result_state_visible"] = True
    if human_identity_spec:
        result["human_identity_spec"] = human_identity_spec
        result["qc_priority"] = ["IDENTITY", "REQUIRED_OBJECTS_AND_HANDS", "FACTUAL_EVIDENCE", "COMPOSITION", "STYLE_AND_VISUAL_QUALITY"]
    return result


def qc_decision(result: dict[str, Any]) -> dict[str, str]:
    if not result.get("available"):
        return {"status": "BLOCKED", "correction": _clean(result.get("reason") or "Reference QC was unavailable", 500)}
    score = float(result.get("overall_quality_score") or 0)
    decision = str(result.get("decision") or result.get("semantic_validation_status") or "").upper()
    passed = score >= 85 and decision == "PASS"
    correction = _clean(result.get("corrective_instruction") or result.get("failure_reason"), 500)
    return {"status": "PASS" if passed else "REGENERATE", "correction": "" if passed else (correction or "Regenerate to match the approved reference specification.")}


@dataclass(frozen=True)
class ReferenceProviderCapabilities:
    supports_generation: bool
    supports_reference_edit: bool
    model: str


class ReferenceImageProvider(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> ReferenceProviderCapabilities: ...

    @abstractmethod
    async def generate(self, prompt: str, source_image: bytes | None = None) -> bytes: ...


class OpenAIReferenceImageProvider(ReferenceImageProvider):
    @property
    def capabilities(self) -> ReferenceProviderCapabilities:
        return ReferenceProviderCapabilities(
            supports_generation=bool(os.getenv("OPENAI_API_KEY", "").strip()),
            supports_reference_edit=True,
            model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        )

    async def generate(self, prompt: str, source_image: bytes | None = None) -> bytes:
        if source_image is not None:
            return await generate_reference_image(source_image, prompt)
        return await generate_instagram_image({}, prompt, purpose="pixverse")


def configured_reference_provider() -> ReferenceImageProvider:
    provider = os.getenv("REFERENCE_IMAGE_PROVIDER", "openai").strip().lower()
    if provider != "openai":
        raise RuntimeError(f"Unsupported REFERENCE_IMAGE_PROVIDER: {provider}. Configured options: openai.")
    return OpenAIReferenceImageProvider()


@dataclass(frozen=True)
class VideoProviderCapabilities:
    supports_text_to_video: bool
    supports_image_to_video: bool
    supports_start_frame: bool
    supports_end_frame: bool
    supports_reference_images: bool
    supported_durations: tuple[int, ...]
    supported_aspect_ratios: tuple[str, ...]
    supports_audio: bool
    supports_negative_prompt: bool = False
    supports_seed: bool = True
    supports_motion_mode: bool = True
    supports_identity_strength: bool = False
    supports_character_consistency_control: bool = False
    supports_reference_strength: bool = False
    supports_fusion_reference_to_video: bool = False


class VideoProvider(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> VideoProviderCapabilities: ...

    @abstractmethod
    async def generate_shot(self, *, motion_prompt: str, text_prompt: str, start_reference: bytes | None, end_reference: bytes | None, duration: int, aspect_ratio: str, quality: str, negative_prompt: str) -> dict[str, Any]: ...


class PixVerseProvider(VideoProvider):
    def __init__(self, client: PixVerseClient | None = None):
        self.client = client or PixVerseClient()

    @property
    def capabilities(self) -> VideoProviderCapabilities:
        return VideoProviderCapabilities(
            True, True, True, False, True, (5, 8, 10),
            ("16:9", "9:16", "1:1", "3:4", "4:3"), False,
            supports_negative_prompt=True,
            supports_seed=True,
            supports_motion_mode=True,
            supports_fusion_reference_to_video=True,
        )

    async def generate_shot(self, *, motion_prompt: str, text_prompt: str, start_reference: bytes | None, end_reference: bytes | None, duration: int, aspect_ratio: str, quality: str, negative_prompt: str) -> dict[str, Any]:
        if duration not in self.capabilities.supported_durations:
            raise ValueError(f"PixVerse duration {duration} is unsupported; use one of {self.capabilities.supported_durations}.")
        if aspect_ratio not in self.capabilities.supported_aspect_ratios:
            raise ValueError(f"PixVerse aspect ratio {aspect_ratio} is unsupported.")
        if end_reference is not None:
            raise ValueError("The configured PixVerse API does not support an end-frame image.")
        if start_reference is not None:
            image_id = await self.client.upload_image(image_bytes=start_reference, filename="reference.png", content_type="image/png")
            video_id = await self.client.generate_from_image(
                image_id,
                motion_prompt,
                duration=duration,
                quality=quality,
                negative_prompt=negative_prompt,
                motion_mode="normal",
                seed=0,
            )
            return {
                "video_id": video_id,
                "mode": "image_to_video",
                "image_id": image_id,
                "controls": {"motion_mode": "normal", "seed": 0, "negative_prompt": negative_prompt},
                "capabilities": asdict(self.capabilities),
            }
        video_id = await self.client.generate(text_prompt, duration=duration, quality=quality, negative_prompt=negative_prompt, aspect_ratio=aspect_ratio)
        return {"video_id": video_id, "mode": "text_to_video", "capabilities": asdict(self.capabilities)}


def continuity_qc_spec(previous_shot: dict[str, Any], next_shot: dict[str, Any]) -> dict[str, Any]:
    return {
        "previous_shot_id": previous_shot.get("shot_id"),
        "next_shot_id": next_shot.get("shot_id"),
        "expected_previous_end": previous_shot.get("end_frame"),
        "expected_next_start": next_shot.get("start_frame"),
        "evaluate": ["subject consistency", "object geometry", "environment", "camera direction", "lighting", "scale", "spatial relationships", "motion direction"],
        "failure_action": "REGENERATE NEXT SHOT",
    }


def continuity_preflight(previous_shot: dict[str, Any], next_shot: dict[str, Any]) -> dict[str, Any]:
    same_subject = _clean(previous_shot.get("visual_subject"), 300).lower() == _clean(next_shot.get("visual_subject"), 300).lower()
    frame_linked = bool(next_shot.get("reuse_previous_end_frame")) and _clean(previous_shot.get("end_frame"), 1000) == _clean(next_shot.get("start_frame"), 1000)
    return {"status": "PASS" if same_subject and frame_linked else "REGENERATE NEXT SHOT", "checks": {"subject_consistency": same_subject, "frame_boundary_linked": frame_linked}, "correction": "" if same_subject and frame_linked else "Regenerate the next shot from the approved previous ending frame while preserving subject, geometry, environment, camera direction, lighting, scale, and spatial relationships."}


def regeneration_scope(shot_id: str, gate: str, correction: str = "") -> dict[str, str]:
    """Make retries explicit and local; upstream plans and accepted shots are immutable."""
    return {"action": "REGENERATE_SHOT", "shot_id": str(shot_id), "failed_gate": str(gate), "correction": _clean(correction, 600)}


def assembly_eligibility(shots: list[dict[str, Any]]) -> dict[str, Any]:
    failures = []
    for index, shot in enumerate(shots):
        required = ("reference_qc", "motion_semantic_qc", "shot_visual_qc")
        failures.extend(f"{shot.get('shot_id', index + 1)}:{gate}" for gate in required if str(shot.get(gate) or "").upper() != "PASS")
        if index and str(shot.get("continuity_qc") or "").upper() != "PASS":
            failures.append(f"{shot.get('shot_id', index + 1)}:continuity_qc")
    return {"eligible": not failures, "status": "PASS" if not failures else "BLOCKED", "failures": failures}
