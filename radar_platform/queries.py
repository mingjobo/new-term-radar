from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .db import connect, validate_schema_name


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must include a timezone")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _cursor_encode(seen_at: datetime, term_id: uuid.UUID) -> str:
    payload = json.dumps([seen_at.isoformat(), str(term_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _cursor_decode(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        seen_raw, id_raw = json.loads(base64.urlsafe_b64decode(value + padding))
        seen_at = datetime.fromisoformat(seen_raw)
        _aware(seen_at)
        return seen_at, uuid.UUID(id_raw)
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid cursor") from exc


def _since(value: str) -> datetime:
    try:
        if "T" in value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            _aware(parsed)
            return parsed
        return datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid since filter") from exc


class ReadQueries:
    def __init__(self, dsn: str, *, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = validate_schema_name(schema)

    def overview(self, now: datetime) -> dict[str, Any]:
        _aware(now)
        local = now.astimezone(ZoneInfo("Asia/Shanghai"))
        day_start = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo).astimezone(timezone.utc)
        with connect(self.dsn, schema=self.schema) as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM radar_terms WHERE first_seen_at >= %(day_start)s) AS new_terms_today,
                    (SELECT count(*) FROM radar_evidence WHERE observed_at >= %(day_start)s) AS evidence_today,
                    (SELECT count(*) FROM radar_source_state) AS source_count,
                    (SELECT max(finished_at) FROM radar_runs) AS latest_run_at,
                    (SELECT count(*) FROM radar_jobs
                     WHERE status = 'pending' AND task LIKE 'check%%') AS pending_checks,
                    (SELECT count(*) FROM radar_runs
                     WHERE status = 'failed' AND finished_at >= %(day_start)s) AS failed_runs_today
                """,
                {"day_start": day_start},
            ).fetchone()
        return _jsonable(dict(row))

    def terms(
        self,
        filters: dict[str, str],
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if filters.get("sort", "newest") != "newest":
            raise ValueError("unsupported sort")
        clauses: list[str] = []
        params: list[Any] = []
        source = filters.get("source")
        if source:
            clauses.append(
                "EXISTS (SELECT 1 FROM radar_evidence source_filter "
                "WHERE source_filter.term_id = terms.id AND source_filter.source_instance = %s)"
            )
            params.append(source)
        kind = filters.get("kind")
        if kind:
            if kind not in {"name", "generic", "unknown"}:
                raise ValueError("unsupported kind")
            clauses.append("terms.kind = %s")
            params.append(kind)
        query = filters.get("q")
        if query:
            clauses.append("terms.name ILIKE %s")
            params.append(f"%{query[:100]}%")
        since = filters.get("since")
        if since:
            clauses.append("terms.first_seen_at >= %s")
            params.append(_since(since))
        if cursor:
            seen_at, term_id = _cursor_decode(cursor)
            clauses.append("(terms.first_seen_at, terms.id) < (%s, %s)")
            params.extend([seen_at, term_id])
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit + 1)
        statement = f"""
            SELECT terms.id, terms.canonical_key, terms.name, terms.kind, terms.language,
                   terms.first_seen_at, terms.last_seen_at,
                   evidence.source_instance, evidence.url, evidence.excerpt,
                   evidence.observed_at, evidence.metrics
            FROM radar_terms AS terms
            LEFT JOIN LATERAL (
                SELECT source_instance, url, excerpt, observed_at, metrics
                FROM radar_evidence
                WHERE term_id = terms.id
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
            ) AS evidence ON TRUE
            {where}
            ORDER BY terms.first_seen_at DESC, terms.id DESC
            LIMIT %s
        """
        with connect(self.dsn, schema=self.schema) as connection:
            rows = connection.execute(statement, params).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = _cursor_encode(page[-1]["first_seen_at"], page[-1]["id"]) if has_more and page else None
        return {"items": _jsonable([dict(row) for row in page]), "next_cursor": next_cursor}

    def term(self, term_id: str) -> dict[str, Any] | None:
        try:
            parsed_id = uuid.UUID(term_id)
        except ValueError:
            return None
        with connect(self.dsn, schema=self.schema) as connection:
            term = connection.execute(
                """
                SELECT id, canonical_key, name, kind, language, first_seen_at, last_seen_at
                FROM radar_terms
                WHERE id = %s
                """,
                (parsed_id,),
            ).fetchone()
            if term is None:
                return None
            evidence = connection.execute(
                """
                SELECT id, source_instance, external_id, url, excerpt, observed_at,
                       data_window, metrics, content_hash, is_discovery
                FROM radar_evidence
                WHERE term_id = %s
                ORDER BY observed_at DESC, id DESC
                """,
                (parsed_id,),
            ).fetchall()
        result = dict(term)
        result["evidence"] = [dict(row) for row in evidence]
        return _jsonable(result)

    def sources(self, now: datetime) -> list[dict[str, Any]]:
        _aware(now)
        with connect(self.dsn, schema=self.schema) as connection:
            rows = connection.execute(
                """
                WITH instances AS (
                    SELECT source_instance FROM radar_source_state
                    UNION
                    SELECT source_instance FROM radar_runs WHERE source_instance IS NOT NULL
                )
                SELECT instances.source_instance, state.version, state.payload, state.last_success_at,
                       latest.status AS run_status, latest.finished_at AS last_run_at,
                       latest.result AS run_result, latest.error AS run_error
                FROM instances
                LEFT JOIN radar_source_state AS state USING (source_instance)
                LEFT JOIN LATERAL (
                    SELECT status, finished_at, result, error
                    FROM radar_runs
                    WHERE source_instance = instances.source_instance
                    ORDER BY finished_at DESC, id DESC
                    LIMIT 1
                ) AS latest ON TRUE
                ORDER BY instances.source_instance
                """
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            payload = item.pop("payload") or {}
            if isinstance(payload.get("ids"), list):
                item["snapshot_items"] = len(payload["ids"])
            elif isinstance(payload.get("repos"), dict):
                item["snapshot_items"] = len(payload["repos"])
            else:
                item["snapshot_items"] = 0
            status = item.pop("run_status") or ("ok" if item.get("last_success_at") else "not_run")
            if item.get("last_success_at") and (now - item["last_success_at"]).total_seconds() > 86400:
                status = "stale"
            item["status"] = status
            output.append(_jsonable(item))
        return output
