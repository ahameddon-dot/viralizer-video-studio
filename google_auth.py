import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleAuthError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID", "").strip() and os.getenv("GOOGLE_CLIENT_SECRET", "").strip())


def _secret() -> bytes:
    value = (
        os.getenv("GOOGLE_SESSION_SECRET", "").strip()
        or os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        or os.getenv("APP_PASSWORD", "").strip()
    )
    if not value:
        raise GoogleAuthError("Google authentication is not configured.")
    return value.encode("utf-8")


def _encode(value: dict) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> dict:
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(value + padding))


def _sign(value: str) -> str:
    return hmac.new(_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_payload(payload: dict) -> str:
    encoded = _encode(payload)
    return f"{encoded}.{_sign(encoded)}"


def read_signed_payload(value: str, max_age: int | None = None) -> dict | None:
    try:
        encoded, supplied = value.rsplit(".", 1)
        if not hmac.compare_digest(supplied, _sign(encoded)):
            return None
        payload = _decode(encoded)
        issued = int(payload.get("iat", 0))
        if max_age is not None and (issued <= 0 or time.time() - issued > max_age):
            return None
        if int(payload.get("exp", int(time.time()) + 1)) < int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def new_state(next_path: str = "/") -> str:
    safe_next = next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"
    return signed_payload({"nonce": secrets.token_urlsafe(24), "next": safe_next, "iat": int(time.time())})


def session_token(user: dict) -> str:
    return "google." + signed_payload({
        "sub": str(user.get("sub", "")),
        "email": str(user.get("email", "")).lower(),
        "name": str(user.get("name", "")),
        "iat": int(time.time()),
        "exp": int(time.time()) + 7 * 86400,
    })


def read_session(value: str) -> dict | None:
    if not value.startswith("google."):
        return None
    return read_signed_payload(value[7:])


def redirect_uri(scheme: str, host: str) -> str:
    configured_uri = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    return configured_uri or f"{scheme}://{host}/auth/google/callback"


def authorization_url(callback: str, state: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "redirect_uri": callback,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })


async def exchange_code(code: str, callback: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            token_response = await client.post(TOKEN_URL, data={
                "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": callback,
            })
            token_response.raise_for_status()
            access_token = token_response.json().get("access_token", "")
            if not access_token:
                raise GoogleAuthError("Google did not return an access token.")
            user_response = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            user_response.raise_for_status()
            user = user_response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleAuthError("Google sign-in could not be completed.") from exc
    if not user.get("email") or user.get("email_verified") is not True:
        raise GoogleAuthError("Google did not return a verified email address.")
    return user


def user_allowed(user: dict) -> bool:
    email = str(user.get("email", "")).strip().lower()
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    emails = {item.strip().lower() for item in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",") if item.strip()}
    domains = {item.strip().lower().lstrip("@") for item in os.getenv("GOOGLE_ALLOWED_DOMAINS", "").split(",") if item.strip()}
    if not emails and not domains:
        return True
    return email in emails or domain in domains