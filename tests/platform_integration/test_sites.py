from __future__ import annotations

import importlib
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg import sql

from radar.platform.db import validate_test_database_url
from radar.platform.migrations import apply_migrations


DAY = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
PUBLIC_IP = ["93.184.216.34"]


def _services(test_dsn: str, schema: str):
    assert importlib.util.find_spec("radar.platform.site_store") is not None, "site snapshot store is missing"
    assert importlib.util.find_spec("radar.platform.site_admin") is not None, "site settings store is missing"
    store_module = importlib.import_module("radar.platform.site_store")
    admin_module = importlib.import_module("radar.platform.site_admin")
    apply_migrations(test_dsn, schema=schema)
    admin = admin_module.SiteAdmin(test_dsn, schema=schema, resolver=lambda host: PUBLIC_IP)
    store = store_module.SiteStore(test_dsn, schema=schema)
    site_id = admin.add_site("Example", "https://example.com/", None)
    return site_id, store, admin, store_module


def _key(site_id: uuid.UUID, day: datetime) -> str:
    return f"site:{site_id}:{day.isoformat()}"


def _counts(test_dsn: str, schema: str, site_id: uuid.UUID) -> tuple[int, int, int]:
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        version = connection.execute("SELECT version FROM radar_site_state WHERE site_id = %s", (site_id,)).fetchone()[0]
        urls = connection.execute("SELECT count(*) FROM radar_site_urls WHERE site_id = %s", (site_id,)).fetchone()[0]
        events = connection.execute("SELECT count(*) FROM radar_site_events WHERE site_id = %s", (site_id,)).fetchone()[0]
    return version, urls, events


def test_first_snapshot_has_zero_events(test_dsn: str, test_schema: str) -> None:
    site_id, store, _, _ = _services(test_dsn, test_schema)
    urls = {"https://example.com/a", "https://example.com/b"}

    result = store.commit_complete(site_id, _key(site_id, DAY), DAY, urls, DAY + timedelta(minutes=1))

    assert result == {"added": 0, "removed": 0, "version": 1, "url_count": 2}
    assert _counts(test_dsn, test_schema, site_id) == (1, 2, 0)
    assert [row["id"] for row in store.list_enabled_sites()] == [site_id]


def test_three_added_two_removed_then_identical_run_zero(test_dsn: str, test_schema: str) -> None:
    site_id, store, _, _ = _services(test_dsn, test_schema)
    first = {f"https://example.com/{part}" for part in ("a", "b", "c")}
    second = {f"https://example.com/{part}" for part in ("c", "d", "e", "f")}
    store.commit_complete(site_id, _key(site_id, DAY), DAY, first, DAY + timedelta(minutes=1))

    changed = store.commit_complete(site_id, _key(site_id, DAY + timedelta(days=1)), DAY + timedelta(days=1), second, DAY + timedelta(days=1, minutes=1))
    unchanged = store.commit_complete(site_id, _key(site_id, DAY + timedelta(days=2)), DAY + timedelta(days=2), second, DAY + timedelta(days=2, minutes=1))
    repeat = store.commit_complete(site_id, _key(site_id, DAY + timedelta(days=2)), DAY + timedelta(days=2), second, DAY + timedelta(days=2, minutes=2))
    changed_replay = store.commit_complete(
        site_id,
        _key(site_id, DAY + timedelta(days=2)),
        DAY + timedelta(days=2),
        second | {"https://example.com/g"},
        DAY + timedelta(days=2, minutes=3),
    )

    assert changed == {"added": 3, "removed": 2, "version": 2, "url_count": 4}
    assert unchanged == {"added": 0, "removed": 0, "version": 3, "url_count": 4}
    assert repeat == {"added": 0, "removed": 0, "version": 3, "url_count": 4}
    assert changed_replay == {"added": 0, "removed": 0, "version": 3, "url_count": 4}
    assert _counts(test_dsn, test_schema, site_id) == (3, 4, 5)


def test_old_slot_cannot_revert_snapshot(test_dsn: str, test_schema: str) -> None:
    site_id, store, _, store_module = _services(test_dsn, test_schema)
    store.commit_complete(site_id, _key(site_id, DAY), DAY, {"https://example.com/a"}, DAY + timedelta(minutes=1))
    newer = DAY + timedelta(days=1)
    store.commit_complete(site_id, _key(site_id, newer), newer, {"https://example.com/b"}, newer + timedelta(minutes=1))

    try:
        store.commit_complete(site_id, _key(site_id, DAY + timedelta(hours=1)), DAY + timedelta(hours=1), {"https://example.com/c"}, newer + timedelta(minutes=2))
    except store_module.StaleSiteSnapshot:
        pass
    else:
        assert False, "old slot must not overwrite the newer complete snapshot"

    assert _counts(test_dsn, test_schema, site_id) == (2, 1, 2)


def test_reappearing_url_is_new_added(test_dsn: str, test_schema: str) -> None:
    site_id, store, _, _ = _services(test_dsn, test_schema)
    a = "https://example.com/a"
    b = "https://example.com/b"
    for offset, urls in enumerate(({a}, {b}, {a, b})):
        slot = DAY + timedelta(days=offset)
        store.commit_complete(site_id, _key(site_id, slot), slot, urls, slot + timedelta(minutes=1))

    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(test_schema)))
        rows = connection.execute(
            "SELECT event_type, url FROM radar_site_events WHERE site_id = %s ORDER BY discovered_at, event_type",
            (site_id,),
        ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [("added", b), ("removed", a), ("added", a)]


def test_site_admin_role_cannot_change_terms_or_events(test_dsn: str, test_schema: str) -> None:
    site_id, _, _, _ = _services(test_dsn, test_schema)
    dsn = os.environ.get("RADAR_TEST_SITE_ADMIN_DATABASE_URL")
    assert dsn, "RADAR_TEST_SITE_ADMIN_DATABASE_URL is required for the site-admin permission gate"
    validate_test_database_url(dsn, os.environ["RADAR_TEST_ALLOWED_HOST"])

    with psycopg.connect(test_dsn) as owner:
        assert owner.execute(
            "SELECT has_table_privilege('radar_platform_site_admin', %s, 'INSERT')",
            (f"{test_schema}.radar_sites",),
        ).fetchone()[0] is True
        for table in ("radar_terms", "radar_site_events", "radar_site_urls", "radar_site_state"):
            assert owner.execute(
                "SELECT has_table_privilege('radar_platform_site_admin', %s, 'INSERT')",
                (f"{test_schema}.{table}",),
            ).fetchone()[0] is False
    with psycopg.connect(dsn, autocommit=True) as connection:
        assert connection.execute("SELECT current_user").fetchone()[0] == "radar_platform_site_admin"
        assert connection.execute(
            sql.SQL("UPDATE {}.radar_sites SET name = 'Allowed' WHERE id = %s").format(sql.Identifier(test_schema)),
            (site_id,),
        ).rowcount == 1
        try:
            connection.execute(sql.SQL("DELETE FROM {}.radar_sites WHERE id = %s").format(sql.Identifier(test_schema)), (site_id,))
        except psycopg.errors.InsufficientPrivilege:
            pass
        else:
            assert False, "site-admin must not delete monitored sites"
