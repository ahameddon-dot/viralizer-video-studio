import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


def _connect(root: Path) -> sqlite3.Connection:
    data_dir = Path(os.getenv("APP_DATA_DIR", str(root / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(data_dir / "creatorthon.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS creatorthon_profiles (
      user_id TEXT PRIMARY KEY, email TEXT NOT NULL, full_name TEXT NOT NULL,
      company TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '',
      socials_json TEXT NOT NULL DEFAULT '{}', interests_json TEXT NOT NULL DEFAULT '[]',
      onboarding_complete INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS creatorthon_projects (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, topic_json TEXT NOT NULL,
      provider TEXT NOT NULL DEFAULT '', job_id TEXT NOT NULL DEFAULT '',
      video_url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_creatorthon_projects_user
    ON creatorthon_projects(user_id, updated_at DESC);
    """)
    return db


def get_profile(root: Path, user: dict[str, Any]) -> dict[str, Any]:
    with _connect(root) as db:
        row = db.execute("SELECT * FROM creatorthon_profiles WHERE user_id=?", (str(user.get("sub", "")),)).fetchone()
    if not row:
        return {"email": user.get("email", ""), "full_name": user.get("name", ""), "company": "",
                "role": "", "socials": {}, "interests": [], "onboarding_complete": False}
    result = dict(row)
    result["socials"] = json.loads(result.pop("socials_json") or "{}")
    result["interests"] = json.loads(result.pop("interests_json") or "[]")
    result["onboarding_complete"] = bool(result["onboarding_complete"])
    return result


def save_profile(root: Path, user: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    values = (
        str(user.get("sub", "")), str(user.get("email", "")),
        str(profile.get("full_name") or user.get("name") or "").strip(),
        str(profile.get("company") or "").strip(), str(profile.get("role") or "").strip(),
        json.dumps(profile.get("socials") or {}),
        json.dumps([str(x).strip() for x in profile.get("interests", []) if str(x).strip()][:4]),
        int(bool(profile.get("onboarding_complete"))), now,
    )
    with _connect(root) as db:
        db.execute("""INSERT INTO creatorthon_profiles VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,full_name=excluded.full_name,
        company=excluded.company,role=excluded.role,socials_json=excluded.socials_json,
        interests_json=excluded.interests_json,onboarding_complete=excluded.onboarding_complete,
        updated_at=excluded.updated_at""", values)
    return get_profile(root, user)


def create_project(root: Path, user_id: str, topic: dict[str, Any]) -> dict[str, Any]:
    project_id, now = uuid.uuid4().hex, int(time.time())
    with _connect(root) as db:
        db.execute("INSERT INTO creatorthon_projects (id,user_id,topic_json,created_at,updated_at) VALUES (?,?,?,?,?)",
                   (project_id, user_id, json.dumps(topic, ensure_ascii=False), now, now))
    return {"id": project_id, "topic": topic, "status": "draft", "created_at": now}


def update_project(root: Path, user_id: str, project_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {key: str(values.get(key) or "") for key in ("provider", "job_id", "video_url", "status") if key in values}
    if allowed:
        assignments = ",".join(f"{key}=?" for key in allowed)
        with _connect(root) as db:
            db.execute(f"UPDATE creatorthon_projects SET {assignments},updated_at=? WHERE id=? AND user_id=?",
                       [*allowed.values(), int(time.time()), project_id, user_id])
    with _connect(root) as db:
        row = db.execute("SELECT * FROM creatorthon_projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["topic"] = json.loads(result.pop("topic_json") or "{}")
    return result


def list_projects(root: Path, user_id: str) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute("SELECT * FROM creatorthon_projects WHERE user_id=? ORDER BY updated_at DESC LIMIT 12", (user_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["topic"] = json.loads(item.pop("topic_json") or "{}")
        result.append(item)
    return result
