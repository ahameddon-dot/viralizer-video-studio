from __future__ import annotations

from typing import Any


SENSITIVE_PARTS = ("token", "secret", "password", "authorization", "cookie", "credential", "api_key", "apikey")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            result[str(key)] = "[REDACTED]" if any(part in normalized for part in SENSITIVE_PARTS) else redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return value[:20_000]
    return value
