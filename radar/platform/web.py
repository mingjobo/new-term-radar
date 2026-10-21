from __future__ import annotations

import json
import mimetypes
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.errors import UniqueViolation

from .auth import BasicAuth, trusted_same_origin
from .queries import ReadQueries
from .site_admin import SiteAdmin


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "templates/index.html"
STATIC = ROOT / "static"
MAX_WRITE_BODY = 16 * 1024
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


class _WriteError(ValueError):
    def __init__(self, status: str, message: str) -> None:
        self.status = status
        super().__init__(message)


def _write_payload(environ, *, required: set[str], allowed: set[str]) -> dict[str, Any]:
    content_type = str(environ.get("CONTENT_TYPE", "")).split(";", 1)[0].strip().casefold()
    if content_type != "application/json":
        raise _WriteError("415 Unsupported Media Type", "application/json is required")
    try:
        declared = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise _WriteError("400 Bad Request", "invalid content length") from exc
    if declared < 0:
        raise _WriteError("400 Bad Request", "invalid content length")
    if declared > MAX_WRITE_BODY:
        raise _WriteError("413 Payload Too Large", "settings request is too large")
    stream = environ.get("wsgi.input")
    if stream is None:
        raise _WriteError("400 Bad Request", "missing request body")
    body = stream.read(declared) if declared else stream.read(MAX_WRITE_BODY + 1)
    if len(body) > MAX_WRITE_BODY:
        raise _WriteError("413 Payload Too Large", "settings request is too large")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _WriteError("400 Bad Request", "invalid JSON body") from exc
    if not isinstance(payload, dict) or not required.issubset(payload) or set(payload) - allowed:
        raise _WriteError("400 Bad Request", "invalid settings fields")
    return payload


def _selected_day(query_string: str, now: datetime) -> date:
    query = parse_qs(query_string, keep_blank_values=True)
    raw = query.get("date", [None])[0]
    if raw is None:
        selected = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    else:
        try:
            selected = date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("invalid date") from exc
        if selected.isoformat() != raw:
            raise ValueError("invalid date")
    if selected > now.astimezone(ZoneInfo("Asia/Shanghai")).date():
        raise ValueError("future date is not allowed")
    return selected


def create_app(
    queries: ReadQueries,
    *,
    username: str,
    password_sha256: str,
    site_admin: SiteAdmin | None = None,
    allowed_origins: set[str] | None = None,
) -> Callable:
    auth = BasicAuth(username=username, password_sha256=password_sha256)
    trusted_origins = {origin.rstrip("/").casefold() for origin in (allowed_origins or set())}
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
        path = environ.get("PATH_INFO") or "/"
        if method in {"POST", "PATCH"} and (path == "/api/settings/sites" or path.startswith("/api/settings/sites/")):
            if site_admin is None:
                return _json_response(start_response, "405 Method Not Allowed", {"error": "settings writes unavailable"})
            if not trusted_same_origin(environ.get("HTTP_ORIGIN"), environ.get("HTTP_HOST"), trusted_origins):
                return _json_response(start_response, "403 Forbidden", {"error": "same-origin request required"})
            try:
                if method == "POST" and path == "/api/settings/sites":
                    payload = _write_payload(
                        environ,
                        required={"name", "homepage_url"},
                        allowed={"name", "homepage_url", "sitemap_url"},
                    )
                    if not isinstance(payload["name"], str) or not isinstance(payload["homepage_url"], str):
                        raise ValueError("name and homepage_url must be strings")
                    sitemap_url = payload.get("sitemap_url")
                    if sitemap_url is not None and not isinstance(sitemap_url, str):
                        raise ValueError("sitemap_url must be a string or null")
                    site_id = site_admin.add_site(payload["name"], payload["homepage_url"], sitemap_url)
                    return _json_response(start_response, "201 Created", {"id": str(site_id)})
                if method == "PATCH" and path.startswith("/api/settings/sites/"):
                    site_id = UUID(path.removeprefix("/api/settings/sites/"))
                    payload = _write_payload(
                        environ,
                        required={"name", "enabled"},
                        allowed={"name", "sitemap_url", "enabled"},
                    )
                    if not isinstance(payload["name"], str) or not isinstance(payload["enabled"], bool):
                        raise ValueError("name must be a string and enabled a boolean")
                    sitemap_url = payload.get("sitemap_url")
                    if sitemap_url is not None and not isinstance(sitemap_url, str):
                        raise ValueError("sitemap_url must be a string or null")
                    site_admin.update_site(
                        site_id, name=payload["name"], sitemap_url=sitemap_url, enabled=payload["enabled"]
                    )
                    return _json_response(start_response, "200 OK", {"id": str(site_id), "updated": True})
            except _WriteError as exc:
                return _json_response(start_response, exc.status, {"error": str(exc)})
            except UniqueViolation:
                return _json_response(
                    start_response, "409 Conflict", {"error": "site hostname is already monitored"}
                )
            except ValueError as exc:
                return _json_response(start_response, "400 Bad Request", {"error": str(exc)})
            return _json_response(start_response, "404 Not Found", {"error": "not found"})
        if method not in {"GET", "HEAD"}:
            return _response(
                start_response,
                "405 Method Not Allowed",
                b"Read-only service",
                "text/plain; charset=utf-8",
                [("Allow", "GET, HEAD")],
            )
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
                day = _selected_day(environ.get("QUERY_STRING", ""), now)
                return _json_response(start_response, "200 OK", queries.overview(day, now), head=head)
            if path == "/api/daily-terms":
                day = _selected_day(environ.get("QUERY_STRING", ""), now)
                query = parse_qs(environ.get("QUERY_STRING", ""))
                try:
                    limit = min(max(int(query.get("limit", ["50"])[0]), 1), 100)
                except ValueError:
                    return _json_response(start_response, "400 Bad Request", {"error": "invalid limit"}, head=head)
                return _json_response(
                    start_response, "200 OK",
                    queries.daily_terms(day, cursor=query.get("cursor", [None])[0], limit=limit),
                    head=head,
                )
            if path == "/api/competitors":
                query = parse_qs(environ.get("QUERY_STRING", ""))
                try:
                    page_number = int(query.get("page", ["1"])[0])
                    limit = int(query.get("limit", ["20"])[0])
                except ValueError:
                    return _json_response(start_response, "400 Bad Request", {"error": "invalid page or limit"}, head=head)
                if page_number < 1 or not 1 <= limit <= 100:
                    return _json_response(start_response, "400 Bad Request", {"error": "invalid page or limit"}, head=head)
                filters = {key: query[key][0] for key in ("q", "changed", "status", "from", "to") if query.get(key)}
                return _json_response(
                    start_response, "200 OK",
                    queries.competitor_sites(filters, page=page_number, limit=limit), head=head,
                )
            if path.startswith("/api/competitors/") and path.endswith("/events"):
                site_id = path.removeprefix("/api/competitors/").removesuffix("/events")
                try:
                    UUID(site_id)
                except ValueError:
                    return _json_response(start_response, "400 Bad Request", {"error": "invalid site ID"}, head=head)
                query = parse_qs(environ.get("QUERY_STRING", ""))
                try:
                    page_number = int(query.get("page", ["1"])[0])
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError:
                    return _json_response(start_response, "400 Bad Request", {"error": "invalid page or limit"}, head=head)
                if page_number < 1 or not 1 <= limit <= 100:
                    return _json_response(start_response, "400 Bad Request", {"error": "invalid page or limit"}, head=head)
                filters = {key: query[key][0] for key in ("type", "q", "from", "to") if query.get(key)}
                return _json_response(
                    start_response, "200 OK",
                    queries.competitor_events(site_id, filters, page=page_number, limit=limit), head=head,
                )
            if path == "/api/settings/status":
                return _json_response(start_response, "200 OK", queries.settings_status(now), head=head)
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
    admin_dsn = env.get("RADAR_SITE_ADMIN_DATABASE_URL")
    origins = {value.strip() for value in env.get("RADAR_WEB_ALLOWED_ORIGINS", "").split(",") if value.strip()}
    if admin_dsn and not origins:
        raise RuntimeError("RADAR_WEB_ALLOWED_ORIGINS is required when settings writes are enabled")
    return create_app(
        ReadQueries(dsn), username=username, password_sha256=password_hash,
        site_admin=SiteAdmin(admin_dsn) if admin_dsn else None,
        allowed_origins=origins,
    )
