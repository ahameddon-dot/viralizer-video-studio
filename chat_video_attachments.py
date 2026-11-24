"""Durable video-production snapshots attached to assistant chat threads."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from creatorthon_store import _connect


def _ensure(db: Any) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS autopilot_chat_video_attachments (
          customer_id TEXT NOT NULL,
          chat_conversation_id TEXT NOT NULL,
          subject TEXT NOT NULL,
          mode TEXT NOT NULL,
          snapshot_json TEXT NOT NULL DEFAULT '{}',
          final_asset_id TEXT NOT NULL DEFAULT '',
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          PRIMARY KEY(customer_id, chat_conversation_id, subject, mode)
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_video_attachments_updated "
        "ON autopilot_chat_video_attachments(customer_id,chat_conversation_id,updated_at)"
    )


def _decode(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    try:
        item["snapshot"] = json.loads(item.pop("snapshot_json") or "{}")
    except (TypeError, ValueError):
        item["snapshot"] = {}
    return item


def save(
    root: Path,
    customer_id: str,
    chat_conversation_id: str,
    subject: str,
    mode: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    now = int(time.time())
    final_asset = snapshot.get("finalAsset") or {}
    final_asset_id = str(final_asset.get("id") or "") if isinstance(final_asset, dict) else ""
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    row = None
    for attempt in range(4):
        try:
            with _connect(root) as db:
                _ensure(db)
                db.execute(
                    """INSERT INTO autopilot_chat_video_attachments
                    (customer_id,chat_conversation_id,subject,mode,snapshot_json,final_asset_id,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(customer_id,chat_conversation_id,subject,mode) DO UPDATE SET
                      snapshot_json=excluded.snapshot_json,
                      final_asset_id=excluded.final_asset_id,
                      updated_at=excluded.updated_at""",
                    (customer_id, chat_conversation_id, subject, mode, encoded, final_asset_id, now, now),
                )
                row = db.execute(
                    """SELECT * FROM autopilot_chat_video_attachments
                    WHERE customer_id=? AND chat_conversation_id=? AND subject=? AND mode=?""",
                    (customer_id, chat_conversation_id, subject, mode),
                ).fetchone()
            break
        except Exception as exc:
            retryable = "deadlock" in str(exc).lower() or "serialization" in str(exc).lower()
            if not retryable or attempt == 3:
                raise
            time.sleep(0.05 * (2 ** attempt))
    return _decode(row) or {}


def get(
    root: Path,
    customer_id: str,
    chat_conversation_id: str,
    subject: str = "",
    mode: str = "",
) -> dict[str, Any] | None:
    query = (
        "SELECT * FROM autopilot_chat_video_attachments "
        "WHERE customer_id=? AND chat_conversation_id=?"
    )
    params: list[Any] = [customer_id, chat_conversation_id]
    if subject:
        query += " AND subject=?"
        params.append(subject)
    if mode:
        query += " AND mode=?"
        params.append(mode)
    query += " ORDER BY updated_at DESC LIMIT 1"
    with _connect(root) as db:
        _ensure(db)
        row = db.execute(query, tuple(params)).fetchone()
    return _decode(row)
