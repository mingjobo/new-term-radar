from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest
from psycopg import sql

from radar_platform.models import CollectionResult, EvidenceInput
from radar_platform.queries import ReadQueries


NOW = datetime(2026, 10, 15, 10, 31, tzinfo=timezone.utc)


def _seed(repository) -> str:
    assert repository.enqueue("web:seed", "collect", NOW, {"source_instance": "github:breakout"})
    lease = repository.claim_due(NOW)[0]
    event = EvidenceInput(
        source_instance="github:breakout",
        external_id="101",
        entity_key="name:github:breakout:101",
        name="Fast Radar",
        kind="name",
        language="en",
        url="https://github.com/Acme/Fast-Radar",
        excerpt="An evidence-backed radar for emerging tools",
        observed_at=NOW,
        data_window={"slot": "2026-10-15T08:00:00Z"},
        metrics={"stars": 1000, "velocity_per_day": 500},
        content_hash="hash",
        is_discovery=True,
    )
    repository.commit_source(
        lease,
        CollectionResult("ok", [event], {"repos": {"101": []}}, {"complete": True, "items": 1}),
        expected_version=0,
        now=NOW,
    )
    with psycopg.connect(repository.dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(repository.schema)))
        return str(connection.execute("SELECT id FROM radar_terms").fetchone()[0])


def test_reader_queries_visible_chain_and_database_rejects_write(
    repository,
    reader_dsn: str,
    migrated_schema: str,
) -> None:
    term_id = _seed(repository)
    queries = ReadQueries(reader_dsn, schema=migrated_schema)

    overview = queries.overview(NOW)
    page = queries.terms({"source": "github:breakout", "kind": "name", "sort": "newest"})
    detail = queries.term(term_id)
    sources = queries.sources(NOW)

    assert overview["new_terms_today"] == 1
    assert overview["evidence_today"] == 1
    assert page["items"][0]["name"] == "Fast Radar"
    assert page["items"][0]["url"] == "https://github.com/Acme/Fast-Radar"
    assert detail["evidence"][0]["metrics"]["stars"] == 1000
    assert sources[0]["source_instance"] == "github:breakout"
    assert sources[0]["status"] == "ok"

    with psycopg.connect(reader_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                sql.SQL("INSERT INTO {}.radar_jobs (job_key, task, payload, scheduled_for) "
                        "VALUES ('forbidden', 'collect', %s::jsonb, now())").format(
                    sql.Identifier(migrated_schema)
                ),
                ("{}",),
            )
