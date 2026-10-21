from __future__ import annotations

import base64
import hashlib
import io
import json

import pytest

from radar.platform.web import create_app, create_app_from_env, safe_external_url


USERNAME = "researcher"
PASSWORD = "correct horse battery staple"
PASSWORD_HASH = hashlib.sha256(PASSWORD.encode()).hexdigest()


class FakeQueries:
    def __init__(self) -> None:
        self.last_filters = None
        self.last_cursor = None
        self.last_limit = None

    def overview(self, now):
        return {
            "new_terms_today": 1,
            "evidence_today": 1,
            "source_count": 3,
            "latest_run_at": "2026-10-15T10:31:10+00:00",
        }

    def terms(self, filters, *, cursor=None, limit=50):
        self.last_filters = filters
        self.last_cursor = cursor
        self.last_limit = limit
        return {
            "items": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "<img src=x onerror=alert(1)>",
                    "kind": "name",
                    "source_instance": "github:breakout",
                    "url": "javascript:alert(1)",
                    "first_seen_at": "2026-10-15T10:31:10+00:00",
                }
            ],
            "next_cursor": "next",
        }

    def term(self, term_id):
        return {
            "id": term_id,
            "name": "<script>alert(1)</script>",
            "kind": "name",
            "evidence": [
                {
                    "excerpt": "<b>untrusted</b>",
                    "url": "javascript:alert(1)",
                    "source_instance": "github:breakout",
                    "observed_at": "2026-10-15T10:31:10+00:00",
                }
            ],
        }

    def sources(self, now):
        return [{"source_instance": "hf:models", "status": "baseline", "snapshot_items": 100}]


def _auth(username: str = USERNAME, password: str = PASSWORD) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def _request(app, path: str, *, method: str = "GET", auth: str | None = None):
    route, _, query = path.partition("?")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": route,
        "QUERY_STRING": query,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
    }
    if auth is not None:
        environ["HTTP_AUTHORIZATION"] = auth
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


@pytest.fixture
def queries() -> FakeQueries:
    return FakeQueries()


@pytest.fixture
def app(queries: FakeQueries):
    return create_app(queries, username=USERNAME, password_sha256=PASSWORD_HASH)


@pytest.mark.parametrize("path", ["/", "/api/overview", "/api/terms", "/api/sources", "/static/app.css"])
def test_every_route_requires_basic_auth(app, path: str) -> None:
    status, headers, _ = _request(app, path)

    assert status == "401 Unauthorized"
    assert headers["WWW-Authenticate"].startswith("Basic ")


def test_correct_credentials_allow_page_and_get_apis(app, queries: FakeQueries) -> None:
    status, headers, page = _request(app, "/", auth=_auth())
    assert status == "200 OK"
    assert headers["Content-Type"].startswith("text/html")
    assert b"TERM SIGNAL" in page

    status, _, body = _request(
        app,
        "/api/terms?source=github%3Abreakout&kind=name&sort=newest&limit=999&cursor=abc",
        auth=_auth(),
    )
    assert status == "200 OK"
    assert json.loads(body)["items"][0]["name"].startswith("<img")
    assert queries.last_filters == {"source": "github:breakout", "kind": "name", "sort": "newest"}
    assert queries.last_cursor == "abc"
    assert queries.last_limit == 100

    for path in (
        "/api/overview",
        "/api/sources",
        "/api/terms/00000000-0000-0000-0000-000000000001",
    ):
        assert _request(app, path, auth=_auth())[0] == "200 OK"


@pytest.mark.parametrize("path", ["/refresh", "/research", "/api/refresh", "/api/research"])
def test_refresh_and_research_posts_are_not_exposed(app, path: str) -> None:
    status, headers, _ = _request(app, path, method="POST", auth=_auth())

    assert status == "405 Method Not Allowed"
    assert headers["Allow"] == "GET, HEAD"


def test_missing_read_database_url_never_falls_back_to_writer() -> None:
    env = {
        "RADAR_WRITE_DATABASE_URL": "postgresql://writer:secret@example.test/db",
        "DATABASE_URL": "postgresql://legacy:secret@example.test/db",
        "RADAR_WEB_USERNAME": USERNAME,
        "RADAR_WEB_PASSWORD_SHA256": PASSWORD_HASH,
    }

    with pytest.raises(RuntimeError, match="RADAR_READ_DATABASE_URL"):
        create_app_from_env(env)


def test_untrusted_text_uses_dom_text_and_javascript_urls_are_rejected(app) -> None:
    assert safe_external_url("javascript:alert(1)") is None
    assert safe_external_url("data:text/html,bad") is None
    assert safe_external_url("https://github.com/acme/radar") == "https://github.com/acme/radar"

    status, headers, javascript = _request(app, "/static/app.js", auth=_auth())
    assert status == "200 OK"
    script = javascript.decode()
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "safeHttpUrl" in script
    assert "fetch(new URL(path, window.location.origin)" in script
    assert headers["Content-Security-Policy"].startswith("default-src 'self'")


def test_invalid_credentials_and_sort_are_rejected(app) -> None:
    assert _request(app, "/", auth=_auth(password="wrong"))[0] == "401 Unauthorized"
    status, _, body = _request(app, "/api/terms?sort=drop-table", auth=_auth())
    assert status == "400 Bad Request"
    assert json.loads(body) == {"error": "unsupported sort"}
