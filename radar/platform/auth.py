from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from urllib.parse import urlsplit


class BasicAuth:
    def __init__(self, *, username: str, password_sha256: str) -> None:
        if not username:
            raise ValueError("web username cannot be empty")
        normalized_hash = password_sha256.casefold()
        if len(normalized_hash) != 64 or any(char not in "0123456789abcdef" for char in normalized_hash):
            raise ValueError("web password hash must be a SHA-256 hexadecimal digest")
        self.username = username
        self.password_sha256 = normalized_hash

    def authorized(self, authorization: str | None) -> bool:
        supplied_username = ""
        supplied_password = ""
        if authorization and authorization.startswith("Basic "):
            try:
                decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
                supplied_username, supplied_password = decoded.split(":", 1)
            except (binascii.Error, UnicodeDecodeError, ValueError):
                pass
        supplied_hash = hashlib.sha256(supplied_password.encode()).hexdigest()
        username_ok = hmac.compare_digest(supplied_username.encode(), self.username.encode())
        password_ok = hmac.compare_digest(supplied_hash, self.password_sha256)
        return bool(username_ok & password_ok)


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
