"""Fail-closed browser URL validation."""

from urllib.parse import urlparse

from .config import BrowserConfig


def validate_url(value: str, *, max_length: int = 4096) -> str:
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError("invalid URL")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("unsupported URL scheme")
    if any(character.isspace() for character in value):
        raise ValueError("invalid URL")
    return value