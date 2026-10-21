from __future__ import annotations

import base64
import binascii
import hashlib
import hmac


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
