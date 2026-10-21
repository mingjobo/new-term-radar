from __future__ import annotations

import base64
import hashlib
import io
import json
import os

import psycopg
from psycopg import sql

from radar.platform.db import validate_test_database_url
from radar.platform.migrations import apply_migrations
from radar.platform.queries import ReadQueries
from radar.platform.site_admin import SiteAdmin
from radar.platform.web import create_app


def test_site_admin_role_can_manage_only_site_configuration(test_dsn: str, test_schema: str, reader_dsn: str) -> None:
    admin_dsn = os.environ.get("RADAR_TEST_SITE_ADMIN_DATABASE_URL")
    assert admin_dsn, "RADAR_TEST_SITE_ADMIN_DATABASE_URL is required for the site-admin permission gate"
    validate_test_database_url(admin_dsn, os.environ["RADAR_TEST_ALLOWED_HOST"])
    apply_migrations(test_dsn, schema=test_schema)

    admin = SiteAdmin(admin_dsn, schema=test_schema, resolver=lambda _host: ["93.184.216.34"])
    site_id = admin.add_site("Competitor", "https://example.com/", "https://example.com/sitemap.xml")
    admin.update_site(site_id, name="Paused", sitemap_url=None, enabled=False)
    admin.update_site(site_id, name="Resumed", sitemap_url=None, enabled=True)

    password = "test-password"
    app = create_app(
        ReadQueries(reader_dsn, schema=test_schema),
        username="tester",
        password_sha256=hashlib.sha256(password.encode()).hexdigest(),
        site_admin=admin,
        allowed_origins={"https://radar.example.test"},
    )
    body = json.dumps({"name": "Via web", "homepage_url": "https://example.org/"}).encode()
    headers = {}
    response = b"".join(app({
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/api/settings/sites",
        "QUERY_STRING": "",
        "HTTP_HOST": "radar.example.test",
        "HTTP_ORIGIN": "https://radar.example.test",
        "HTTP_AUTHORIZATION": "Basic " + base64.b64encode(f"tester:{password}".encode()).decode(),
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }, lambda status, values: headers.update(status=status)))
    assert headers["status"] == "201 Created"
    assert json.loads(response)["id"]

    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            sql.SQL("SELECT count(*) FROM {}.radar_sites").format(sql.Identifier(test_schema))
        ).fetchone()[0] == 2
        row = connection.execute(
            sql.SQL("SELECT name, enabled FROM {}.radar_sites WHERE id = %s").format(sql.Identifier(test_schema)),
            (site_id,),
        ).fetchone()
        assert row == ("Resumed", True)
        for table in ("radar_terms", "radar_site_state", "radar_site_urls", "radar_site_events"):
            assert connection.execute(
                "SELECT has_table_privilege(current_user, %s, 'INSERT')",
                (f"{test_schema}.{table}",),
            ).fetchone()[0] is False
