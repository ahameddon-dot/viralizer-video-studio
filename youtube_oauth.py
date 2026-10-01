from __future__ import annotations

import base64
import hashlib
import os
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken


class YouTubeOAuthError(RuntimeError):
    pass


AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "openid email https://www.googleapis.com/auth/youtube.upload"


def configured() -> bool:
    return bool(os.getenv("YOUTUBE_CLIENT_ID", "").strip() and os.getenv("YOUTUBE_CLIENT_SECRET", "").strip())


def redirect_uri(scheme: str, host: str) -> str:
    return os.getenv("YOUTUBE_REDIRECT_URI", "").strip() or f"{scheme}://{host}/auth/youtube/callback"


def authorization_url(callback: str, state: str, login_hint: str = "") -> str:
    values = {
        "client_id": os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
        "redirect_uri": callback,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "access_type": "offline",
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
    }
    if login_hint:
        values["login_hint"] = login_hint
    return AUTHORIZE_URL + "?" + urlencode(values)


def _fernet() -> Fernet:
    secret = (
        os.getenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", "").strip()
        or os.getenv("GOOGLE_SESSION_SECRET", "").strip()
        or os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    )
    if not secret:
        raise YouTubeOAuthError("YouTube token encryption is not configured.")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_refresh_token(token: str) -> str:
    if not token:
        raise YouTubeOAuthError("Google did not return a YouTube refresh token.")
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_refresh_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise YouTubeOAuthError("The saved YouTube connection could not be decrypted. Reconnect the channel.") from exc


async def exchange_connection(code: str, callback: str, expected_email: str) -> dict[str, str]:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token_response = await client.post(TOKEN_URL, data={
                "client_id": os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
                "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": callback,
            })
            token_response.raise_for_status()
            tokens = token_response.json()
            access_token = str(tokens.get("access_token") or "")
            refresh_token = str(tokens.get("refresh_token") or "")
            if not access_token or not refresh_token:
                raise YouTubeOAuthError("Google did not return offline YouTube access. Reconnect and approve access.")
            headers = {"Authorization": f"Bearer {access_token}"}
            user_response = await client.get(USERINFO_URL, headers=headers)
            user_response.raise_for_status()
            oauth_email = str(user_response.json().get("email") or "").strip().lower()
            if not oauth_email or oauth_email != expected_email.strip().lower():
                raise YouTubeOAuthError("Connect the same Google account used to sign in to Viralizer.")
            return {
                "refresh_token_ciphertext": encrypt_refresh_token(refresh_token),
                "channel_id": "",
                "channel_title": oauth_email,
                "oauth_email": oauth_email,
            }
    except YouTubeOAuthError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise YouTubeOAuthError("Google could not connect this YouTube channel.") from exc
