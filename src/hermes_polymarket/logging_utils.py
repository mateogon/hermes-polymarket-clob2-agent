"""Small logging helpers that avoid leaking secrets."""

from __future__ import annotations


SECRET_MARKERS = ("PRIVATE_KEY", "SECRET", "PASSPHRASE", "API_KEY")


def redact(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def sanitize_mapping(data: dict[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, value in data.items():
        if any(marker in key.upper() for marker in SECRET_MARKERS):
            sanitized[key] = redact(str(value))
        else:
            sanitized[key] = value
    return sanitized

