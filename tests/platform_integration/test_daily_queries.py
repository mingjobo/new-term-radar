from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from radar.platform.queries import ReadQueries


START = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)
OLD = START - timedelta(seconds=1)
NEW = START + timedelta(seconds=1)
NEXT = START + timedelta(days=1, seconds=1)
NOW = START + timedelta(days=4)


def _term(connection, name: str, seen_at: datetime) -> uuid.UUID:
    term_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO radar_terms (id, canonical_key, name, kind, language, first_seen_at, last_seen_at) "
        "VALUES (%s, %s, %s, 'name', 'en', %s, %s)",
        (term_id, f"name:{name.casefold()}", name, seen_at, seen_at),
    )
    return term_id


def _evidence(connection, term_id: uuid.UUID, source: str, seen_at: datetime) -> None:
    event_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO radar_evidence "
        "(id, term_id, source_instance, external_id, entity_key, slot, url, excerpt, "
        "observed_at, data_window, metrics, content_hash, is_discovery) "
        "VALUES (%s, %s, %s, %s, 'name:shared', %s, %s, 'A real clue', %s, %s, %s, 'hash', TRUE)",
        (
            event_id, term_id, source, str(event_id), seen_at.isoformat(),
            f"https://example.com/{source}", seen_at, Jsonb({"slot": seen_at.isoformat()}), Jsonb({}),
        ),
    )


def _run(connection, source: str, finished_at: datetime, status: str = "ok") -> None:
    key = f"test:{source}:{finished_at.isoformat()}"
    connection.execute(
        "INSERT INTO radar_jobs (job_key, task, payload, scheduled_for, status) "
        "VALUES (%s, 'test', %s, %s, 'complete')",
        (key, Jsonb({"source_instance": source}), finished_at, ),
    )
    connection.execute(
        "INSERT INTO radar_runs "
        "(id, job_key, lease_token, source_instance, status, result, started_at, finished_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (uuid.uuid4(), key, uuid.uuid4(), source, status, Jsonb({}), finished_at, finished_at),
    )


def test_overview_day_boundary_and_missing_state(test_dsn: str, migrated_schema: str, reader_dsn: str) -> None:
    site_id = uuid.uuid4()
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(migrated_schema)))
        old_id = _term(connection, "Old", OLD)
        new_id = _term(connection, "New", NEW)
        _evidence(connection, old_id, "github:breakout", OLD)
        _evidence(connection, new_id, "github:breakout", NEW)
        _evidence(connection, new_id, "hf:models", NEW + timedelta(seconds=1))
        connection.execute(
            "INSERT INTO radar_sites (id, name, homepage_url, host) "
            "VALUES (%s, 'Example', 'https://example.com/', 'example.com')", (site_id,)
        )
        for event_type, url in (("added", "https://example.com/a"), ("removed", "https://example.com/b")):
            connection.execute(
                "INSERT INTO radar_site_events (id, site_id, run_key, event_type, url, discovered_at) "
                "VALUES (%s, %s, 'site:test', %s, %s, %s)",
                (uuid.uuid4(), site_id, event_type, url, NEW),
            )
        _run(connection, "github:breakout", OLD)
        _run(connection, "github:breakout", NEW)
        _run(connection, "hf:models", NEW)
        _run(connection, f"site:{site_id}", NEW)
        _run(connection, "github:breakout", NEXT)
        _run(connection, f"site:{site_id}", NEXT)

    queries = ReadQueries(reader_dsn, schema=migrated_schema)
    before = queries.overview(date(2026, 10, 20), NOW)
    selected = queries.overview(date(2026, 10, 21), NOW)
    zero = queries.overview(date(2026, 10, 22), NOW)
    missing = queries.overview(date(2026, 10, 23), NOW)

    assert [before[key] for key in ("new_terms", "evidence", "changed_sites", "added_urls", "removed_urls")] == [1, 1, None, None, None]
    assert [selected[key] for key in ("new_terms", "evidence", "changed_sites", "added_urls", "removed_urls")] == [1, 2, 1, 1, 1]
    assert [zero[key] for key in ("new_terms", "evidence", "changed_sites", "added_urls", "removed_urls")] == [0, 0, 0, 0, 0]
    assert [missing[key] for key in ("new_terms", "evidence", "changed_sites", "added_urls", "removed_urls")] == [None] * 5


def test_daily_terms_merges_sources_per_first_seen_term_and_research_card_keeps_evidence(test_dsn: str, migrated_schema: str, reader_dsn: str) -> None:
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(migrated_schema)))
        older = _term(connection, "Shared", NEW)
        newer = _term(connection, "Another", NEW + timedelta(minutes=1))
        _evidence(connection, older, "github:breakout", NEW)
        _evidence(connection, older, "hf:models", NEW + timedelta(seconds=1))
        _evidence(connection, newer, "hf:spaces", NEW + timedelta(minutes=1))
        _run(connection, "github:breakout", NEW)
        _run(connection, "hf:models", NEW)
        _run(connection, "hf:spaces", NEW)

    queries = ReadQueries(reader_dsn, schema=migrated_schema)
    first = queries.daily_terms(date(2026, 10, 21), limit=1)
    second = queries.daily_terms(date(2026, 10, 21), cursor=first["next_cursor"], limit=1)
    shared = second["items"][0]

    assert first["items"][0]["name"] == "Another"
    assert shared["name"] == "Shared"
    assert shared["sources"] == ["github:breakout", "hf:models"]
    assert shared["evidence_count"] == 2
    assert second["next_cursor"] is None
    assert first["summary"]["status"] == "ok"
    assert first["summary"]["new_terms"] == 2
    assert first["summary"]["evidence"] == 3
    assert len(queries.term(str(older))["evidence"]) == 2
