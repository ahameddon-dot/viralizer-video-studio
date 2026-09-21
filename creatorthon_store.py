import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_POSTGRES_READY = False


class _PostgresAdapter:
    dialect = "postgres"

    def __init__(self, connection: Any):
        self.connection = connection

    def execute(self, query: str, params: Any = None):
        return self.connection.execute(query.replace("?", "%s"), params or ())

# Persistent user workspace schema. Existing SQLite databases are migrated in place.
PROJECT_JSON_FIELDS = {
    "prompt": "prompt_json", "narration": "narration_json",
    "configuration": "configuration_json", "article_intelligence": "article_intelligence_json",
    "production": "production_json", "qc": "qc_json",
}
PROJECT_TEXT_FIELDS = {
    "provider", "job_id", "video_url", "thumbnail_url", "status", "aspect_ratio", "quality", "title",
}


def _json_load(value: Any, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _ensure_column(db: Any, table: str, name: str, declaration: str) -> None:
    if getattr(db, "dialect", "sqlite") == "postgres":
        db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {declaration}")
        return
    existing = {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}
    if name not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _schema_statements() -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS creatorthon_profiles (
          user_id TEXT PRIMARY KEY, email TEXT NOT NULL, full_name TEXT NOT NULL,
          company TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '',
          socials_json TEXT NOT NULL DEFAULT '{}', interests_json TEXT NOT NULL DEFAULT '[]',
          onboarding_complete INTEGER NOT NULL DEFAULT 0, updated_at BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS creatorthon_projects (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, topic_json TEXT NOT NULL,
          provider TEXT NOT NULL DEFAULT '', job_id TEXT NOT NULL DEFAULT '', video_url TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'draft', created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_creatorthon_projects_user ON creatorthon_projects(user_id, updated_at DESC)",
        """CREATE TABLE IF NOT EXISTS creatorthon_reports (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
          report_type TEXT NOT NULL DEFAULT 'topic-research', source_url TEXT NOT NULL DEFAULT '',
          content_json TEXT NOT NULL DEFAULT '{}', created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_creatorthon_reports_user ON creatorthon_reports(user_id, updated_at DESC)",
        """CREATE TABLE IF NOT EXISTS creatorthon_assets (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
          url TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at BIGINT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_creatorthon_assets_user ON creatorthon_assets(user_id, created_at DESC)",
    ]


def _project_columns() -> tuple[tuple[str, str], ...]:
    return (
        ("title", "TEXT NOT NULL DEFAULT ''"), ("prompt_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("narration_json", "TEXT NOT NULL DEFAULT '{}'"), ("configuration_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("article_intelligence_json", "TEXT NOT NULL DEFAULT '{}'"), ("production_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("qc_json", "TEXT NOT NULL DEFAULT '{}'"), ("thumbnail_url", "TEXT NOT NULL DEFAULT ''"),
        ("aspect_ratio", "TEXT NOT NULL DEFAULT ''"), ("quality", "TEXT NOT NULL DEFAULT ''"),
    )


@contextmanager
def _connect(root: Path) -> Iterator[Any]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL is configured but psycopg is not installed.") from exc
        # Supabase's transaction pooler does not support named prepared statements.
        connection = psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
        db = _PostgresAdapter(connection)
        global _POSTGRES_READY
        try:
            if not _POSTGRES_READY:
                for statement in _schema_statements():
                    db.execute(statement)
                for name, declaration in _project_columns():
                    _ensure_column(db, "creatorthon_projects", name, declaration)
                connection.commit()
                _POSTGRES_READY = True
            yield db
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return
    data_dir = Path(os.getenv("APP_DATA_DIR", str(root / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(data_dir / "creatorthon.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
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
    CREATE TABLE IF NOT EXISTS creatorthon_reports (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '', report_type TEXT NOT NULL DEFAULT 'topic-research',
      source_url TEXT NOT NULL DEFAULT '', content_json TEXT NOT NULL DEFAULT '{}',
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_creatorthon_reports_user ON creatorthon_reports(user_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS creatorthon_assets (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL, url TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_creatorthon_assets_user ON creatorthon_assets(user_id, created_at DESC);
    """)
    for name, declaration in _project_columns():
        _ensure_column(db, "creatorthon_projects", name, declaration)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def database_health(root: Path) -> dict[str, Any]:
    """Return a secret-free database readiness result for deployment diagnostics."""
    configured = bool(os.getenv("DATABASE_URL", "").strip())
    backend = "postgres" if configured else "sqlite"
    try:
        with _connect(root) as db:
            row = db.execute("SELECT 1 AS ready").fetchone()
        ready = bool(row and (dict(row).get("ready") if hasattr(row, "keys") else row[0]))
        return {"configured": configured, "backend": backend, "ready": ready, "error": ""}
    except Exception as exc:
        message = str(exc).lower()
        if "password authentication failed" in message or "authentication failed" in message:
            category = "authentication_failed"
        elif "name or service not known" in message or "could not translate host" in message:
            category = "host_not_found"
        elif "timeout" in message or "timed out" in message:
            category = "connection_timeout"
        elif "ssl" in message or "certificate" in message:
            category = "tls_error"
        elif "database_url is configured but psycopg" in message:
            category = "driver_missing"
        elif "invalid" in message and ("dsn" in message or "uri" in message or "connection" in message):
            category = "invalid_connection_string"
        elif "permission denied" in message or "insufficient privilege" in message:
            category = "database_permission_denied"
        else:
            category = "database_unavailable"
        return {"configured": configured, "backend": backend, "ready": False, "error": category}


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


def _project(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["topic"] = _json_load(result.pop("topic_json", "{}"), {})
    for public, column in PROJECT_JSON_FIELDS.items():
        result[public] = _json_load(result.pop(column, "{}"), {})
    return result


def create_project(root: Path, user_id: str, topic: dict[str, Any], values: dict[str, Any] | None = None) -> dict[str, Any]:
    project_id, now = uuid.uuid4().hex, int(time.time())
    title = str(topic.get("title") or topic.get("topic") or "Untitled project").strip()[:500]
    with _connect(root) as db:
        db.execute("INSERT INTO creatorthon_projects (id,user_id,topic_json,title,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                   (project_id, user_id, json.dumps(topic, ensure_ascii=False), title, now, now))
    return update_project(root, user_id, project_id, values or {}) or {}


def update_project(root: Path, user_id: str, project_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    allowed: dict[str, Any] = {key: str(values.get(key) or "") for key in PROJECT_TEXT_FIELDS if key in values}
    if "topic" in values and isinstance(values["topic"], dict):
        allowed["topic_json"] = json.dumps(values["topic"], ensure_ascii=False)
    for public, column in PROJECT_JSON_FIELDS.items():
        if public in values:
            value = values[public]
            if public in {"prompt", "narration"} and isinstance(value, str):
                value = {"text": value}
            allowed[column] = json.dumps(value or {}, ensure_ascii=False)
    with _connect(root) as db:
        if allowed:
            assignments = ",".join(f"{key}=?" for key in allowed)
            db.execute(f"UPDATE creatorthon_projects SET {assignments},updated_at=? WHERE id=? AND user_id=?",
                       [*allowed.values(), int(time.time()), project_id, user_id])
        row = db.execute("SELECT * FROM creatorthon_projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
    return _project(row) if row else None


def list_projects(root: Path, user_id: str, limit: int = 50, status: str = "") -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    query, params = "SELECT * FROM creatorthon_projects WHERE user_id=?", [user_id]
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with _connect(root) as db:
        rows = db.execute(query, params).fetchall()
    return [_project(row) for row in rows]


def save_report(root: Path, user_id: str, values: dict[str, Any]) -> dict[str, Any]:
    report_id, now = str(values.get("id") or uuid.uuid4().hex), int(time.time())
    with _connect(root) as db:
        db.execute("""INSERT INTO creatorthon_reports
        (id,user_id,project_id,title,report_type,source_url,content_json,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
        title=excluded.title,report_type=excluded.report_type,source_url=excluded.source_url,
        content_json=excluded.content_json,updated_at=excluded.updated_at
        WHERE creatorthon_reports.user_id=excluded.user_id""", (
            report_id, user_id, str(values.get("project_id") or ""), str(values.get("title") or "Untitled report")[:500],
            str(values.get("report_type") or "topic-research")[:80], str(values.get("source_url") or "")[:2000],
            json.dumps(values.get("content") or {}, ensure_ascii=False), now, now,
        ))
        row = db.execute("SELECT * FROM creatorthon_reports WHERE id=? AND user_id=?", (report_id, user_id)).fetchone()
    result = dict(row)
    result["content"] = _json_load(result.pop("content_json"), {})
    return result


def list_reports(root: Path, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute("SELECT * FROM creatorthon_reports WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                          (user_id, max(1, min(int(limit), 100)))).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["content"] = _json_load(item.pop("content_json"), {})
        result.append(item)
    return result


def add_asset(root: Path, user_id: str, values: dict[str, Any]) -> dict[str, Any]:
    asset_id, now = uuid.uuid4().hex, int(time.time())
    with _connect(root) as db:
        db.execute("INSERT INTO creatorthon_assets VALUES (?,?,?,?,?,?,?)", (
            asset_id, user_id, str(values.get("project_id") or ""), str(values.get("kind") or "file")[:40],
            str(values.get("url") or "")[:2000], json.dumps(values.get("metadata") or {}, ensure_ascii=False), now,
        ))
    return {"id": asset_id, "project_id": str(values.get("project_id") or ""), "kind": values.get("kind") or "file",
            "url": values.get("url") or "", "metadata": values.get("metadata") or {}, "created_at": now}


def list_assets(root: Path, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute("SELECT * FROM creatorthon_assets WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                          (user_id, max(1, min(int(limit), 200)))).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _json_load(item.pop("metadata_json"), {})
        result.append(item)
    return result


def workspace(root: Path, user: dict[str, Any]) -> dict[str, Any]:
    user_id = str(user.get("sub", ""))
    projects, reports, assets = list_projects(root, user_id), list_reports(root, user_id), list_assets(root, user_id)
    return {"profile": get_profile(root, user), "projects": projects, "reports": reports, "assets": assets,
            "summary": {"projects": len(projects), "completed_videos": sum(bool(p.get("video_url")) for p in projects),
                        "drafts": sum(p.get("status") in {"draft", "prepared"} for p in projects), "reports": len(reports)}}
