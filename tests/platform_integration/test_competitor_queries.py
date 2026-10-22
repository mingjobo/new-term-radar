from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from radar.platform.queries import ReadQueries


NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
FILTERS = {"from": "2026-10-21", "to": "2026-10-21"}


def _site(connection, name: str, host: str, *, version: int | None = None, enabled: bool = True) -> uuid.UUID:
    site_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO radar_sites (id, name, homepage_url, host, enabled, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (site_id, name, f"https://{host}/", host, enabled, NOW),
    )
    if version is not None:
        connection.execute(
            "INSERT INTO radar_site_state "
            "(site_id, version, url_count, last_success_at, last_run_key, last_scheduled_for) "
            "VALUES (%s, %s, 12, %s, %s, %s)",
            (site_id, version, NOW, f"site:{site_id}:2026-10-21", NOW),
        )
    return site_id


def _run(connection, source: str, status: str, result: dict | None = None, *, at: datetime = NOW) -> None:
    job_key = f"test:{source}:{uuid.uuid4()}"
    connection.execute(
        "INSERT INTO radar_jobs (job_key, task, payload, scheduled_for, status) "
        "VALUES (%s, 'test', %s, %s, 'complete')",
        (job_key, Jsonb({"source_instance": source}), at),
    )
    connection.execute(
        "INSERT INTO radar_runs "
        "(id, job_key, lease_token, source_instance, status, result, started_at, finished_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (uuid.uuid4(), job_key, uuid.uuid4(), source, status, Jsonb(result or {}), at, at),
    )


def test_large_competitor_pages_match_counts(test_dsn: str, migrated_schema: str, reader_dsn: str) -> None:
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(migrated_schema)))
        ids = [_site(connection, f"Site {n:02d}", f"site{n:02d}.example.com") for n in range(20)]
        site_id = ids[0]
        connection.execute(
            "INSERT INTO radar_site_events (id, site_id, run_key, event_type, url, discovered_at) "
            "SELECT gen_random_uuid(), %s, 'site:test', "
            "CASE WHEN n %% 2 = 0 THEN 'added' ELSE 'removed' END, "
            "'https://site00.example.com/page-' || lpad(n::text, 4, '0'), %s "
            "FROM generate_series(0, 999) AS n",
            (site_id, NOW),
        )

    queries = ReadQueries(reader_dsn, schema=migrated_schema)
    first = queries.competitor_sites(FILTERS, page=1, limit=10)
    second = queries.competitor_sites(FILTERS, page=2, limit=10)
    changed = queries.competitor_sites({**FILTERS, "changed": "1"})
    searched = queries.competitor_sites({**FILTERS, "q": "Site 00"})
    events = queries.competitor_events(str(site_id), FILTERS, page=1, limit=50)
    next_events = queries.competitor_events(str(site_id), FILTERS, page=2, limit=50)
    added = queries.competitor_events(str(site_id), {**FILTERS, "type": "added"})
    path = queries.competitor_events(str(site_id), {**FILTERS, "q": "page-0001"})

    assert first["total"] == second["total"] == 20
    assert len(first["items"]) == len(second["items"]) == 10
    assert first["summary"]["added_urls"] == 500
    assert first["summary"]["removed_urls"] == 500
    assert type(first["summary"]["added_urls"]) is int
    assert type(first["summary"]["removed_urls"]) is int
    assert changed["total"] == 1 and changed["items"][0]["id"] == str(site_id)
    assert searched["total"] == 1
    assert events["total"] == 1000 and len(events["items"]) == 50
    assert next_events["total"] == 1000 and len(next_events["items"]) == 50
    assert added["total"] == 500
    assert path["total"] == 1 and path["items"][0]["path"] == "/page-0001"


def test_failed_and_baseline_states_distinct_and_settings_include_sources(test_dsn: str, migrated_schema: str, reader_dsn: str) -> None:
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(migrated_schema)))
        baseline = _site(connection, "Baseline", "baseline.example.com", version=1)
        failed = _site(connection, "Failed", "failed.example.com", version=2)
        untouched = _site(connection, "Untouched", "untouched.example.com")
        _run(connection, f"site:{baseline}", "ok", {"added": 0, "removed": 0, "url_count": 12})
        _run(connection, f"site:{failed}", "incomplete", {"reason": "missing shard"})
        for source, count in (("github:breakout", 17), ("hf:models", 100), ("hf:spaces", 100)):
            payload = {"repos": {str(n): [] for n in range(count)}} if source.startswith("github") else {"ids": list(range(count))}
            connection.execute(
                "INSERT INTO radar_source_state (source_instance, version, payload, last_success_at, updated_at) "
                "VALUES (%s, 2, %s, %s, %s)", (source, Jsonb(payload), NOW, NOW),
            )
            _run(connection, source, "ok", {"new_terms": 3})

    queries = ReadQueries(reader_dsn, schema=migrated_schema)
    page = queries.competitor_sites(FILTERS)
    by_name = {item["name"]: item for item in page["items"]}
    assert by_name["Baseline"]["status"] == "baseline"
    assert by_name["Failed"]["status"] == "incomplete"
    assert by_name["Untouched"]["status"] == "not_collected"
    assert by_name["Baseline"]["range_status"] == "ok"
    assert by_name["Failed"]["range_status"] == "incomplete"
    assert by_name["Untouched"]["range_status"] == "not_collected"
    assert page["summary"]["range_complete"] is False
    assert queries.competitor_sites({**FILTERS, "status": "incomplete"})["total"] == 1
    assert queries.competitor_events(str(baseline), FILTERS)["site"]["status"] == "baseline"
    assert queries.competitor_events(str(failed), FILTERS)["site"]["status"] == "incomplete"
    assert queries.competitor_events(str(untouched), FILTERS)["site"]["status"] == "not_collected"

    settings = queries.settings_status(NOW)
    sources = {item["source_instance"]: item for item in settings["sources"]}
    assert set(sources) == {"github:breakout", "hf:models", "hf:spaces"}
    assert [sources[name]["snapshot_items"] for name in ("github:breakout", "hf:models", "hf:spaces")] == [17, 100, 100]
    assert all(item["new_terms_last_run"] == 3 for item in sources.values())
    sites = {item["name"]: item for item in settings["sites"]}
    assert sites["Baseline"]["url_count"] == 12
    assert sites["Baseline"]["status"] == "baseline"
    assert sites["Failed"]["status"] == "incomplete"
    assert sites["Failed"]["last_run_reason"] == "missing shard"
    assert sites["Untouched"]["status"] == "not_collected"


def test_yesterday_success_is_not_todays_zero_change(
    test_dsn: str, migrated_schema: str, reader_dsn: str
) -> None:
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(migrated_schema)))
        site_id = _site(connection, "Yesterday", "yesterday.example.com", version=2)
        _run(connection, f"site:{site_id}", "ok", at=NOW - timedelta(days=1))

    queries = ReadQueries(reader_dsn, schema=migrated_schema)
    page = queries.competitor_sites(FILTERS)
    detail = queries.competitor_events(str(site_id), FILTERS)
    assert page["items"][0]["range_status"] == "not_collected"
    assert page["summary"]["range_complete"] is False
    assert detail["site"]["range_status"] == "not_collected"
    assert detail["total"] == 0
    uncollected = queries.competitor_sites({**FILTERS, "status": "not_collected"})
    assert uncollected["total"] == 1
    assert uncollected["items"][0]["id"] == str(site_id)


def test_pausing_after_todays_attempt_keeps_todays_coverage(
    test_dsn: str, migrated_schema: str, reader_dsn: str
) -> None:
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(migrated_schema)))
        successful = _site(connection, "Paused OK", "paused-ok.example.com", version=2, enabled=False)
        failed = _site(connection, "Paused failed", "paused-failed.example.com", version=2, enabled=False)
        _run(connection, f"site:{successful}", "ok")
        _run(connection, f"site:{failed}", "failed")

    queries = ReadQueries(reader_dsn, schema=migrated_schema)
    page = queries.competitor_sites(FILTERS)
    by_name = {item["name"]: item for item in page["items"]}
    assert by_name["Paused OK"]["range_status"] == "ok"
    assert by_name["Paused failed"]["range_status"] == "failed"
    assert page["summary"]["range_complete"] is False
    assert queries.competitor_events(str(successful), FILTERS)["site"]["range_status"] == "ok"


def test_multi_day_range_requires_each_beijing_day_to_be_collected(
    test_dsn: str, migrated_schema: str, reader_dsn: str
) -> None:
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(migrated_schema)))
        site_id = _site(connection, "Sparse", "sparse.example.com", version=2)
        connection.execute(
            "UPDATE radar_sites SET created_at = %s WHERE id = %s",
            (NOW - timedelta(days=6), site_id),
        )
        _run(connection, f"site:{site_id}", "ok")

    queries = ReadQueries(reader_dsn, schema=migrated_schema)
    filters = {"from": "2026-10-15", "to": "2026-10-21"}
    page = queries.competitor_sites(filters)
    detail = queries.competitor_events(str(site_id), filters)
    assert page["items"][0]["range_status"] == "partial"
    assert page["summary"]["range_complete"] is False
    assert detail["site"]["range_status"] == "partial"
    assert queries.competitor_sites({**filters, "status": "partial"})["total"] == 1
