from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg import sql

from radar_platform.models import CollectionResult, EvidenceInput
from radar_platform.repository import LeaseLost, Repository


NOW = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)


def _event(*, observed_at: datetime, slot: str, external_id: str = "acme/radar") -> EvidenceInput:
    return EvidenceInput(
        source_instance="github:breakout",
        external_id=external_id,
        entity_key=f"name:github:breakout:{external_id}",
        name="Radar",
        kind="name",
        language="en",
        url=f"https://github.com/{external_id}",
        excerpt="Evidence-backed description",
        observed_at=observed_at,
        data_window={"slot": slot},
        metrics={"stars": 1000},
        content_hash=f"hash-{slot}",
        is_discovery=True,
    )


def _result(*, observed_at: datetime, slot: str, snapshot: dict | None = None) -> CollectionResult:
    return CollectionResult(
        status="ok",
        observations=[_event(observed_at=observed_at, slot=slot)],
        next_snapshot=snapshot if snapshot is not None else {"ids": ["acme/radar"]},
        coverage={"complete": True},
    )


def _claim(repository: Repository, *, job_key: str, now: datetime, lease_seconds: int = 300):
    assert repository.enqueue(job_key, "collect", now, {"source_instance": "github:breakout"})
    leases = repository.claim_due(now, limit=1, lease_seconds=lease_seconds)
    assert len(leases) == 1
    return leases[0]


def _counts(dsn: str, schema: str) -> dict[str, int]:
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        return {
            table: connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            for table in ("radar_terms", "radar_evidence", "radar_source_state", "radar_runs", "radar_jobs")
        }


def test_repeat_slot_does_not_duplicate(repository: Repository, test_dsn: str, migrated_schema: str) -> None:
    lease = _claim(repository, job_key="github:2026-10-15T00", now=NOW)
    first = repository.commit_source(lease, _result(observed_at=NOW, slot="2026-10-15T00"), expected_version=0, now=NOW)

    assert first == {"observations": 1, "new_terms": 1, "source_version": 1}
    assert repository.enqueue("github:2026-10-15T00", "collect", NOW, {}) is False
    with pytest.raises(LeaseLost):
        repository.commit_source(lease, _result(observed_at=NOW, slot="2026-10-15T00"), expected_version=0, now=NOW)
    assert _counts(test_dsn, migrated_schema) == {
        "radar_terms": 1,
        "radar_evidence": 1,
        "radar_source_state": 1,
        "radar_runs": 1,
        "radar_jobs": 1,
    }


def test_next_slot_keeps_observation(repository: Repository, test_dsn: str, migrated_schema: str) -> None:
    first = _claim(repository, job_key="github:slot-1", now=NOW)
    repository.commit_source(first, _result(observed_at=NOW, slot="slot-1"), expected_version=0, now=NOW)

    later = NOW + timedelta(hours=8)
    second = _claim(repository, job_key="github:slot-2", now=later)
    result = repository.commit_source(second, _result(observed_at=later, slot="slot-2"), expected_version=1, now=later)

    assert result == {"observations": 1, "new_terms": 0, "source_version": 2}
    counts = _counts(test_dsn, migrated_schema)
    assert counts["radar_terms"] == 1
    assert counts["radar_evidence"] == 2
    assert counts["radar_runs"] == 2


def test_failed_commit_keeps_previous_snapshot(repository: Repository, test_dsn: str, migrated_schema: str) -> None:
    first = _claim(repository, job_key="github:good", now=NOW)
    repository.commit_source(first, _result(observed_at=NOW, slot="good"), expected_version=0, now=NOW)

    later = NOW + timedelta(hours=8)
    second = _claim(repository, job_key="github:bad", now=later)
    bad = _result(observed_at=later, slot="bad", snapshot={"not_json": {"set"}})
    with pytest.raises((TypeError, psycopg.Error)):
        repository.commit_source(second, bad, expected_version=1, now=later)

    state = repository.get_source_state("github:breakout")
    assert state.version == 1
    assert state.payload == {"ids": ["acme/radar"]}
    counts = _counts(test_dsn, migrated_schema)
    assert counts["radar_terms"] == 1
    assert counts["radar_evidence"] == 1
    assert counts["radar_runs"] == 1


def test_two_workers_cannot_claim_same_job(repository: Repository, test_dsn: str, migrated_schema: str) -> None:
    other = Repository(test_dsn, schema=migrated_schema)
    assert repository.enqueue("github:one", "collect", NOW, {})

    first = repository.claim_due(NOW, limit=1)
    second = other.claim_due(NOW, limit=1)

    assert len(first) == 1
    assert second == []
    assert first[0].job_key == "github:one"


def test_expired_lease_cannot_commit(repository: Repository, test_dsn: str, migrated_schema: str) -> None:
    lease = _claim(repository, job_key="github:expired", now=NOW, lease_seconds=1)

    with pytest.raises(LeaseLost, match="expired"):
        repository.commit_source(
            lease,
            _result(observed_at=NOW, slot="expired"),
            expected_version=0,
            now=NOW + timedelta(seconds=2),
        )

    assert repository.get_source_state("github:breakout").version == 0
    counts = _counts(test_dsn, migrated_schema)
    assert counts["radar_terms"] == 0
    assert counts["radar_evidence"] == 0
    assert counts["radar_runs"] == 0


def test_baseline_without_discoveries_advances_only_source_state(
    repository: Repository,
    test_dsn: str,
    migrated_schema: str,
) -> None:
    lease = _claim(repository, job_key="hf:baseline", now=NOW)
    baseline = CollectionResult(
        status="baseline",
        observations=[],
        next_snapshot={"top": ["model/a", "model/b"]},
        coverage={"items": 2},
    )

    assert repository.commit_source(lease, baseline, expected_version=0, now=NOW) == {
        "observations": 0,
        "new_terms": 0,
        "source_version": 1,
    }
    counts = _counts(test_dsn, migrated_schema)
    assert counts["radar_terms"] == 0
    assert counts["radar_evidence"] == 0
    assert counts["radar_source_state"] == 1
    assert counts["radar_runs"] == 1


def test_failed_job_without_retry_is_not_reclaimed(repository: Repository) -> None:
    lease = _claim(repository, job_key="github:terminal-failure", now=NOW)
    repository.fail_job(lease, {"message": "permanent for this cycle"}, retry_at=None, now=NOW)

    assert repository.claim_due(NOW + timedelta(hours=1), limit=1) == []


def test_failed_job_is_reclaimed_only_when_retry_is_due(repository: Repository) -> None:
    lease = _claim(repository, job_key="github:retry", now=NOW)
    retry_at = NOW + timedelta(minutes=15)
    repository.fail_job(lease, {"message": "temporary"}, retry_at=retry_at, now=NOW)

    assert repository.claim_due(retry_at - timedelta(seconds=1), limit=1) == []
    retried = repository.claim_due(retry_at, limit=1)
    assert len(retried) == 1
    assert retried[0].job_key == "github:retry"
