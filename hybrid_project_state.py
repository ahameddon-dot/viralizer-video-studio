"""Shared project state and immutable storyboard revisions for UI/chat parity."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from creatorthon_store import _connect


SCENE_FIELDS = frozenset({"start", "end", "purpose", "narration", "on_screen_text", "camera", "keyframe_prompt", "motion_prompt"})


class RevisionConflictError(RuntimeError):
    def __init__(self, expected: int, current: int):
        super().__init__(f"Project revision changed: expected {expected}, current {current}.")
        self.expected = expected
        self.current = current


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value: Any, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


def _safe_scene_patch(patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict) or not patch:
        raise ValueError("A non-empty scene patch is required.")
    unknown = set(patch) - SCENE_FIELDS
    if unknown:
        raise ValueError(f"Unsupported scene fields: {', '.join(sorted(unknown))}.")
    safe: dict[str, Any] = {}
    for key, value in patch.items():
        if key in {"start", "end"}:
            if not isinstance(value, (int, float)) or value < 0 or value > 600:
                raise ValueError(f"{key} must be a time between 0 and 600 seconds.")
            safe[key] = value
        else:
            text = " ".join(str(value or "").split())
            if not text or len(text) > 4000:
                raise ValueError(f"{key} must contain 1 to 4000 characters.")
            safe[key] = text
    return safe


def _event(db: Any, project_id: str, customer_id: str, event_type: str, payload: dict[str, Any], correlation_id: str, now: int) -> dict[str, Any]:
    current = db.execute("SELECT COALESCE(MAX(sequence),0) AS n FROM hybrid_project_events WHERE project_context_id=?", (project_id,)).fetchone()
    sequence = int(dict(current)["n"]) + 1
    event_id = uuid.uuid4().hex
    row = db.execute(
        """INSERT INTO hybrid_project_events
        (id,project_context_id,customer_id,sequence,event_type,payload_json,correlation_id,created_at)
        VALUES(?,?,?,?,?,?,?,?) RETURNING *""",
        (event_id, project_id, customer_id, sequence, event_type, _json(payload), correlation_id, now),
    ).fetchone()
    return dict(row)


def ensure_autopilot_project(root: Path, customer_id: str, concept_id: str, actor_id: str = "") -> dict[str, Any]:
    now = int(time.time())
    with _connect(root) as db:
        concept = db.execute("SELECT content_json FROM autopilot_creative_concepts WHERE id=? AND customer_id=?", (concept_id, customer_id)).fetchone()
        if not concept:
            raise ValueError("Creative concept was not found for this customer.")
        project_id, candidate_id = "", uuid.uuid4().hex
        created = db.execute(
            """INSERT INTO hybrid_project_contexts
            (id,customer_id,concept_id,revision,created_at,updated_at)
            VALUES(?,?,?,1,?,?) ON CONFLICT(customer_id,concept_id) DO NOTHING RETURNING id""",
            (candidate_id, customer_id, concept_id, now, now),
        ).fetchone()
        if created:
            project_id = dict(created)["id"]
            storyboard = _load(dict(concept)["content_json"], {}).get("storyboard") or []
            if not storyboard:
                raise ValueError("Creative concept has no storyboard.")
            revision_id = uuid.uuid4().hex
            db.execute(
                """INSERT INTO hybrid_storyboard_revisions
                (id,project_context_id,customer_id,version,storyboard_json,change_summary,actor_type,actor_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (revision_id, project_id, customer_id, 1, _json(storyboard), "Initial storyboard imported", "system", actor_id, now),
            )
            db.execute("UPDATE hybrid_project_contexts SET active_storyboard_revision_id=? WHERE id=?", (revision_id, project_id))
            _event(db, project_id, customer_id, "project.created", {"revision": 1, "storyboard_revision_id": revision_id}, uuid.uuid4().hex, now)
        else:
            existing = db.execute(
                "SELECT id FROM hybrid_project_contexts WHERE customer_id=? AND concept_id=?",
                (customer_id, concept_id),
            ).fetchone()
            project_id = dict(existing)["id"]
    return get_project_context(root, customer_id, project_id)


def get_project_context(root: Path, customer_id: str, project_id: str) -> dict[str, Any]:
    with _connect(root) as db:
        project = db.execute("SELECT * FROM hybrid_project_contexts WHERE id=? AND customer_id=?", (project_id, customer_id)).fetchone()
        if not project:
            raise ValueError("Project context was not found for this customer.")
        item = dict(project)
        revision = db.execute(
            "SELECT * FROM hybrid_storyboard_revisions WHERE id=? AND project_context_id=? AND customer_id=?",
            (item["active_storyboard_revision_id"], project_id, customer_id),
        ).fetchone()
    active = dict(revision) if revision else None
    if active:
        active["storyboard"] = _load(active.pop("storyboard_json"), [])
    item["active_storyboard"] = active
    return item


def revise_storyboard_scene(root: Path, customer_id: str, project_id: str, scene_index: int, expected_revision: int,
                            patch: dict[str, Any], actor_type: str, actor_id: str = "", change_summary: str = "",
                            correlation_id: str = "") -> dict[str, Any]:
    if actor_type not in {"user_ui", "user_chat", "system"}:
        raise ValueError("Unsupported revision actor type.")
    safe_patch, now = _safe_scene_patch(patch), int(time.time())
    correlation_id = correlation_id or uuid.uuid4().hex
    invalidated = {"approvals": 0, "publications": 0, "workflow_steps": 0}
    with _connect(root) as db:
        project_row = db.execute("SELECT * FROM hybrid_project_contexts WHERE id=? AND customer_id=?", (project_id, customer_id)).fetchone()
        if not project_row:
            raise ValueError("Project context was not found for this customer.")
        project = dict(project_row)
        current = int(project["revision"])
        if current != expected_revision:
            raise RevisionConflictError(expected_revision, current)
        active_row = db.execute("SELECT * FROM hybrid_storyboard_revisions WHERE id=?", (project["active_storyboard_revision_id"],)).fetchone()
        active = dict(active_row)
        storyboard = _load(active["storyboard_json"], [])
        if scene_index < 0 or scene_index >= len(storyboard):
            raise ValueError("Storyboard scene was not found.")
        storyboard[scene_index] = {**storyboard[scene_index], **safe_patch}
        version, revision_id = current + 1, uuid.uuid4().hex
        updated = db.execute(
            """UPDATE hybrid_project_contexts SET active_storyboard_revision_id=?,revision=?,updated_at=?
            WHERE id=? AND customer_id=? AND revision=? RETURNING id""",
            (revision_id, version, now, project_id, customer_id, current),
        ).fetchone()
        if not updated:
            latest = db.execute("SELECT revision FROM hybrid_project_contexts WHERE id=?", (project_id,)).fetchone()
            raise RevisionConflictError(expected_revision, int(dict(latest)["revision"]))
        db.execute(
            """INSERT INTO hybrid_storyboard_revisions
            (id,project_context_id,customer_id,version,parent_revision_id,storyboard_json,change_summary,actor_type,actor_id,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (revision_id, project_id, customer_id, version, active["id"], _json(storyboard), change_summary[:500], actor_type, actor_id, now),
        )
        db.execute(
            """INSERT INTO hybrid_scene_revisions
            (id,storyboard_revision_id,project_context_id,customer_id,scene_index,patch_json,actor_type,actor_id,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, revision_id, project_id, customer_id, scene_index, _json(safe_patch), actor_type, actor_id, now),
        )
        concept_row = db.execute("SELECT content_json FROM autopilot_creative_concepts WHERE id=? AND customer_id=?", (project["concept_id"], customer_id)).fetchone()
        content = _load(dict(concept_row)["content_json"], {})
        content["storyboard"] = storyboard
        for keyframe in (content.get("keyframes") or {}).get(str(scene_index), []):
            keyframe["stale"] = True
            keyframe["stale_reason"] = f"storyboard revision {version} changed scene {scene_index + 1}"
        db.execute("UPDATE autopilot_creative_concepts SET content_json=?,updated_at=? WHERE id=? AND customer_id=?", (_json(content), now, project["concept_id"], customer_id))
        assets = db.execute("SELECT id,workflow_run_id FROM autopilot_asset_versions WHERE customer_id=? AND concept_id=?", (customer_id, project["concept_id"])).fetchall()
        asset_ids = [dict(row)["id"] for row in assets]
        run_ids = sorted({dict(row)["workflow_run_id"] for row in assets})
        for asset_id in asset_ids:
            cursor = db.execute("UPDATE autopilot_publications SET status='cancelled',error_json=?,updated_at=? WHERE customer_id=? AND asset_version_id=? AND status IN ('queued','scheduled','failed')", (_json({"reason": "storyboard_changed", "project_revision": version}), now, customer_id, asset_id))
            invalidated["publications"] += max(0, cursor.rowcount)
            cursor = db.execute("UPDATE autopilot_content_approvals SET status='revoked',revoked_at=? WHERE customer_id=? AND asset_version_id=? AND status IN ('approved','consumed') AND NOT EXISTS (SELECT 1 FROM autopilot_publications p WHERE p.approval_id=autopilot_content_approvals.id AND p.status IN ('submitting','processing','published'))", (now, customer_id, asset_id))
            invalidated["approvals"] += max(0, cursor.rowcount)
        for run_id in run_ids:
            cursor = db.execute("UPDATE autopilot_workflow_steps SET status='cancelled',updated_at=? WHERE customer_id=? AND run_id=? AND agent_type='publishing' AND status IN ('queued','retry_wait')", (now, customer_id, run_id))
            invalidated["workflow_steps"] += max(0, cursor.rowcount)
        event = _event(db, project_id, customer_id, "storyboard.revision.created", {"revision": version, "storyboard_revision_id": revision_id, "scene_index": scene_index, "patch": safe_patch, "invalidated": invalidated}, correlation_id, now)
    return {"project": get_project_context(root, customer_id, project_id), "event": event, "invalidated": invalidated}


def list_project_events(root: Path, customer_id: str, project_id: str, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    with _connect(root) as db:
        exists = db.execute("SELECT id FROM hybrid_project_contexts WHERE id=? AND customer_id=?", (project_id, customer_id)).fetchone()
        if not exists:
            raise ValueError("Project context was not found for this customer.")
        rows = db.execute(
            "SELECT * FROM hybrid_project_events WHERE project_context_id=? AND customer_id=? AND sequence>? ORDER BY sequence LIMIT ?",
            (project_id, customer_id, max(0, after), max(1, min(500, limit))),
        ).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["payload"] = _load(event.pop("payload_json"), {})
        events.append(event)
    return events
