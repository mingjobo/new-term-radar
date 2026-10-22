from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql

from radar.platform.migrations import apply_migrations
from radar.platform.models import HttpResponse
from radar.platform.repository import Repository
from radar.platform.site_admin import SiteAdmin
from radar.platform.site_store import SiteStore


NOW = datetime.now(ZoneInfo("Asia/Shanghai")).replace(
    hour=9, minute=0, second=0, microsecond=0
).astimezone(timezone.utc)


def _xml(*paths: str) -> bytes:
    urls = "".join(f"<url><loc>https://example.com/{path}</loc></url>" for path in paths)
    return f"<urlset>{urls}</urlset>".encode()


class SiteHttp:
    tick_requests = 0

    def __init__(self, sitemap: bytes, *, status: int = 200) -> None:
        self.sitemap = sitemap
        self.status = status

    def request(self, method: str, url: str, *, headers=None) -> HttpResponse:
        self.tick_requests += 1
        if url.endswith("robots.txt"):
            return HttpResponse(404, {}, b"")
        return HttpResponse(self.status, {}, self.sitemap)


def _services(dsn: str, schema: str):
    apply_migrations(dsn, schema=schema)
    admin = SiteAdmin(dsn, schema=schema, resolver=lambda _host: ["93.184.216.34"])
    site_id = admin.add_site("Example", "https://example.com/", None)
    return Repository(dsn, schema=schema), SiteStore(dsn, schema=schema), admin, site_id


def _state(dsn: str, schema: str, site_id) -> tuple[int, int, int]:
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        version = connection.execute("SELECT version FROM radar_site_state WHERE site_id = %s", (site_id,)).fetchone()[0]
        urls = connection.execute("SELECT count(*) FROM radar_site_urls WHERE site_id = %s", (site_id,)).fetchone()[0]
        events = connection.execute("SELECT count(*) FROM radar_site_events WHERE site_id = %s", (site_id,)).fetchone()[0]
    return version, urls, events


def test_first_complete_run_only_builds_baseline_and_later_diff(test_dsn: str, test_schema: str) -> None:
    from radar.platform.schedule import run_due_sites

    repo, store, _, site_id = _services(test_dsn, test_schema)
    pages = [_xml("a", "b", "c"), _xml("c", "d", "e", "f"), _xml("c", "d", "e", "f")]

    first = run_due_sites(repo, store, NOW, lambda _host: SiteHttp(pages[0]), max_jobs=10)
    assert first.status == "ok" and first.jobs == 1
    assert _state(test_dsn, test_schema, site_id) == (1, 3, 0)

    second = run_due_sites(repo, store, NOW + timedelta(days=1), lambda _host: SiteHttp(pages[1]), max_jobs=10)
    assert second.status == "ok" and second.jobs == 1
    assert _state(test_dsn, test_schema, site_id) == (2, 4, 5)

    third = run_due_sites(repo, store, NOW + timedelta(days=2), lambda _host: SiteHttp(pages[2]), max_jobs=10)
    repeated = run_due_sites(repo, store, NOW + timedelta(days=2, minutes=1), lambda _host: SiteHttp(pages[2]), max_jobs=10)
    assert third.status == "ok" and third.jobs == 1
    assert repeated.jobs == 0
    assert _state(test_dsn, test_schema, site_id) == (3, 4, 5)


def test_incomplete_site_keeps_previous_snapshot_and_pause_keeps_history(test_dsn: str, test_schema: str) -> None:
    from radar.platform.schedule import run_due_sites

    repo, store, admin, site_id = _services(test_dsn, test_schema)
    run_due_sites(repo, store, NOW, lambda _host: SiteHttp(_xml("a", "b")), max_jobs=10)
    before = _state(test_dsn, test_schema, site_id)

    incomplete = run_due_sites(repo, store, NOW + timedelta(days=1), lambda _host: SiteHttp(b"", status=500), max_jobs=10)
    assert incomplete.status != "ok"
    assert _state(test_dsn, test_schema, site_id) == before

    admin.update_site(site_id, name="Example paused", sitemap_url=None, enabled=False)
    paused = run_due_sites(repo, store, NOW + timedelta(days=2), lambda _host: SiteHttp(_xml("new")), max_jobs=10)
    assert paused.jobs == 0
    assert _state(test_dsn, test_schema, site_id) == before
