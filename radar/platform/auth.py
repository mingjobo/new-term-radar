from __future__ import annotations

from urllib.parse import urlsplit


def trusted_same_origin(origin: str | None, host: str | None, allowed_origins: set[str]) -> bool:
    """Require a browser Origin explicitly trusted by deployment configuration."""
    if not origin or not host or not allowed_origins:
        return False
    try:
        parsed = urlsplit(origin)
        parsed.port
    except ValueError:
        return False
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.path or parsed.query or parsed.fragment:
        return False
    normalized = f"{parsed.scheme}://{parsed.netloc.casefold()}"
    return normalized in allowed_origins and parsed.netloc.casefold() == host.casefold()
