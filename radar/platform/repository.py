from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from .db import connect, validate_schema_name
from .models import CollectionResult, Lease, SourceSnapshot


class RepositoryError(RuntimeError):
    pass


class LeaseLost(RepositoryError):
    pass


class SourceVersionConflict(RepositoryError):
    pass


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")


class Repository:
    def __init__(self, dsn: str, *, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = validate_schema_name(schema)

    def enqueue(self, job_key: str, task: str, due_at: datetime, payload: dict[str, Any]) -> bool:
        _aware(due_at, "due_at")
        with connect(self.dsn, schema=self.schema) as connection:
            cursor = connection.execute(
                """
                INSERT INTO radar_jobs (job_key, task, payload, scheduled_for)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (job_key) DO NOTHING
                """,
                (job_key, task, Jsonb(payload), due_at),
            )
            return cursor.rowcount == 1

    def claim_due(self, now: datetime, *, limit: int = 1, lease_seconds: int = 300) -> list[Lease]:
        _aware(now, "now")
        if limit <= 0 or lease_seconds <= 0:
            raise ValueError("limit and lease_seconds must be positive")
        token = uuid.uuid4()
        with connect(self.dsn, schema=self.schema) as connection:
            rows = connection.execute(
                """
                WITH due AS (
                    SELECT job_key
                    FROM radar_jobs
                    WHERE scheduled_for <= %(now)s
                      AND (
                        status = 'pending'
                        OR (status = 'leased' AND lease_expires_at <= %(now)s)
                      )
                    ORDER BY scheduled_for, job_key
                    FOR UPDATE SKIP LOCKED
                    LIMIT %(limit)s
                )
                UPDATE radar_jobs AS jobs
                SET status = 'leased',
                    lease_token = %(token)s,
                    lease_expires_at = %(now)s + make_interval(secs => %(lease_seconds)s),
                    attempts = attempts + 1,
                    updated_at = %(now)s
                FROM due
                WHERE jobs.job_key = due.job_key
                RETURNING jobs.job_key, jobs.lease_token, jobs.task, jobs.payload, jobs.scheduled_for
                """,
                {"now": now, "limit": limit, "token": token, "lease_seconds": lease_seconds},
            ).fetchall()
        return [
            Lease(
                job_key=row["job_key"],
                lease_token=str(row["lease_token"]),
                task=row["task"],
                payload=row["payload"],
                scheduled_for=row["scheduled_for"],
            )
            for row in rows
        ]

    @staticmethod
    def _assert_lease(row: dict[str, Any] | None, lease: Lease, now: datetime) -> None:
        if row is None or row["status"] != "leased" or str(row["lease_token"]) != lease.lease_token:
            raise LeaseLost(f"lease is no longer active for {lease.job_key}")
        if row["lease_expires_at"] <= now:
            raise LeaseLost(f"lease expired for {lease.job_key}")

    def commit_source(
        self,
        lease: Lease,
        result: CollectionResult,
        *,
        expected_version: int,
        now: datetime,
    ) -> dict[str, int]:
        _aware(now, "now")
        if result.status not in {"ok", "baseline"} or result.next_snapshot is None:
            raise RepositoryError("only complete ok/baseline results can advance source state")
        source_instance = lease.payload.get("source_instance")
        if not isinstance(source_instance, str) or not source_instance:
            if result.observations:
                source_instance = result.observations[0].source_instance
            else:
                raise RepositoryError("source_instance is required in the lease payload")
        if any(event.source_instance != source_instance for event in result.observations):
            raise RepositoryError("all observations must belong to the leased source")

        observations = 0
        new_terms = 0
        with connect(self.dsn, schema=self.schema) as connection:
            job = connection.execute(
                "SELECT status, lease_token, lease_expires_at FROM radar_jobs WHERE job_key = %s FOR UPDATE",
                (lease.job_key,),
            ).fetchone()
            self._assert_lease(job, lease, now)

            state = connection.execute(
                "SELECT version FROM radar_source_state WHERE source_instance = %s FOR UPDATE",
                (source_instance,),
            ).fetchone()
            current_version = 0 if state is None else int(state["version"])
            if current_version != expected_version:
                raise SourceVersionConflict(
                    f"source {source_instance} expected version {expected_version}, found {current_version}"
                )

            for event in result.observations:
                term = connection.execute(
                    "SELECT id FROM radar_terms WHERE canonical_key = %s",
                    (event.entity_key,),
                ).fetchone()
                if term is None and not event.is_discovery:
                    continue
                if term is None:
                    term_id = uuid.uuid4()
                    connection.execute(
                        """
                        INSERT INTO radar_terms
                            (id, canonical_key, name, kind, language, first_seen_at, last_seen_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            term_id,
                            event.entity_key,
                            event.name,
                            event.kind,
                            event.language,
                            event.observed_at,
                            event.observed_at,
                        ),
                    )
                    new_terms += 1
                else:
                    term_id = term["id"]
                    connection.execute(
                        """
                        UPDATE radar_terms
                        SET name = %s, last_seen_at = GREATEST(last_seen_at, %s)
                        WHERE id = %s
                        """,
                        (event.name, event.observed_at, term_id),
                    )
                slot = str(event.data_window.get("slot") or lease.scheduled_for.isoformat())
                inserted = connection.execute(
                    """
                    INSERT INTO radar_evidence
                        (id, term_id, source_instance, external_id, entity_key, slot, url, excerpt,
                         observed_at, data_window, metrics, content_hash, is_discovery)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_instance, external_id, slot, term_id) DO NOTHING
                    """,
                    (
                        uuid.uuid4(),
                        term_id,
                        event.source_instance,
                        event.external_id,
                        event.entity_key,
                        slot,
                        event.url,
                        event.excerpt,
                        event.observed_at,
                        Jsonb(event.data_window),
                        Jsonb(event.metrics),
                        event.content_hash,
                        event.is_discovery,
                    ),
                )
                observations += inserted.rowcount

            next_version = current_version + 1
            connection.execute(
                """
                INSERT INTO radar_source_state (source_instance, version, payload, last_success_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_instance) DO UPDATE
                SET version = EXCLUDED.version,
                    payload = EXCLUDED.payload,
                    last_success_at = EXCLUDED.last_success_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (source_instance, next_version, Jsonb(result.next_snapshot), now, now),
            )
            summary = {"observations": observations, "new_terms": new_terms, "source_version": next_version}
            connection.execute(
                """
                INSERT INTO radar_runs
                    (id, job_key, lease_token, source_instance, status, result, started_at, finished_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    lease.job_key,
                    lease.lease_token,
                    source_instance,
                    result.status,
                    Jsonb({**summary, "coverage": result.coverage}),
                    lease.scheduled_for,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE radar_jobs
                SET status = 'complete', result = %s, error = NULL,
                    lease_token = NULL, lease_expires_at = NULL, updated_at = %s
                WHERE job_key = %s
                """,
                (Jsonb(summary), now, lease.job_key),
            )
        return summary

    def finish_job(self, lease: Lease, result: dict[str, Any], now: datetime) -> None:
        _aware(now, "now")
        status = str(result.get("status", "ok"))
        if status not in {"ok", "off", "incomplete", "skipped"}:
            raise ValueError(f"invalid finished job status: {status}")
        with connect(self.dsn, schema=self.schema) as connection:
            row = connection.execute(
                "SELECT status, lease_token, lease_expires_at FROM radar_jobs WHERE job_key = %s FOR UPDATE",
                (lease.job_key,),
            ).fetchone()
            self._assert_lease(row, lease, now)
            connection.execute(
                """
                INSERT INTO radar_runs
                    (id, job_key, lease_token, source_instance, status, result, started_at, finished_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    lease.job_key,
                    lease.lease_token,
                    lease.payload.get("source_instance"),
                    status,
                    Jsonb(result),
                    lease.scheduled_for,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE radar_jobs
                SET status = 'complete', result = %s, error = NULL,
                    lease_token = NULL, lease_expires_at = NULL, updated_at = %s
                WHERE job_key = %s
                """,
                (Jsonb(result), now, lease.job_key),
            )

    def fail_job(
        self,
        lease: Lease,
        error: dict[str, Any],
        retry_at: datetime | None,
        now: datetime,
    ) -> None:
        _aware(now, "now")
        if retry_at is not None:
            _aware(retry_at, "retry_at")
        with connect(self.dsn, schema=self.schema) as connection:
            row = connection.execute(
                "SELECT status, lease_token, lease_expires_at FROM radar_jobs WHERE job_key = %s FOR UPDATE",
                (lease.job_key,),
            ).fetchone()
            self._assert_lease(row, lease, now)
            connection.execute(
                """
                INSERT INTO radar_runs
                    (id, job_key, lease_token, source_instance, status, error, started_at, finished_at)
                VALUES (%s, %s, %s, %s, 'failed', %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    lease.job_key,
                    lease.lease_token,
                    lease.payload.get("source_instance"),
                    Jsonb(error),
                    lease.scheduled_for,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE radar_jobs
                SET status = %s, error = %s, scheduled_for = COALESCE(%s, scheduled_for),
                    lease_token = NULL, lease_expires_at = NULL, updated_at = %s
                WHERE job_key = %s
                """,
                ("pending" if retry_at is not None else "failed", Jsonb(error), retry_at, now, lease.job_key),
            )

    def get_source_state(self, source_instance: str) -> SourceSnapshot:
        with connect(self.dsn, schema=self.schema) as connection:
            row = connection.execute(
                "SELECT version, payload, last_success_at FROM radar_source_state WHERE source_instance = %s",
                (source_instance,),
            ).fetchone()
        if row is None:
            return SourceSnapshot(version=0, payload={}, last_success_at=None)
        return SourceSnapshot(
            version=int(row["version"]),
            payload=row["payload"],
            last_success_at=row["last_success_at"],
        )
