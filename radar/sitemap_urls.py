"""Conservative URL normalization shared by sitemap readers."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def decode_loc(value: str) -> str:
    """Keep the legacy reader's ampersand decoding unchanged."""
    return value.replace("&amp;", "&")


def normalize_url(value: str) -> str:
    """Normalize only URL parts that cannot identify a different page."""
    if any(ord(char) < 32 for char in value):
        raise ValueError("URL contains control characters")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    scheme = parsed.scheme.casefold()
    host = (parsed.hostname or "").casefold().rstrip(".")
    if scheme not in {"http", "https"} or not host:
        raise ValueError("URL must have an HTTP(S) hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    if port == (80 if scheme == "http" else 443):
        port = None
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority = f"{authority}:{port}"
    return urlunsplit((scheme, authority, parsed.path or "/", parsed.query, ""))
