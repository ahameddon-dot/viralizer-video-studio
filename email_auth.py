"""First-party email/password accounts for the standalone Growth Autopilot."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from creatorthon_store import _connect


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
SESSION_TTL_SECONDS = 7 * 86400


class EmailAuthError(ValueError):
    pass


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise EmailAuthError("Enter a valid email address.")
    return email


def validate_password(value: str) -> None:
    if len(value) < 10:
        raise EmailAuthError("Use at least 10 characters for your password.")
    if len(value) > 256:
        raise EmailAuthError("Password is too long.")


def _password_hash(password: str, salt: bytes) -> str:
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return base64.urlsafe_b64encode(derived).decode("ascii").rstrip("=")


def _encoded_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${encoded_salt}${_password_hash(password, salt)}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, encoded_salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        salt = base64.urlsafe_b64decode(encoded_salt + "=" * (-len(encoded_salt) % 4))
        supplied = _password_hash(password, salt)
        return hmac.compare_digest(supplied, expected)
    except (TypeError, ValueError):
        return False


_DUMMY_SALT = b"viralizer-dummy!"
_DUMMY_SALT_ENCODED = base64.urlsafe_b64encode(_DUMMY_SALT).decode("ascii").rstrip("=")
_DUMMY_PASSWORD = f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_DUMMY_SALT_ENCODED}${_password_hash('invalid-password-placeholder', _DUMMY_SALT)}"


def create_email_account(root: Path, email: str, password: str) -> dict[str, Any]:
    email = normalize_email(email)
    validate_password(password)
    account_id, now = uuid.uuid4().hex, int(time.time())
    try:
        with _connect(root) as db:
            row = db.execute(
                """INSERT INTO customer_accounts(id,email,password_hash,status,created_at,updated_at,last_login_at)
                VALUES(?,?,?,'active',?,?,?) RETURNING id,email,status,created_at,last_login_at""",
                (account_id, email, _encoded_password(password), now, now, now),
            ).fetchone()
    except Exception as exc:
        if "unique" in str(exc).casefold() or "duplicate" in str(exc).casefold():
            raise EmailAuthError("An account already exists for this email. Sign in instead.") from exc
        raise
    return dict(row)


def authenticate_email_account(root: Path, email: str, password: str) -> dict[str, Any] | None:
    email = normalize_email(email)
    now = int(time.time())
    with _connect(root) as db:
        row = db.execute("SELECT * FROM customer_accounts WHERE email=? AND status='active'", (email,)).fetchone()
        candidate = str(dict(row).get("password_hash") or "") if row else _DUMMY_PASSWORD
        if not _verify_password(password, candidate) or not row:
            return None
        db.execute("UPDATE customer_accounts SET last_login_at=?,updated_at=? WHERE id=?", (now, now, dict(row)["id"]))
    account = dict(row)
    account["last_login_at"] = now
    return account


def _session_secret() -> bytes:
    value = (
        os.getenv("EMAIL_SESSION_SECRET", "").strip()
        or os.getenv("GOOGLE_SESSION_SECRET", "").strip()
        or os.getenv("APP_PASSWORD", "").strip()
    )
    if not value:
        raise EmailAuthError("Email account sessions are not configured on this server.")
    return value.encode("utf-8")


def email_session_token(account: dict[str, Any]) -> str:
    now = int(time.time())
    payload = {
        "sub": f"email:{account['id']}",
        "account_id": str(account["id"]),
        "email": str(account["email"]),
        "name": str(account["email"]).split("@", 1)[0],
        "provider": "email",
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"email.{encoded}.{signature}"


def read_email_session(token: str) -> dict[str, Any] | None:
    try:
        prefix, encoded, signature = token.split(".", 2)
        if prefix != "email":
            return None
        expected = hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if int(payload.get("exp") or 0) < int(time.time()) or not str(payload.get("sub") or "").startswith("email:"):
            return None
        return payload
    except (EmailAuthError, TypeError, ValueError, json.JSONDecodeError):
        return None
