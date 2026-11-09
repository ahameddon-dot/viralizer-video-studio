"""Small dependency-free migration runner for the existing SQLite/PostgreSQL adapters."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


MIGRATION_NAME = re.compile(r"^[0-9]{14}_[a-z0-9_]+\.sql$")


def _statements(sql: str) -> list[str]:
    """Split simple project migration files into statements.

    Migration files intentionally exclude procedural blocks and semicolons in
    string literals. This keeps the runner portable without adding a dependency.
    """
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def apply_migrations(db: Any, directory: Path) -> list[str]:
    db.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        checksum TEXT NOT NULL,
        applied_at BIGINT NOT NULL
        )"""
    )
    if getattr(db, "dialect", "sqlite") == "postgres":
        db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("viralizer-schema-migrations",))

    applied = {
        str(dict(row)["version"]): str(dict(row)["checksum"])
        for row in db.execute("SELECT version,checksum FROM schema_migrations").fetchall()
    }
    completed: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        if not MIGRATION_NAME.fullmatch(path.name):
            continue
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        if path.name in applied:
            if applied[path.name] != checksum:
                raise RuntimeError(f"Applied migration checksum changed: {path.name}")
            continue
        for statement in _statements(sql):
            db.execute(statement)
        db.execute(
            "INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(?,?,CAST(strftime('%s','now') AS INTEGER))"
            if getattr(db, "dialect", "sqlite") == "sqlite"
            else "INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(?,?,EXTRACT(EPOCH FROM now())::BIGINT)",
            (path.name, checksum),
        )
        completed.append(path.name)
    return completed

