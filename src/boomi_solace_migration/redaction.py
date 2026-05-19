from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SENSITIVE_MARKERS = ("password", "token", "secret", "apikey", "api_key", "authorization")
REDACTED = "***REDACTED***"


def is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return any(marker in normalized for marker in SENSITIVE_MARKERS)


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if is_sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [redact(item) for item in value]
    return value


def redact_text(text: str) -> str:
    redacted = text
    for marker in SENSITIVE_MARKERS:
        redacted = redacted.replace(marker.upper(), marker.upper())
    return redacted
