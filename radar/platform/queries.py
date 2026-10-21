from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .db import connect, validate_schema_name
from .schedule import SOURCE_INSTANCES


BEIJING = ZoneInfo("Asia/Shanghai")


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


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError("day must be a calendar date")
    start = datetime.combine(day, time.min, tzinfo=BEIJING).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=BEIJING).astimezone(timezone.utc)
    return start, end


def _site_range(filters: dict[str, str]) -> tuple[datetime, datetime]:
    today = datetime.now(timezone.utc).astimezone(BEIJING).date()
    try:
        from_day = date.fromisoformat(filters.get("from", today.isoformat()))
        to_day = date.fromisoformat(filters.get("to", today.isoformat()))
    except ValueError as exc:
        raise ValueError("invalid date range") from exc
    if from_day > to_day or to_day > today or (to_day - from_day).days > 90:
        raise ValueError("invalid date range")
    start, _ = _day_bounds(from_day)
    _, end = _day_bounds(to_day)
    return start, end


def _site_status(item: dict[str, Any], now: datetime) -> str:
    if not item["enabled"]:
        return "paused"
    if item["last_run_status"] in {"failed", "incomplete"}:
        return item["last_run_status"]
    if item["version"] is None:
        return "not_collected"
    if item["version"] == 1:
        return "baseline"
    if item["last_success_at"] < now - timedelta(hours=48):
        return "stale"
    return "ok"


class ReadQueries:
    def __init__(self, dsn: str, *, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = validate_schema_name(schema)

    def overview(self, day: date | datetime, now: datetime | None = None) -> dict[str, Any]:
        if now is None and isinstance(day, datetime):
            now = day
            day = now.astimezone(BEIJING).date()
        if now is None:
            raise ValueError("now is required")
        _aware(now)
        if day > now.astimezone(BEIJING).date():
            raise ValueError("future date is not allowed")
        day_start, day_end = _day_bounds(day)
        historical = day < now.astimezone(BEIJING).date()
        with connect(self.dsn, schema=self.schema) as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM radar_terms
                     WHERE first_seen_at >= %(day_start)s AND first_seen_at < %(day_end)s) AS new_terms,
                    (SELECT count(*) FROM radar_evidence
                     WHERE observed_at >= %(day_start)s AND observed_at < %(day_end)s) AS evidence,
                    (SELECT count(DISTINCT site_id) FROM radar_site_events
                     WHERE discovered_at >= %(day_start)s AND discovered_at < %(day_end)s) AS changed_sites,
                    (SELECT count(*) FROM radar_site_events
                     WHERE event_type = 'added' AND discovered_at >= %(day_start)s
                       AND discovered_at < %(day_end)s) AS added_urls,
                    (SELECT count(*) FROM radar_site_events
                     WHERE event_type = 'removed' AND discovered_at >= %(day_start)s
                       AND discovered_at < %(day_end)s) AS removed_urls,
                    (SELECT count(DISTINCT source_instance) = cardinality(%(source_instances)s::text[])
                     FROM radar_runs
                     WHERE source_instance = ANY(%(source_instances)s::text[])
                       AND status IN ('ok', 'baseline')
                       AND finished_at >= %(day_start)s AND finished_at < %(day_end)s) AS sources_collected,
                    (EXISTS(SELECT 1 FROM radar_sites AS sites
                            WHERE sites.created_at < %(day_end)s
                              AND (sites.enabled OR %(historical)s OR EXISTS (
                                  SELECT 1 FROM radar_runs AS attempted
                                  WHERE attempted.source_instance = 'site:' || sites.id::text
                                    AND attempted.finished_at >= %(day_start)s
                                    AND attempted.finished_at < %(day_end)s)))
                     AND NOT EXISTS(
                         SELECT 1 FROM radar_sites AS sites
                         WHERE sites.created_at < %(day_end)s
                           AND (sites.enabled OR %(historical)s OR EXISTS (
                               SELECT 1 FROM radar_runs AS attempted
                               WHERE attempted.source_instance = 'site:' || sites.id::text
                                 AND attempted.finished_at >= %(day_start)s
                                 AND attempted.finished_at < %(day_end)s))
                           AND NOT EXISTS(
                               SELECT 1 FROM radar_runs AS runs
                               WHERE runs.source_instance = 'site:' || sites.id::text
                                 AND runs.status = 'ok'
                                 AND runs.finished_at >= %(day_start)s
                                 AND runs.finished_at < %(day_end)s
                           )
                     )) AS sites_collected,
                    (SELECT count(*) FROM radar_source_state) AS source_count,
                    (SELECT max(finished_at) FROM radar_runs) AS latest_run_at,
                    (SELECT count(*) FROM radar_jobs
                     WHERE status = 'pending' AND task LIKE 'check%%') AS pending_checks,
                    (SELECT count(*) FROM radar_runs
                     WHERE status = 'failed' AND finished_at >= %(day_start)s
                       AND finished_at < %(day_end)s) AS failed_runs_today
                """,
                {"day_start": day_start, "day_end": day_end,
                 "historical": historical, "source_instances": list(SOURCE_INSTANCES)},
            ).fetchone()
        result = dict(row)
        result["date"] = day.isoformat()
        if not result.pop("sources_collected"):
            result["new_terms"] = None
            result["evidence"] = None
        if not result.pop("sites_collected"):
            result["changed_sites"] = None
            result["added_urls"] = None
            result["removed_urls"] = None
        result["new_terms_today"] = result["new_terms"]
        result["evidence_today"] = result["evidence"]
        return _jsonable(result)

    def daily_terms(self, day: date, *, cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        day_start, day_end = _day_bounds(day)
        where_params: list[Any] = [day_start, day_end]
        cursor_clause = ""
        if cursor:
            seen_at, term_id = _cursor_decode(cursor)
            cursor_clause = "AND (terms.first_seen_at, terms.id) < (%s, %s)"
            where_params.extend([seen_at, term_id])
        statement = f"""
            SELECT terms.id, terms.name, terms.kind, terms.language,
                   terms.first_seen_at, terms.last_seen_at,
                   COALESCE((
                       SELECT array_agg(DISTINCT evidence.source_instance ORDER BY evidence.source_instance)
                       FROM radar_evidence AS evidence
                       WHERE evidence.term_id = terms.id
                         AND evidence.observed_at >= %s AND evidence.observed_at < %s
                   ), ARRAY[]::text[]) AS sources,
                   (SELECT count(*) FROM radar_evidence AS evidence
                    WHERE evidence.term_id = terms.id
                      AND evidence.observed_at >= %s AND evidence.observed_at < %s) AS evidence_count,
                   latest.source_instance, latest.url, latest.observed_at AS discovered_at
            FROM radar_terms AS terms
            LEFT JOIN LATERAL (
                SELECT source_instance, url, observed_at
                FROM radar_evidence
                WHERE term_id = terms.id AND observed_at >= %s AND observed_at < %s
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
            ) AS latest ON TRUE
            WHERE terms.first_seen_at >= %s AND terms.first_seen_at < %s
              {cursor_clause}
            ORDER BY terms.first_seen_at DESC, terms.id DESC
            LIMIT %s
        """
        params = [day_start, day_end] * 3 + where_params + [limit + 1]
        with connect(self.dsn, schema=self.schema) as connection:
            rows = connection.execute(statement, params).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = _cursor_encode(page[-1]["first_seen_at"], page[-1]["id"]) if has_more and page else None
        return {
            "date": day.isoformat(),
            "items": _jsonable([dict(row) for row in page]),
            "next_cursor": next_cursor,
            "summary": self.daily_source_status(day, datetime.now(timezone.utc)),
        }

    def daily_source_status(self, day: date, now: datetime) -> dict[str, Any]:
        _aware(now)
        day_start, day_end = _day_bounds(day)
        with connect(self.dsn, schema=self.schema) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (source_instance) source_instance, status, finished_at
                FROM radar_runs
                WHERE source_instance = ANY(%s::text[])
                  AND finished_at >= %s AND finished_at < %s
                ORDER BY source_instance, finished_at DESC, id DESC
                """,
                (list(SOURCE_INSTANCES), day_start, day_end),
            ).fetchall()
            latest_success = connection.execute(
                """
                SELECT max(finished_at) AS last_success_at
                FROM radar_runs
                WHERE source_instance = ANY(%s::text[])
                  AND status IN ('ok', 'baseline')
                  AND finished_at >= %s AND finished_at < %s
                """,
                (list(SOURCE_INSTANCES), day_start, day_end),
            ).fetchone()["last_success_at"]
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM radar_terms
                     WHERE first_seen_at >= %s AND first_seen_at < %s) AS new_terms,
                    (SELECT count(*) FROM radar_evidence
                     WHERE observed_at >= %s AND observed_at < %s) AS evidence
                """,
                (day_start, day_end, day_start, day_end),
            ).fetchone()
        statuses = {row["source_instance"]: row["status"] for row in rows}
        successes = sum(value in {"ok", "baseline"} for value in statuses.values())
        if not rows:
            status = "not_collected"
        elif successes == len(SOURCE_INSTANCES):
            status = "ok"
        elif successes == 0:
            status = "failed"
        else:
            status = "partial"
        return _jsonable({
            "date": day.isoformat(), "status": status,
            "new_terms": counts["new_terms"] if successes else None,
            "evidence": counts["evidence"] if successes else None,
            "last_success_at": latest_success,
            "sources": statuses,
        })

    def competitor_sites(
        self, filters: dict[str, str], *, page: int = 1, limit: int = 20
    ) -> dict[str, Any]:
        if page < 1 or not 1 <= limit <= 100:
            raise ValueError("invalid page or limit")
        start, end = _site_range(filters)
        from_day = start.astimezone(BEIJING).date()
        to_day = (end - timedelta(microseconds=1)).astimezone(BEIJING).date()
        today = datetime.now(timezone.utc).astimezone(BEIJING).date()
        changed = filters.get("changed")
        if changed not in {None, "1", "true"}:
            raise ValueError("invalid changed filter")
        status = filters.get("status")
        if status and status not in {"paused", "not_collected", "baseline", "ok", "failed", "incomplete", "stale", "partial"}:
            raise ValueError("invalid site status")
        conditions = []
        where_params: list[Any] = []
        q = filters.get("q", "").strip()[:100]
        if q:
            conditions.append("(name ILIKE %s OR host ILIKE %s)")
            where_params.extend([f"%{q}%", f"%{q}%"])
        if changed:
            conditions.append("(added_urls + removed_urls) > 0")
        if status:
            conditions.append("(CASE WHEN status = 'paused' THEN status "
                              "WHEN range_status = 'ok' THEN status ELSE range_status END) = %s")
            where_params.append(status)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        base = """
            WITH event_counts AS (
                SELECT site_id,
                       count(*) FILTER (WHERE event_type = 'added') AS added_urls,
                       count(*) FILTER (WHERE event_type = 'removed') AS removed_urls,
                       max(discovered_at) AS latest_change_at
                FROM radar_site_events
                WHERE discovered_at >= %s AND discovered_at < %s
                GROUP BY site_id
            ), base AS (
                SELECT sites.id, sites.name, sites.host, sites.homepage_url,
                       sites.sitemap_url, sites.enabled,
                       state.version, state.url_count, state.last_success_at,
                       latest.status AS last_run_status, latest.finished_at AS last_attempt_at,
                       latest.result AS last_run_result,
                       coverage.expected_days, coverage.covered_days,
                       CASE
                         WHEN coverage.expected_days = 0 THEN 'not_collected'
                         WHEN coverage.covered_days = coverage.expected_days THEN 'ok'
                         WHEN period.status IN ('failed', 'incomplete') THEN period.status
                         WHEN coverage.covered_days > 0 THEN 'partial'
                         ELSE 'not_collected'
                       END AS range_status,
                       COALESCE(events.added_urls, 0) AS added_urls,
                       COALESCE(events.removed_urls, 0) AS removed_urls,
                       events.latest_change_at,
                       CASE
                         WHEN NOT sites.enabled THEN 'paused'
                         WHEN latest.status IN ('failed', 'incomplete') THEN latest.status
                         WHEN state.version IS NULL THEN 'not_collected'
                         WHEN state.version = 1 THEN 'baseline'
                         WHEN state.last_success_at < %s THEN 'stale'
                         ELSE 'ok'
                       END AS status
                FROM radar_sites AS sites
                LEFT JOIN radar_site_state AS state ON state.site_id = sites.id
                LEFT JOIN event_counts AS events ON events.site_id = sites.id
                LEFT JOIN LATERAL (
                    SELECT status, finished_at, result
                    FROM radar_runs
                    WHERE source_instance = 'site:' || sites.id::text
                    ORDER BY finished_at DESC, id DESC LIMIT 1
                ) AS latest ON TRUE
                LEFT JOIN LATERAL (
                    SELECT status FROM radar_runs
                    WHERE source_instance = 'site:' || sites.id::text
                      AND finished_at >= %s AND finished_at < %s
                    ORDER BY finished_at DESC, id DESC LIMIT 1
                ) AS period ON TRUE
                LEFT JOIN LATERAL (
                    SELECT count(*) AS expected_days,
                           count(*) FILTER (WHERE daily.was_collected) AS covered_days
                    FROM generate_series(%s::date, %s::date, interval '1 day') AS days(day_at)
                    LEFT JOIN LATERAL (
                        SELECT EXISTS (
                            SELECT 1 FROM radar_runs AS runs
                            WHERE runs.source_instance = 'site:' || sites.id::text
                              AND runs.status = 'ok'
                              AND runs.finished_at >= (days.day_at::date::timestamp AT TIME ZONE 'Asia/Shanghai')
                              AND runs.finished_at < ((days.day_at::date + 1)::timestamp AT TIME ZONE 'Asia/Shanghai')
                        ) AS was_collected,
                        EXISTS (
                            SELECT 1 FROM radar_runs AS attempted
                            WHERE attempted.source_instance = 'site:' || sites.id::text
                              AND attempted.finished_at >= (days.day_at::date::timestamp AT TIME ZONE 'Asia/Shanghai')
                              AND attempted.finished_at < ((days.day_at::date + 1)::timestamp AT TIME ZONE 'Asia/Shanghai')
                        ) AS was_attempted
                    ) AS daily ON TRUE
                    WHERE days.day_at::date >= (sites.created_at AT TIME ZONE 'Asia/Shanghai')::date
                      AND (days.day_at::date < %s::date OR sites.enabled OR daily.was_attempted)
                ) AS coverage ON TRUE
            )
        """
        params = [start, end, datetime.now(timezone.utc) - timedelta(hours=48),
                  start, end, from_day, to_day, today] + where_params
        with connect(self.dsn, schema=self.schema) as connection:
            totals = connection.execute(
                base + f"""
                SELECT count(*) AS sites,
                       COALESCE(sum(added_urls), 0)::bigint AS added_urls,
                       COALESCE(sum(removed_urls), 0)::bigint AS removed_urls,
                       count(*) FILTER (WHERE status IN ('failed', 'incomplete', 'stale')) AS abnormal_sites,
                       (count(*) FILTER (WHERE expected_days > 0) > 0 AND
                        COALESCE(bool_and(expected_days = 0 OR covered_days = expected_days), FALSE)) AS range_complete
                FROM base {where}
                """,
                params,
            ).fetchone()
            rows = connection.execute(
                base + f"""
                SELECT * FROM base {where}
                ORDER BY latest_change_at DESC NULLS LAST, name, id
                LIMIT %s OFFSET %s
                """,
                params + [limit, (page - 1) * limit],
            ).fetchall()
        return {
            "items": _jsonable([dict(row) for row in rows]),
            "total": totals["sites"],
            "summary": _jsonable(dict(totals)),
            "page": page,
            "page_size": limit,
        }

    def competitor_events(
        self, site_id: str, filters: dict[str, str], *, page: int = 1, limit: int = 50
    ) -> dict[str, Any]:
        if page < 1 or not 1 <= limit <= 100:
            raise ValueError("invalid page or limit")
        try:
            parsed_id = uuid.UUID(site_id)
        except ValueError as exc:
            raise ValueError("invalid site ID") from exc
        start, end = _site_range(filters)
        from_day = start.astimezone(BEIJING).date()
        to_day = (end - timedelta(microseconds=1)).astimezone(BEIJING).date()
        today = datetime.now(timezone.utc).astimezone(BEIJING).date()
        event_type = filters.get("type", "all")
        if event_type not in {"all", "added", "removed"}:
            raise ValueError("invalid event type")
        clauses = ["site_id = %s", "discovered_at >= %s", "discovered_at < %s"]
        params: list[Any] = [parsed_id, start, end]
        if event_type != "all":
            clauses.append("event_type = %s")
            params.append(event_type)
        q = filters.get("q", "").strip()[:100]
        if q:
            clauses.append("url ILIKE %s")
            params.append(f"%{q}%")
        where = " AND ".join(clauses)
        with connect(self.dsn, schema=self.schema) as connection:
            site = connection.execute(
                """
                SELECT sites.id, sites.name, sites.host, sites.enabled, sites.created_at,
                       state.version, state.url_count, state.last_success_at,
                       latest.status AS last_run_status, latest.finished_at AS last_attempt_at,
                       latest.result AS last_run_result, latest.error AS last_run_error
                FROM radar_sites AS sites
                LEFT JOIN radar_site_state AS state ON state.site_id = sites.id
                LEFT JOIN LATERAL (
                    SELECT status, finished_at, result, error
                    FROM radar_runs
                    WHERE source_instance = 'site:' || sites.id::text
                    ORDER BY finished_at DESC, id DESC LIMIT 1
                ) AS latest ON TRUE
                WHERE sites.id = %s
                """, (parsed_id,)
            ).fetchone()
            if site is None:
                raise ValueError("unknown site")
            coverage = connection.execute(
                """
                SELECT count(*) AS expected_days,
                       count(*) FILTER (WHERE daily.was_collected) AS covered_days
                FROM generate_series(%s::date, %s::date, interval '1 day') AS days(day_at)
                LEFT JOIN LATERAL (
                    SELECT EXISTS (
                        SELECT 1 FROM radar_runs AS runs
                        WHERE runs.source_instance = %s
                          AND runs.status = 'ok'
                          AND runs.finished_at >= (days.day_at::date::timestamp AT TIME ZONE 'Asia/Shanghai')
                          AND runs.finished_at < ((days.day_at::date + 1)::timestamp AT TIME ZONE 'Asia/Shanghai')
                    ) AS was_collected,
                    EXISTS (
                        SELECT 1 FROM radar_runs AS attempted
                        WHERE attempted.source_instance = %s
                          AND attempted.finished_at >= (days.day_at::date::timestamp AT TIME ZONE 'Asia/Shanghai')
                          AND attempted.finished_at < ((days.day_at::date + 1)::timestamp AT TIME ZONE 'Asia/Shanghai')
                    ) AS was_attempted
                ) AS daily ON TRUE
                WHERE days.day_at::date >= %s::date
                  AND (days.day_at::date < %s::date OR %s OR daily.was_attempted)
                """, (from_day, to_day, f"site:{parsed_id}", f"site:{parsed_id}",
                      site["created_at"].astimezone(BEIJING).date(), today, site["enabled"]),
            ).fetchone()
            period = connection.execute(
                """
                SELECT status FROM radar_runs
                WHERE source_instance = %s AND finished_at >= %s AND finished_at < %s
                ORDER BY finished_at DESC, id DESC LIMIT 1
                """, (f"site:{parsed_id}", start, end),
            ).fetchone()
            total = connection.execute(
                f"SELECT count(*) AS total FROM radar_site_events WHERE {where}", params
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT id, event_type, url, discovered_at
                FROM radar_site_events WHERE {where}
                ORDER BY discovered_at DESC, id ASC
                LIMIT %s OFFSET %s
                """,
                params + [limit, (page - 1) * limit],
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            parsed = urlsplit(item["url"])
            item["path"] = parsed.path or "/"
            items.append(item)
        site_item = dict(site)
        result = site_item.pop("last_run_result") or {}
        run_error = site_item.pop("last_run_error") or {}
        site_item["status"] = _site_status(site_item, datetime.now(timezone.utc))
        if coverage["expected_days"] == 0:
            site_item["range_status"] = "not_collected"
        elif coverage["covered_days"] == coverage["expected_days"]:
            site_item["range_status"] = "ok"
        elif period and period["status"] in {"failed", "incomplete"}:
            site_item["range_status"] = period["status"]
        elif coverage["covered_days"]:
            site_item["range_status"] = "partial"
        else:
            site_item["range_status"] = "not_collected"
        site_item["last_run_reason"] = result.get("reason") or run_error.get("message")
        return {
            "site": _jsonable(site_item),
            "items": _jsonable(items),
            "total": total,
            "page": page,
            "page_size": limit,
        }

    def settings_status(self, now: datetime) -> dict[str, Any]:
        _aware(now)
        with connect(self.dsn, schema=self.schema) as connection:
            rows = connection.execute(
                """
                SELECT sites.id, sites.name, sites.host, sites.homepage_url,
                       sites.sitemap_url, sites.enabled, sites.created_at,
                       state.version, state.url_count, state.last_success_at,
                       latest.status AS last_run_status, latest.finished_at AS last_attempt_at,
                       latest.result AS last_run_result, latest.error AS last_run_error
                FROM radar_sites AS sites
                LEFT JOIN radar_site_state AS state ON state.site_id = sites.id
                LEFT JOIN LATERAL (
                    SELECT status, finished_at, result, error
                    FROM radar_runs
                    WHERE source_instance = 'site:' || sites.id::text
                    ORDER BY finished_at DESC, id DESC LIMIT 1
                ) AS latest ON TRUE
                ORDER BY sites.name, sites.id
                """
            ).fetchall()
        sites = []
        for row in rows:
            item = dict(row)
            result = item.pop("last_run_result") or {}
            run_error = item.get("last_run_error") or {}
            item["status"] = _site_status(item, now)
            item["added_last_run"] = result.get("added")
            item["removed_last_run"] = result.get("removed")
            item["last_run_reason"] = result.get("reason") or run_error.get("message")
            sites.append(_jsonable(item))
        sources = self.sources(now)
        for source in sources:
            result = source.get("run_result") or {}
            source["new_terms_last_run"] = result.get("new_terms")
        return {"sources": sources, "sites": sites}

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
                    SELECT unnest(%s::text[]) AS source_instance
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
                """,
                (list(SOURCE_INSTANCES),),
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
            if status in {"ok", "baseline"} and item.get("last_success_at") and (now - item["last_success_at"]).total_seconds() > 86400:
                status = "stale"
            item["status"] = status
            output.append(_jsonable(item))
        return output
