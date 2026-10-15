from __future__ import annotations

import json
import mimetypes
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlsplit

from .auth import BasicAuth
from .queries import ReadQueries


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "templates/index.html"
STATIC = ROOT / "static"
SECURITY_HEADERS = [
    ("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
]


def safe_external_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme in {"http", "https"} and bool(parsed.netloc) else None


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _response(start_response, status: str, body: bytes, content_type: str, extra=None, *, head=False):
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        *SECURITY_HEADERS,
    ]
    if extra:
        headers.extend(extra)
    start_response(status, headers)
    return [] if head else [body]


def _json_response(start_response, status: str, payload: Any, *, head: bool = False):
    body = json.dumps(payload, ensure_ascii=False, default=_json_default, separators=(",", ":")).encode()
    return _response(start_response, status, body, "application/json; charset=utf-8", head=head)


def create_app(
    queries: ReadQueries,
    *,
    username: str,
    password_sha256: str,
) -> Callable:
    auth = BasicAuth(username=username, password_sha256=password_sha256)
    page = TEMPLATE.read_bytes()
    static_files = {
        "/static/app.js": (STATIC / "app.js").read_bytes(),
        "/static/app.css": (STATIC / "app.css").read_bytes(),
    }

    def app(environ, start_response):
        head = environ.get("REQUEST_METHOD", "GET").upper() == "HEAD"
        if not auth.authorized(environ.get("HTTP_AUTHORIZATION")):
            return _response(
                start_response,
                "401 Unauthorized",
                b"Authentication required",
                "text/plain; charset=utf-8",
                [("WWW-Authenticate", 'Basic realm="Term Signal", charset="UTF-8"')],
                head=head,
            )
        method = environ.get("REQUEST_METHOD", "GET").upper()
        if method not in {"GET", "HEAD"}:
            return _response(
                start_response,
                "405 Method Not Allowed",
                b"Read-only service",
                "text/plain; charset=utf-8",
                [("Allow", "GET, HEAD")],
            )
        path = environ.get("PATH_INFO") or "/"
        now = datetime.now(timezone.utc)
        try:
            if path in {"/", "/index.html"} or path.startswith("/terms/"):
                return _response(start_response, "200 OK", page, "text/html; charset=utf-8", head=head)
            if path in static_files:
                content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
                if content_type.startswith("text/") or content_type == "application/javascript":
                    content_type += "; charset=utf-8"
                return _response(start_response, "200 OK", static_files[path], content_type, head=head)
            if path == "/api/overview":
                return _json_response(start_response, "200 OK", queries.overview(now), head=head)
            if path == "/api/sources":
                return _json_response(start_response, "200 OK", {"items": queries.sources(now)}, head=head)
            if path == "/api/terms":
                query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=False)
                sort = query.get("sort", ["newest"])[0]
                if sort != "newest":
                    return _json_response(start_response, "400 Bad Request", {"error": "unsupported sort"}, head=head)
                filters = {
                    key: query[key][0]
                    for key in ("source", "kind", "q", "since")
                    if query.get(key)
                }
                filters["sort"] = sort
                try:
                    limit = min(max(int(query.get("limit", ["50"])[0]), 1), 100)
                except ValueError:
                    return _json_response(start_response, "400 Bad Request", {"error": "invalid limit"}, head=head)
                payload = queries.terms(
                    filters,
                    cursor=query.get("cursor", [None])[0],
                    limit=limit,
                )
                return _json_response(start_response, "200 OK", payload, head=head)
            if path.startswith("/api/terms/"):
                term = queries.term(path.removeprefix("/api/terms/"))
                if term is None:
                    return _json_response(start_response, "404 Not Found", {"error": "term not found"}, head=head)
                return _json_response(start_response, "200 OK", term, head=head)
        except ValueError as exc:
            return _json_response(start_response, "400 Bad Request", {"error": str(exc)}, head=head)
        return _json_response(start_response, "404 Not Found", {"error": "not found"}, head=head)

    return app


def create_app_from_env(environ: Mapping[str, str] | None = None) -> Callable:
    env = os.environ if environ is None else environ
    dsn = env.get("RADAR_READ_DATABASE_URL")
    if not dsn:
        raise RuntimeError("RADAR_READ_DATABASE_URL is required; writer and legacy URLs are never fallbacks")
    username = env.get("RADAR_WEB_USERNAME")
    password_hash = env.get("RADAR_WEB_PASSWORD_SHA256")
    if not username or not password_hash:
        raise RuntimeError("RADAR_WEB_USERNAME and RADAR_WEB_PASSWORD_SHA256 are required")
    return create_app(ReadQueries(dsn), username=username, password_sha256=password_hash)
