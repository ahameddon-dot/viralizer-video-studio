from typing import Any


def topic_grounded_keyframe_prompt(content: dict[str, Any], scene: dict[str, Any], prompt: str) -> str:
    """Anchor a keyframe to approved story evidence, not source-format words."""
    title = " ".join(str(content.get("title") or content.get("topic") or "").split())[:240]
    hook = " ".join(str(content.get("hook") or content.get("strategy_summary") or "").split())[:500]
    scene_evidence = " ".join(str(
        scene.get("visual") or scene.get("visual_description") or scene.get("subject_action") or scene.get("description") or ""
    ).split())[:700]
    authority = " ".join(part for part in (title, hook, scene_evidence) if part)
    if not authority:
        return prompt
    return (
        f'STORY SUBJECT LOCK: this is a scene from "{title or authority}". '
        f"Approved story evidence: {authority}. The generated frame must visibly communicate this exact subject and scene beat. "
        "Treat words such as trailer, video, film, post, and promo as source-format metadata, not as objects to depict. "
        "Do not show a film reel, projector, clapperboard, camera rig, editing suite, generic studio equipment, or unrelated stock imagery "
        "unless the approved scene explicitly requires that object. Prefer concrete subject-specific people, places, actions, symbols, stakes, and consequences. "
        + prompt
    )
