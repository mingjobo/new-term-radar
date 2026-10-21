from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid

from radar.platform.web import create_app


SITE_ID = str(uuid.uuid4())


class FakeQueries:
    def __init__(self) -> None:
        self.site_filters = None
        self.event_filters = None

    def competitor_sites(self, filters, *, page=1, limit=20):
        self.site_filters = (filters, page, limit)
        return {"items": [{"id": SITE_ID, "name": "Example", "status": "baseline"}], "total": 1}

    def competitor_events(self, site_id, filters, *, page=1, limit=50):
        self.event_filters = (site_id, filters, page, limit)
        return {"items": [{"url": "https://example.com/new", "event_type": "added"}], "total": 1}

    def settings_status(self, now):
        return {"sources": [], "sites": []}


def _request(app, path):
    route, _, query = path.partition("?")
    captured = {}
    auth = "Basic " + base64.b64encode(b"user:password").decode()
    body = b"".join(app({
        "REQUEST_METHOD": "GET", "PATH_INFO": route, "QUERY_STRING": query,
        "HTTP_AUTHORIZATION": auth, "wsgi.input": io.BytesIO(b""),
    }, lambda status, headers: captured.update(status=status)))
    return captured["status"], json.loads(body)


def test_competitor_and_settings_apis_are_paged_and_read_only() -> None:
    queries = FakeQueries()
    app = create_app(queries, username="user", password_sha256=hashlib.sha256(b"password").hexdigest())

    status, payload = _request(app, "/api/competitors?q=Exam&changed=1&page=2&limit=10")
    assert status == "200 OK" and payload["total"] == 1
    assert queries.site_filters == ({"q": "Exam", "changed": "1"}, 2, 10)

    status, payload = _request(app, f"/api/competitors/{SITE_ID}/events?type=removed&q=path&page=3")
    assert status == "200 OK" and payload["total"] == 1
    assert queries.event_filters == (SITE_ID, {"type": "removed", "q": "path"}, 3, 50)

    assert _request(app, "/api/settings/status")[0] == "200 OK"


def test_invalid_competitor_paging_and_id_are_rejected() -> None:
    app = create_app(FakeQueries(), username="user", password_sha256=hashlib.sha256(b"password").hexdigest())
    assert _request(app, "/api/competitors?page=0")[0] == "400 Bad Request"
    assert _request(app, "/api/competitors/not-a-uuid/events")[0] == "400 Bad Request"
