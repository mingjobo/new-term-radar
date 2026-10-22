from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone

import pytest

from radar.platform.web import _selected_day, create_app, create_app_from_env, safe_external_url


class FakeQueries:
    def __init__(self) -> None:
        self.last_filters = None
        self.last_cursor = None
        self.last_limit = None
        self.overview_day = None
        self.daily_day = None

    def overview(self, day, now):
        self.overview_day = day
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

    def daily_terms(self, day, *, cursor=None, limit=50):
        self.daily_day = day
        return {"date": day.isoformat(), "items": [], "next_cursor": None}

    def competitor_sites(self, filters, *, page=1, limit=20):
        return {"items": [], "page": page, "limit": limit, "total": 0}

    def settings_status(self, now):
        return {"sources": [], "sites": []}


def _request(app, path: str, *, method: str = "GET"):
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
    return create_app(queries)


@pytest.mark.parametrize("path", ["/", "/api/overview", "/api/daily-terms", "/api/competitors", "/api/settings/status", "/static/app.css"])
def test_public_routes_need_no_credentials(app, path: str) -> None:
    status, headers, _ = _request(app, path)

    assert status == "200 OK"
    assert "WWW-Authenticate" not in headers


def test_public_page_and_get_apis(app, queries: FakeQueries) -> None:
    status, headers, page = _request(app, "/")
    assert status == "200 OK"
    assert headers["Content-Type"].startswith("text/html")
    assert b"TERM SIGNAL" in page

    status, _, body = _request(
        app,
        "/api/terms?source=github%3Abreakout&kind=name&sort=newest&limit=999&cursor=abc",
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
        assert _request(app, path)[0] == "200 OK"


@pytest.mark.parametrize("path", ["/refresh", "/research", "/api/refresh", "/api/research"])
def test_refresh_and_research_posts_are_not_exposed(app, path: str) -> None:
    status, headers, _ = _request(app, path, method="POST")

    assert status == "405 Method Not Allowed"
    assert headers["Allow"] == "GET, HEAD"


def test_missing_read_database_url_never_falls_back_to_writer() -> None:
    env = {
        "RADAR_WRITE_DATABASE_URL": "postgresql://writer:secret@example.test/db",
        "DATABASE_URL": "postgresql://legacy:secret@example.test/db",
    }

    with pytest.raises(RuntimeError, match="RADAR_READ_DATABASE_URL"):
        create_app_from_env(env)


def test_untrusted_text_uses_dom_text_and_javascript_urls_are_rejected(app) -> None:
    assert safe_external_url("javascript:alert(1)") is None
    assert safe_external_url("data:text/html,bad") is None
    assert safe_external_url("https://github.com/acme/radar") == "https://github.com/acme/radar"

    status, headers, javascript = _request(app, "/static/app.js")
    assert status == "200 OK"
    script = javascript.decode()
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "safeHttpUrl" in script
    assert "fetch(new URL(path, window.location.origin)" in script
    assert headers["Content-Security-Policy"].startswith("default-src 'self'")


def test_invalid_sort_is_rejected(app) -> None:
    status, _, body = _request(app, "/api/terms?sort=drop-table")
    assert status == "400 Bad Request"
    assert json.loads(body) == {"error": "unsupported sort"}


def test_future_date_rejected_before_daily_queries(app) -> None:
    for path in ("/api/overview?date=9999-12-31", "/api/daily-terms?date=9999-12-31"):
        status, _, body = _request(app, path)
        assert status == "400 Bad Request"
        assert json.loads(body)["error"] == "future date is not allowed"


def test_selected_date_reaches_both_daily_endpoints(app, queries: FakeQueries) -> None:
    assert _request(app, "/api/overview?date=2026-10-20")[0] == "200 OK"
    assert _request(app, "/api/daily-terms?date=2026-10-20")[0] == "200 OK"
    assert queries.overview_day == date(2026, 10, 20)
    assert queries.daily_day == date(2026, 10, 20)


def test_default_date_uses_beijing_midnight_boundary() -> None:
    assert _selected_day("", datetime(2026, 10, 20, 15, 59, tzinfo=timezone.utc)) == date(2026, 10, 20)
    assert _selected_day("", datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)) == date(2026, 10, 21)
