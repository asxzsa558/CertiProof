"""Helpers for removing user-provided secrets before logging or persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "key_file",
    "ssh_key",
    "credential",
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_sensitive(value: Any) -> Any:
    """Return a copy with secret-looking mapping values replaced."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if is_sensitive_key(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_sensitive(item) for item in value]
    return value
