"""Fail-closed browser URL validation."""

import ipaddress
from urllib.parse import urlparse

from .config import BrowserConfig


def validate_url(value: str, *, max_length: int = 4096) -> str:
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError("invalid URL")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("unsupported URL scheme")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("embedded credentials are not allowed")
    if any(character.isspace() for character in value):
        raise ValueError("invalid URL")
    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".localhost", ".local", ".lan", ".internal")):
        raise ValueError("private network host is not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified):
        raise ValueError("private network address is not allowed")
    return value