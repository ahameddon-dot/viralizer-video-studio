import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_POSTGRES_READY = False
_POSTGRES_POOL = None
_POSTGRES_POOL_DSN = ""
_POSTGRES_POOL_LOCK = threading.Lock()


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
        """CREATE TABLE IF NOT EXISTS creatorthon_event_accounts (
          event_key TEXT NOT NULL, user_id TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', admitted_at BIGINT NOT NULL, seat_number INTEGER NOT NULL DEFAULT 0,
          generation_status TEXT NOT NULL DEFAULT '', generation_project_id TEXT NOT NULL DEFAULT '',
          generation_provider TEXT NOT NULL DEFAULT '', generation_job_id TEXT NOT NULL DEFAULT '',
          generation_updated_at BIGINT NOT NULL DEFAULT 0, generation_count INTEGER NOT NULL DEFAULT 0,
          extra_generation_credits INTEGER NOT NULL DEFAULT 0, admission_override INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (event_key, user_id))""",
        """CREATE TABLE IF NOT EXISTS creatorthon_youtube_connections (
          user_id TEXT PRIMARY KEY, refresh_token_ciphertext TEXT NOT NULL,
          channel_id TEXT NOT NULL, channel_title TEXT NOT NULL, oauth_email TEXT NOT NULL,
          created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS creatorthon_insight_jobs (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, topic_key TEXT NOT NULL,
          topic_json TEXT NOT NULL, position INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
          result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
          created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL,
          UNIQUE(user_id,topic_key))""",
        "CREATE INDEX IF NOT EXISTS idx_creatorthon_insight_queue ON creatorthon_insight_jobs(user_id,position)",
        """CREATE TABLE IF NOT EXISTS creatorthon_topic_insight_cache (
          topic_key TEXT PRIMARY KEY, topic_title TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
          fetched_at BIGINT NOT NULL, expires_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS creatorthon_category_topic_cache (
          category_key TEXT PRIMARY KEY, category_name TEXT NOT NULL, topics_json TEXT NOT NULL DEFAULT '[]',
          fetched_at BIGINT NOT NULL, expires_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS creatorthon_event_admission_overrides (
          event_key TEXT NOT NULL, email TEXT NOT NULL, granted_by TEXT NOT NULL,
          created_at BIGINT NOT NULL, used_at BIGINT NOT NULL DEFAULT 0,
          PRIMARY KEY(event_key,email))""",
        """CREATE TABLE IF NOT EXISTS creatorthon_event_denials (
          event_key TEXT NOT NULL, email TEXT NOT NULL, removed_by TEXT NOT NULL,
          created_at BIGINT NOT NULL, PRIMARY KEY(event_key,email))""",
        """CREATE TABLE IF NOT EXISTS creatorthon_admin_audit (
          id TEXT PRIMARY KEY, event_key TEXT NOT NULL, admin_email TEXT NOT NULL,
          action TEXT NOT NULL, target_email TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
          created_at BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS creatorthon_workflow_states (
          user_id TEXT PRIMARY KEY, step TEXT NOT NULL DEFAULT 'profile',
          topics_json TEXT NOT NULL DEFAULT '[]', selected_topic_json TEXT NOT NULL DEFAULT '{}',
          updated_at BIGINT NOT NULL)""",
    ]


def _project_columns() -> tuple[tuple[str, str], ...]:
    return (
        ("title", "TEXT NOT NULL DEFAULT ''"), ("prompt_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("narration_json", "TEXT NOT NULL DEFAULT '{}'"), ("configuration_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("article_intelligence_json", "TEXT NOT NULL DEFAULT '{}'"), ("production_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("qc_json", "TEXT NOT NULL DEFAULT '{}'"), ("thumbnail_url", "TEXT NOT NULL DEFAULT ''"),
        ("aspect_ratio", "TEXT NOT NULL DEFAULT ''"), ("quality", "TEXT NOT NULL DEFAULT ''"),
    )


def _ensure_event_account_schema(db: Any) -> None:
    _ensure_column(db, "creatorthon_event_accounts", "seat_number", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "creatorthon_event_accounts", "email", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(db, "creatorthon_event_accounts", "generation_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "creatorthon_event_accounts", "extra_generation_credits", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "creatorthon_event_accounts", "admission_override", "INTEGER NOT NULL DEFAULT 0")
    db.execute(
        "UPDATE creatorthon_event_accounts SET generation_count=1 "
        "WHERE generation_status='accepted' AND generation_count=0"
    )
    rows = db.execute(
        "SELECT event_key,user_id,seat_number FROM creatorthon_event_accounts ORDER BY event_key,admitted_at,user_id"
    ).fetchall()
    used: dict[str, set[int]] = {}
    for row in rows:
        item = dict(row)
        key = str(item["event_key"])
        number = int(item.get("seat_number") or 0)
        occupied = used.setdefault(key, set())
        if number > 0:
            occupied.add(number)
            continue
        number = next(candidate for candidate in range(1, len(rows) + 2) if candidate not in occupied)
        db.execute(
            "UPDATE creatorthon_event_accounts SET seat_number=? WHERE event_key=? AND user_id=?",
            (number, key, str(item["user_id"])),
        )
        occupied.add(number)
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_creatorthon_event_seat "
        "ON creatorthon_event_accounts(event_key,seat_number) WHERE seat_number > 0"
    )


@contextmanager
def _connect(root: Path) -> Iterator[Any]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL is configured but PostgreSQL pooling support is not installed.") from exc
        global _POSTGRES_POOL, _POSTGRES_POOL_DSN, _POSTGRES_READY
        if _POSTGRES_POOL is None or _POSTGRES_POOL_DSN != database_url:
            with _POSTGRES_POOL_LOCK:
                if _POSTGRES_POOL is None or _POSTGRES_POOL_DSN != database_url:
                    if _POSTGRES_POOL is not None:
                        _POSTGRES_POOL.close()
                    _POSTGRES_POOL = ConnectionPool(
                        conninfo=database_url,
                        min_size=1,
                        max_size=4,
                        timeout=10,
                        kwargs={"row_factory": dict_row, "prepare_threshold": None},
                        open=True,
                    )
                    _POSTGRES_POOL_DSN = database_url
                    _POSTGRES_READY = False
        with _POSTGRES_POOL.connection(timeout=10) as connection:
            db = _PostgresAdapter(connection)
            try:
                if not _POSTGRES_READY:
                    for statement in _schema_statements():
                        db.execute(statement)
                    for name, declaration in _project_columns():
                        _ensure_column(db, "creatorthon_projects", name, declaration)
                    _ensure_event_account_schema(db)
                    connection.commit()
                    _POSTGRES_READY = True
                yield db
                connection.commit()
            except Exception:
                connection.rollback()
                raise
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
    CREATE TABLE IF NOT EXISTS creatorthon_event_accounts (
      event_key TEXT NOT NULL, user_id TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', admitted_at INTEGER NOT NULL,
      seat_number INTEGER NOT NULL DEFAULT 0,
      generation_status TEXT NOT NULL DEFAULT '', generation_project_id TEXT NOT NULL DEFAULT '',
      generation_provider TEXT NOT NULL DEFAULT '', generation_job_id TEXT NOT NULL DEFAULT '',
      generation_updated_at INTEGER NOT NULL DEFAULT 0, generation_count INTEGER NOT NULL DEFAULT 0,
      extra_generation_credits INTEGER NOT NULL DEFAULT 0, admission_override INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (event_key, user_id)
    );
    CREATE TABLE IF NOT EXISTS creatorthon_youtube_connections (
      user_id TEXT PRIMARY KEY, refresh_token_ciphertext TEXT NOT NULL,
      channel_id TEXT NOT NULL, channel_title TEXT NOT NULL, oauth_email TEXT NOT NULL,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS creatorthon_insight_jobs (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, topic_key TEXT NOT NULL,
      topic_json TEXT NOT NULL, position INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
      result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      UNIQUE(user_id,topic_key)
    );
    CREATE INDEX IF NOT EXISTS idx_creatorthon_insight_queue
    ON creatorthon_insight_jobs(user_id,position);
    CREATE TABLE IF NOT EXISTS creatorthon_topic_insight_cache (
      topic_key TEXT PRIMARY KEY, topic_title TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
      fetched_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS creatorthon_category_topic_cache (
      category_key TEXT PRIMARY KEY, category_name TEXT NOT NULL, topics_json TEXT NOT NULL DEFAULT '[]',
      fetched_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS creatorthon_workflow_states (
      user_id TEXT PRIMARY KEY, step TEXT NOT NULL DEFAULT 'profile',
      topics_json TEXT NOT NULL DEFAULT '[]', selected_topic_json TEXT NOT NULL DEFAULT '{}',
      updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS creatorthon_event_admission_overrides (
      event_key TEXT NOT NULL, email TEXT NOT NULL, granted_by TEXT NOT NULL,
      created_at INTEGER NOT NULL, used_at INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(event_key,email)
    );
    CREATE TABLE IF NOT EXISTS creatorthon_event_denials (
      event_key TEXT NOT NULL, email TEXT NOT NULL, removed_by TEXT NOT NULL,
      created_at INTEGER NOT NULL, PRIMARY KEY(event_key,email)
    );
    CREATE TABLE IF NOT EXISTS creatorthon_admin_audit (
      id TEXT PRIMARY KEY, event_key TEXT NOT NULL, admin_email TEXT NOT NULL,
      action TEXT NOT NULL, target_email TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
      created_at INTEGER NOT NULL
    );
    """)
    for name, declaration in _project_columns():
        _ensure_column(db, "creatorthon_projects", name, declaration)
    _ensure_event_account_schema(db)
    db.commit()
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


def event_key() -> str:
    return os.getenv("CREATORTHON_EVENT_KEY", "creatorthon-event-2026").strip() or "creatorthon-event-2026"


def claim_event_seat(root: Path, user_id: str, limit: int = 50, email: str = "") -> dict[str, Any]:
    """Atomically admit one account to the configured event, up to the shared cap."""
    key, now, normalized_email = event_key(), int(time.time()), email.strip().lower()
    with _connect(root) as db:
        if getattr(db, "dialect", "sqlite") == "postgres":
            db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"creatorthon-seat:{key}",))
        else:
            db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM creatorthon_event_accounts WHERE event_key=? AND user_id=?", (key, user_id)).fetchone()
        if row:
            if normalized_email and not str(dict(row).get("email") or "").strip():
                db.execute(
                    "UPDATE creatorthon_event_accounts SET email=? WHERE event_key=? AND user_id=?",
                    (normalized_email, key, user_id),
                )
                return {**dict(row), "email": normalized_email}
            return dict(row)
        if normalized_email:
            denied = db.execute(
                "SELECT 1 FROM creatorthon_event_denials WHERE event_key=? AND lower(email)=?",
                (key, normalized_email),
            ).fetchone()
            if denied:
                raise RuntimeError("Your Creatorthon event access was removed by an organizer.")
        override = None
        if normalized_email:
            override = db.execute(
                "SELECT * FROM creatorthon_event_admission_overrides WHERE event_key=? AND lower(email)=?",
                (key, normalized_email),
            ).fetchone()
        count_row = db.execute("SELECT COUNT(*) AS total FROM creatorthon_event_accounts WHERE event_key=?", (key,)).fetchone()
        total = int(dict(count_row).get("total", 0) if hasattr(count_row, "keys") else count_row[0])
        if total >= max(1, int(limit)) and not override:
            raise RuntimeError("The 50-user Creatorthon event capacity has been reached.")
        occupied_rows = db.execute(
            "SELECT seat_number FROM creatorthon_event_accounts WHERE event_key=? AND seat_number>0",
            (key,),
        ).fetchall()
        occupied = {int(dict(item).get("seat_number") or 0) for item in occupied_rows}
        seat_number = next(number for number in range(1, max(max(occupied, default=0) + 2, int(limit) + 2)) if number not in occupied)
        db.execute(
            "INSERT INTO creatorthon_event_accounts (event_key,user_id,email,admitted_at,seat_number,admission_override) VALUES (?,?,?,?,?,?)",
            (key, user_id, normalized_email, now, seat_number, int(bool(override))),
        )
        if override:
            db.execute(
                "UPDATE creatorthon_event_admission_overrides SET used_at=? WHERE event_key=? AND lower(email)=?",
                (now, key, normalized_email),
            )
        return {"event_key": key, "user_id": user_id, "email": normalized_email, "admitted_at": now,
                "seat_number": seat_number, "generation_status": "", "generation_count": 0,
                "extra_generation_credits": 0, "admission_override": int(bool(override))}


def generation_entitlement(root: Path, user_id: str, email: str = "") -> dict[str, Any]:
    claim_event_seat(root, user_id, int(os.getenv("CREATORTHON_EVENT_USER_LIMIT", "50")), email)
    with _connect(root) as db:
        row = db.execute("SELECT * FROM creatorthon_event_accounts WHERE event_key=? AND user_id=?", (event_key(), user_id)).fetchone()
    return dict(row) if row else {}


def reserve_event_generation(root: Path, user_id: str, project_id: str, provider: str, email: str = "") -> dict[str, Any]:
    """Reserve the one generation slot. Failed provider starts can release it safely."""
    key, now = event_key(), int(time.time())
    claim_event_seat(root, user_id, int(os.getenv("CREATORTHON_EVENT_USER_LIMIT", "50")), email)
    with _connect(root) as db:
        if getattr(db, "dialect", "sqlite") == "postgres":
            db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"creatorthon-generation:{key}:{user_id}",))
        else:
            db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM creatorthon_event_accounts WHERE event_key=? AND user_id=?", (key, user_id)).fetchone()
        item = dict(row)
        status = str(item.get("generation_status") or "")
        used = int(item.get("generation_count") or 0)
        allowance = 1 + int(item.get("extra_generation_credits") or 0)
        if status == "reserved" or used >= allowance:
            return {**item, "allowed": False}
        db.execute("UPDATE creatorthon_event_accounts SET generation_status='reserved',generation_project_id=?,generation_provider=?,generation_updated_at=? WHERE event_key=? AND user_id=?", (project_id, provider, now, key, user_id))
    return {"allowed": True, "generation_status": "reserved", "generation_project_id": project_id}


def release_event_generation(root: Path, user_id: str, project_id: str) -> None:
    with _connect(root) as db:
        db.execute("UPDATE creatorthon_event_accounts SET generation_status='',generation_project_id='',generation_provider='',generation_job_id='',generation_updated_at=? WHERE event_key=? AND user_id=? AND generation_status='reserved' AND generation_project_id=?", (int(time.time()), event_key(), user_id, project_id))


def accept_event_generation(root: Path, user_id: str, project_id: str, provider: str, job_id: str) -> None:
    with _connect(root) as db:
        db.execute("UPDATE creatorthon_event_accounts SET generation_status='accepted',generation_provider=?,generation_job_id=?,generation_updated_at=?,generation_count=generation_count+1 WHERE event_key=? AND user_id=? AND generation_project_id=? AND generation_status='reserved'", (provider, job_id, int(time.time()), event_key(), user_id, project_id))


def _record_admin_audit(db: Any, admin_email: str, action: str, target_email: str,
                        details: dict[str, Any] | None = None) -> None:
    db.execute(
        "INSERT INTO creatorthon_admin_audit (id,event_key,admin_email,action,target_email,details_json,created_at) VALUES (?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, event_key(), admin_email.strip().lower(), action, target_email.strip().lower(),
         json.dumps(details or {}, ensure_ascii=False), int(time.time())),
    )


def grant_event_admission(root: Path, target_email: str, admin_email: str) -> dict[str, Any]:
    email, key, now = target_email.strip().lower(), event_key(), int(time.time())
    with _connect(root) as db:
        db.execute(
            "DELETE FROM creatorthon_event_denials WHERE event_key=? AND lower(email)=?",
            (key, email),
        )
        db.execute(
            """INSERT INTO creatorthon_event_admission_overrides (event_key,email,granted_by,created_at,used_at)
            VALUES (?,?,?,?,0) ON CONFLICT(event_key,email) DO UPDATE SET granted_by=excluded.granted_by,
            created_at=excluded.created_at""",
            (key, email, admin_email.strip().lower(), now),
        )
        _record_admin_audit(db, admin_email, "admit_user", email)
    return {"email": email, "admitted": True}


def remove_event_user(root: Path, target_email: str, admin_email: str) -> dict[str, Any]:
    """Remove an event participant while preserving their profile, projects, assets, and videos."""
    email, key, now = target_email.strip().lower(), event_key(), int(time.time())
    with _connect(root) as db:
        row = db.execute(
            """SELECT a.user_id,a.generation_status FROM creatorthon_event_accounts a
            LEFT JOIN creatorthon_profiles p ON p.user_id=a.user_id
            WHERE a.event_key=? AND lower(COALESCE(NULLIF(a.email,''),p.email,''))=?""",
            (key, email),
        ).fetchone()
        if not row:
            raise LookupError("This email is not an admitted Creatorthon user.")
        account = dict(row)
        if str(account.get("generation_status") or "") == "reserved":
            raise RuntimeError("This user cannot be removed while a video generation is starting. Try again shortly.")
        db.execute(
            """INSERT INTO creatorthon_event_denials (event_key,email,removed_by,created_at)
            VALUES (?,?,?,?) ON CONFLICT(event_key,email) DO UPDATE SET
            removed_by=excluded.removed_by,created_at=excluded.created_at""",
            (key, email, admin_email.strip().lower(), now),
        )
        db.execute("DELETE FROM creatorthon_event_accounts WHERE event_key=? AND user_id=?", (key, account["user_id"]))
        db.execute("DELETE FROM creatorthon_event_admission_overrides WHERE event_key=? AND lower(email)=?", (key, email))
        _record_admin_audit(db, admin_email, "remove_user", email, {"projects_preserved": True})
    return {"email": email, "removed": True, "projects_preserved": True}


def grant_extra_generation(root: Path, target_email: str, admin_email: str) -> dict[str, Any]:
    email, key = target_email.strip().lower(), event_key()
    with _connect(root) as db:
        row = db.execute(
            """SELECT a.user_id FROM creatorthon_event_accounts a
            LEFT JOIN creatorthon_profiles p ON p.user_id=a.user_id
            WHERE a.event_key=? AND lower(COALESCE(NULLIF(a.email,''),p.email,''))=?""",
            (key, email),
        ).fetchone()
        if not row:
            raise LookupError("This email has not entered the Creatorthon event yet.")
        user_id = str(dict(row).get("user_id") or "")
        db.execute(
            "UPDATE creatorthon_event_accounts SET extra_generation_credits=extra_generation_credits+1 "
            "WHERE event_key=? AND user_id=?",
            (key, user_id),
        )
        _record_admin_audit(db, admin_email, "grant_video_credit", email, {"credits": 1})
        updated = db.execute(
            "SELECT * FROM creatorthon_event_accounts WHERE event_key=? AND user_id=?", (key, user_id)
        ).fetchone()
    return dict(updated)


def event_admin_state(root: Path, limit: int = 50) -> dict[str, Any]:
    key = event_key()
    with _connect(root) as db:
        rows = db.execute(
            """SELECT a.*,COALESCE(NULLIF(a.email,''),p.email,'') AS resolved_email,
            COALESCE(p.full_name,'') AS full_name
            FROM creatorthon_event_accounts a LEFT JOIN creatorthon_profiles p ON p.user_id=a.user_id
            WHERE a.event_key=? ORDER BY a.seat_number""",
            (key,),
        ).fetchall()
        pending = db.execute(
            "SELECT email,granted_by,created_at FROM creatorthon_event_admission_overrides "
            "WHERE event_key=? AND used_at=0 ORDER BY created_at DESC", (key,)
        ).fetchall()
        audit = db.execute(
            "SELECT admin_email,action,target_email,details_json,created_at FROM creatorthon_admin_audit "
            "WHERE event_key=? ORDER BY created_at DESC LIMIT 100", (key,)
        ).fetchall()
    users = []
    for row in rows:
        item = dict(row)
        used = int(item.get("generation_count") or 0)
        allowance = 1 + int(item.get("extra_generation_credits") or 0)
        users.append({
            "user_id": str(item.get("user_id") or ""), "email": str(item.get("resolved_email") or ""),
            "full_name": str(item.get("full_name") or ""), "seat_number": int(item.get("seat_number") or 0),
            "admitted_at": int(item.get("admitted_at") or 0), "admission_override": bool(item.get("admission_override")),
            "generation_status": str(item.get("generation_status") or "available"),
            "videos_used": used, "total_allowance": allowance, "credits_remaining": max(0, allowance - used),
        })
    return {"event_key": key, "capacity": int(limit), "admitted_count": len(users), "users": users,
            "pending_admissions": [dict(row) for row in pending],
            "audit": [{**dict(row), "details": _json_load(dict(row).get("details_json"), {})} for row in audit]}


def save_youtube_connection(root: Path, user_id: str, connection: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    with _connect(root) as db:
        existing = db.execute("SELECT created_at FROM creatorthon_youtube_connections WHERE user_id=?", (user_id,)).fetchone()
        created_at = int(dict(existing).get("created_at") or now) if existing else now
        if existing:
            db.execute(
                "UPDATE creatorthon_youtube_connections SET refresh_token_ciphertext=?,channel_id=?,channel_title=?,oauth_email=?,updated_at=? WHERE user_id=?",
                (connection["refresh_token_ciphertext"], connection["channel_id"], connection["channel_title"],
                 connection["oauth_email"], now, user_id),
            )
        else:
            db.execute(
                "INSERT INTO creatorthon_youtube_connections (user_id,refresh_token_ciphertext,channel_id,channel_title,oauth_email,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (user_id, connection["refresh_token_ciphertext"], connection["channel_id"], connection["channel_title"],
                 connection["oauth_email"], created_at, now),
            )
    return {**connection, "user_id": user_id, "created_at": created_at, "updated_at": now}


def get_youtube_connection(root: Path, user_id: str) -> dict[str, Any] | None:
    with _connect(root) as db:
        row = db.execute("SELECT * FROM creatorthon_youtube_connections WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def delete_youtube_connection(root: Path, user_id: str) -> bool:
    with _connect(root) as db:
        cursor = db.execute("DELETE FROM creatorthon_youtube_connections WHERE user_id=?", (user_id,))
        return bool(cursor.rowcount)


def _insight_job(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["topic"] = _json_load(item.pop("topic_json", "{}"), {})
    item["result"] = _json_load(item.pop("result_json", "{}"), {})
    return item


def _topic_key(title: str) -> str:
    normalized = " ".join(str(title).split()).casefold()
    return __import__("hashlib").sha256(normalized.encode("utf-8")).hexdigest()


def get_cached_topic_insight(root: Path, title: str, *, allow_stale: bool = False) -> dict[str, Any] | None:
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute(
            "SELECT result_json,fetched_at,expires_at FROM creatorthon_topic_insight_cache WHERE topic_key=?",
            (_topic_key(title),),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    if not allow_stale and int(item.get("expires_at") or 0) <= now:
        return None
    result = _json_load(item.get("result_json"), {})
    if not isinstance(result, dict) or not result:
        return None
    result.setdefault("fetched_at", int(item.get("fetched_at") or 0))
    result["cached"] = True
    return result


def save_cached_topic_insight(root: Path, title: str, result: dict[str, Any], ttl_seconds: int = 86400) -> None:
    clean_title = " ".join(str(title).split())
    now = int(time.time())
    with _connect(root) as db:
        db.execute(
            """INSERT INTO creatorthon_topic_insight_cache
            (topic_key,topic_title,result_json,fetched_at,expires_at,updated_at) VALUES (?,?,?,?,?,?)
            ON CONFLICT(topic_key) DO UPDATE SET topic_title=excluded.topic_title,
            result_json=excluded.result_json,fetched_at=excluded.fetched_at,
            expires_at=excluded.expires_at,updated_at=excluded.updated_at""",
            (_topic_key(clean_title), clean_title, json.dumps(result, ensure_ascii=False), now,
             now + max(300, int(ttl_seconds)), now),
        )


def get_cached_category_topics(root: Path, category: str, *, allow_stale: bool = False) -> list[dict[str, Any]]:
    key = " ".join(str(category).split()).casefold()
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute(
            "SELECT topics_json,expires_at FROM creatorthon_category_topic_cache WHERE category_key=?", (key,)
        ).fetchone()
    if not row:
        return []
    item = dict(row)
    if not allow_stale and int(item.get("expires_at") or 0) <= now:
        return []
    topics = _json_load(item.get("topics_json"), [])
    return topics if isinstance(topics, list) else []


def save_cached_category_topics(root: Path, category: str, topics: list[dict[str, Any]], ttl_seconds: int = 86400) -> None:
    clean_category = " ".join(str(category).split())
    now = int(time.time())
    with _connect(root) as db:
        db.execute(
            """INSERT INTO creatorthon_category_topic_cache
            (category_key,category_name,topics_json,fetched_at,expires_at,updated_at) VALUES (?,?,?,?,?,?)
            ON CONFLICT(category_key) DO UPDATE SET category_name=excluded.category_name,
            topics_json=excluded.topics_json,fetched_at=excluded.fetched_at,
            expires_at=excluded.expires_at,updated_at=excluded.updated_at""",
            (clean_category.casefold(), clean_category, json.dumps(topics, ensure_ascii=False), now,
             now + max(300, int(ttl_seconds)), now),
        )


def list_insight_jobs(root: Path, user_id: str) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM creatorthon_insight_jobs WHERE user_id=? ORDER BY position,id", (user_id,)
        ).fetchall()
    return [_insight_job(row) for row in rows]


def enqueue_insight_job(root: Path, user_id: str, topic: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    title = " ".join(str(topic.get("topic") or topic.get("title") or topic.get("name") or "").split())
    if not title:
        raise ValueError("A topic title is required.")
    topic_key = _topic_key(title)
    now, job_id = int(time.time()), uuid.uuid4().hex
    with _connect(root) as db:
        if getattr(db, "dialect", "sqlite") == "postgres":
            db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"creatorthon-insights:{user_id}",))
        else:
            db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM creatorthon_insight_jobs WHERE user_id=? AND topic_key=?", (user_id, topic_key)
        ).fetchone()
        if existing:
            return _insight_job(existing), False
        row = db.execute(
            "SELECT COALESCE(MAX(position),0) AS maximum FROM creatorthon_insight_jobs WHERE user_id=?", (user_id,)
        ).fetchone()
        position = int(dict(row).get("maximum") or 0) + 1
        db.execute(
            "INSERT INTO creatorthon_insight_jobs (id,user_id,topic_key,topic_json,position,status,created_at,updated_at) VALUES (?,?,?,?,?,'queued',?,?)",
            (job_id, user_id, topic_key, json.dumps(topic, ensure_ascii=False), position, now, now),
        )
        created = db.execute("SELECT * FROM creatorthon_insight_jobs WHERE id=?", (job_id,)).fetchone()
    return _insight_job(created), True


def claim_next_insight_job(root: Path, user_id: str) -> dict[str, Any] | None:
    now = int(time.time())
    with _connect(root) as db:
        if getattr(db, "dialect", "sqlite") == "postgres":
            db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"creatorthon-insights:{user_id}",))
        else:
            db.execute("BEGIN IMMEDIATE")
        # A crashed web process may leave a job in processing. It is safe to retry after five minutes.
        db.execute(
            "UPDATE creatorthon_insight_jobs SET status='queued',error='',updated_at=? WHERE user_id=? AND status='processing' AND updated_at<?",
            (now, user_id, now - 300),
        )
        active = db.execute(
            "SELECT id FROM creatorthon_insight_jobs WHERE user_id=? AND status='processing' LIMIT 1", (user_id,)
        ).fetchone()
        if active:
            return None
        row = db.execute(
            "SELECT * FROM creatorthon_insight_jobs WHERE user_id=? AND status='queued' ORDER BY position,id LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        job_id = str(dict(row)["id"])
        db.execute(
            "UPDATE creatorthon_insight_jobs SET status='processing',attempts=attempts+1,error='',updated_at=? WHERE id=? AND user_id=?",
            (now, job_id, user_id),
        )
        claimed = db.execute("SELECT * FROM creatorthon_insight_jobs WHERE id=?", (job_id,)).fetchone()
    return _insight_job(claimed)


def finish_insight_job(root: Path, user_id: str, job_id: str, result: dict[str, Any] | None = None, error: str = "") -> None:
    with _connect(root) as db:
        db.execute(
            "UPDATE creatorthon_insight_jobs SET status=?,result_json=?,error=?,updated_at=? WHERE id=? AND user_id=?",
            ("failed" if error else "completed", json.dumps(result or {}, ensure_ascii=False), str(error)[:1000],
             int(time.time()), job_id, user_id),
        )


def delete_insight_job(root: Path, user_id: str, job_id: str) -> bool:
    """Remove one user's selected insight without deleting the shared prefetched report."""
    with _connect(root) as db:
        cursor = db.execute(
            "DELETE FROM creatorthon_insight_jobs WHERE id=? AND user_id=?",
            (job_id, user_id),
        )
        return bool(cursor.rowcount)


def retry_insight_job(root: Path, user_id: str, job_id: str) -> bool:
    with _connect(root) as db:
        cursor = db.execute(
            "UPDATE creatorthon_insight_jobs SET status='queued',error='',updated_at=? WHERE id=? AND user_id=? AND status IN ('failed','completed')",
            (int(time.time()), job_id, user_id),
        )
        return bool(cursor.rowcount)


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


def get_workflow_state(root: Path, user_id: str) -> dict[str, Any]:
    with _connect(root) as db:
        row = db.execute(
            "SELECT step,topics_json,selected_topic_json,updated_at "
            "FROM creatorthon_workflow_states WHERE user_id=?",
            (user_id,),
        ).fetchone()
    if not row:
        return {"step": "", "topics": [], "selected_topic": {}, "updated_at": 0}
    result = dict(row)
    return {
        "step": str(result.get("step") or ""),
        "topics": _json_load(result.get("topics_json"), []),
        "selected_topic": _json_load(result.get("selected_topic_json"), {}),
        "updated_at": int(result.get("updated_at") or 0),
    }


def save_workflow_state(root: Path, user_id: str, state: dict[str, Any]) -> dict[str, Any]:
    allowed_steps = {"profile", "interests", "topics", "create"}
    step = str(state.get("step") or "").strip().lower()
    if step not in allowed_steps:
        step = "interests"
    topics = [item for item in state.get("topics", []) if isinstance(item, dict)][:30]
    selected = state.get("selected_topic") if isinstance(state.get("selected_topic"), dict) else {}
    now = int(time.time())
    with _connect(root) as db:
        db.execute(
            """INSERT INTO creatorthon_workflow_states
            (user_id,step,topics_json,selected_topic_json,updated_at) VALUES (?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET step=excluded.step,topics_json=excluded.topics_json,
            selected_topic_json=excluded.selected_topic_json,updated_at=excluded.updated_at""",
            (user_id, step, json.dumps(topics, ensure_ascii=False), json.dumps(selected, ensure_ascii=False), now),
        )
    return get_workflow_state(root, user_id)


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


def delete_project_video(root: Path, user_id: str, project_id: str) -> dict[str, Any] | None:
    """Clear one owner's video and video assets while preserving the editable project."""
    with _connect(root) as db:
        row = db.execute("SELECT * FROM creatorthon_projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
        if not row:
            return None
        project = _project(row)
        assets = db.execute("SELECT * FROM creatorthon_assets WHERE project_id=? AND user_id=? AND kind=?", (project_id, user_id, "video")).fetchall()
        db.execute("DELETE FROM creatorthon_assets WHERE project_id=? AND user_id=? AND kind=?", (project_id, user_id, "video"))
        production = dict(project.get("production") or {})
        for key in ("raw_video_url", "raw_object_key", "media_job_id", "finish_job_id", "finish_status", "output_url", "completed_at", "error"):
            production.pop(key, None)
        status = "prepared" if project.get("prompt") else "draft"
        db.execute("UPDATE creatorthon_projects SET video_url='',status=?,production_json=?,updated_at=? WHERE id=? AND user_id=?",
                   (status, json.dumps(production, ensure_ascii=False), int(time.time()), project_id, user_id))
    project["assets"] = [dict(asset) for asset in assets]
    return project


def delete_project(root: Path, user_id: str, project_id: str) -> dict[str, Any] | None:
    """Delete one owner's project and its linked reports/assets."""
    with _connect(root) as db:
        row = db.execute("SELECT * FROM creatorthon_projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
        if not row:
            return None
        project = _project(row)
        assets = db.execute("SELECT * FROM creatorthon_assets WHERE project_id=? AND user_id=?", (project_id, user_id)).fetchall()
        db.execute("DELETE FROM creatorthon_assets WHERE project_id=? AND user_id=?", (project_id, user_id))
        db.execute("DELETE FROM creatorthon_reports WHERE project_id=? AND user_id=?", (project_id, user_id))
        db.execute("DELETE FROM creatorthon_projects WHERE id=? AND user_id=?", (project_id, user_id))
    project["assets"] = [dict(asset) for asset in assets]
    return project

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
