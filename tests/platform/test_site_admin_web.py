from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid

import pytest
import psycopg

from radar.platform.site_admin import SiteAdmin
from radar.platform.web import create_app, create_app_from_env


USER = "researcher"
PASS = "correct horse battery staple"
HASH = hashlib.sha256(PASS.encode()).hexdigest()
ORIGIN = "https://radar.example.test"


class FakeAdmin:
    def __init__(self) -> None:
        self.added: list[tuple] = []
        self.updated: list[tuple] = []
        self.id = uuid.uuid4()

    def add_site(self, name, homepage_url, sitemap_url):
        self.added.append((name, homepage_url, sitemap_url))
        return self.id

    def update_site(self, site_id, *, name, sitemap_url, enabled):
        self.updated.append((site_id, name, sitemap_url, enabled))


def _auth() -> str:
    return "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()


def _call(app, path: str, *, method="POST", payload=None, auth=None, origin=None, host="radar.example.test", content_type="application/json"):
    body = json.dumps(payload).encode() if payload is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "HTTP_HOST": host,
        "SERVER_NAME": host,
        "SERVER_PORT": "443",
        "wsgi.url_scheme": "https",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    if auth is not None:
        environ["HTTP_AUTHORIZATION"] = auth
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    response = b"".join(app(environ, start_response))
    return captured["status"], json.loads(response) if response.startswith(b"{") else response


def _app(admin=None):
    return create_app(
        object(), username=USER, password_sha256=HASH,
        site_admin=admin, allowed_origins={ORIGIN},
    )


def test_admin_write_requires_basic_auth_and_same_origin() -> None:
    admin = FakeAdmin()
    app = _app(admin)
    payload = {"name": "Competitor", "homepage_url": "https://example.com/", "sitemap_url": None}

    assert _call(app, "/api/settings/sites", payload=payload, origin=ORIGIN)[0] == "401 Unauthorized"
    assert _call(app, "/api/settings/sites", payload=payload, auth=_auth())[0] == "403 Forbidden"
    status, response = _call(app, "/api/settings/sites", payload=payload, auth=_auth(), origin=ORIGIN)

    assert status == "201 Created"
    assert response == {"id": str(admin.id)}
    assert admin.added == [("Competitor", "https://example.com/", None)]


@pytest.mark.parametrize("origin,host", [
    ("https://evil.example", "radar.example.test"),
    (ORIGIN, "evil.example"),
    ("http://radar.example.test", "radar.example.test"),
])
def test_cross_site_or_mismatched_host_rejected(origin: str, host: str) -> None:
    admin = FakeAdmin()
    app = _app(admin)
    status, _ = _call(app, "/api/settings/sites", payload={"name": "X", "homepage_url": "https://example.com/"}, auth=_auth(), origin=origin, host=host)
    assert status == "403 Forbidden"
    assert admin.added == []


def test_patch_cannot_change_homepage_host_or_send_unknown_fields() -> None:
    admin = FakeAdmin()
    app = _app(admin)
    path = f"/api/settings/sites/{admin.id}"
    payload = {"name": "Renamed", "sitemap_url": None, "enabled": False, "homepage_url": "https://other.com/"}

    status, _ = _call(app, path, method="PATCH", payload=payload, auth=_auth(), origin=ORIGIN)
    assert status == "400 Bad Request"
    assert admin.updated == []

    del payload["homepage_url"]
    status, response = _call(app, path, method="PATCH", payload=payload, auth=_auth(), origin=ORIGIN)
    assert status == "200 OK"
    assert response == {"id": str(admin.id), "updated": True}
    assert admin.updated == [(admin.id, "Renamed", None, False)]


def test_json_only_and_bounded_body() -> None:
    admin = FakeAdmin()
    app = _app(admin)
    payload = {"name": "X" * 17_000, "homepage_url": "https://example.com/"}
    assert _call(app, "/api/settings/sites", payload=payload, auth=_auth(), origin=ORIGIN)[0] == "413 Payload Too Large"
    assert _call(app, "/api/settings/sites", payload={}, auth=_auth(), origin=ORIGIN, content_type="text/plain")[0] == "415 Unsupported Media Type"


def test_missing_admin_dsn_disables_writes_without_writer_fallback() -> None:
    env = {
        "RADAR_READ_DATABASE_URL": "postgresql://reader:secret@example.test/db",
        "RADAR_WRITE_DATABASE_URL": "postgresql://writer:secret@example.test/db",
        "RADAR_WEB_USERNAME": USER,
        "RADAR_WEB_PASSWORD_SHA256": HASH,
    }
    app = create_app_from_env(env)
    assert _call(app, "/api/settings/sites", payload={}, auth=_auth(), origin=ORIGIN)[0] == "405 Method Not Allowed"


def test_private_and_cross_domain_site_urls_are_rejected_before_database_access() -> None:
    admin = SiteAdmin("postgresql://unused:unused@example.test/db", resolver=lambda _host: ["93.184.216.34"])
    with pytest.raises(ValueError, match="private"):
        admin.add_site("Private", "http://127.0.0.1/", None)
    with pytest.raises(ValueError, match="hostname"):
        admin.add_site("Cross host", "https://example.com/", "https://other.example/sitemap.xml")


def test_duplicate_site_has_safe_conflict_response() -> None:
    class DuplicateAdmin(FakeAdmin):
        def add_site(self, name, homepage_url, sitemap_url):
            raise psycopg.errors.UniqueViolation("duplicate key value violates unique constraint")

    app = _app(DuplicateAdmin())
    status, response = _call(
        app, "/api/settings/sites",
        payload={"name": "X", "homepage_url": "https://example.com/"},
        auth=_auth(), origin=ORIGIN,
    )
    assert status == "409 Conflict"
    assert response == {"error": "site hostname is already monitored"}


def test_admin_dsn_requires_explicit_trusted_origins() -> None:
    env = {
        "RADAR_READ_DATABASE_URL": "postgresql://reader:secret@example.test/db",
        "RADAR_SITE_ADMIN_DATABASE_URL": "postgresql://siteadmin:secret@example.test/db",
        "RADAR_WEB_USERNAME": USER,
        "RADAR_WEB_PASSWORD_SHA256": HASH,
    }
    with pytest.raises(RuntimeError, match="RADAR_WEB_ALLOWED_ORIGINS"):
        create_app_from_env(env)
