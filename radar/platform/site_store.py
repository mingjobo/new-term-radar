"""Atomic, per-site sitemap snapshots and URL change events."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from .db import connect, validate_schema_name


class StaleSiteSnapshot(ValueError):
    pass


class SitePaused(ValueError):
    pass


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")


class SiteStore:
    def __init__(self, dsn: str, *, schema: str = "public") -> None:
        self.dsn = dsn
        self.schema = validate_schema_name(schema)

    def list_enabled_sites(self) -> list[dict]:
        with connect(self.dsn, schema=self.schema) as connection:
            return connection.execute(
                "SELECT id, name, homepage_url, host, sitemap_url FROM radar_sites WHERE enabled ORDER BY name, id"
            ).fetchall()

    def commit_complete(
        self,
        site_id: UUID,
        run_key: str,
        scheduled_for: datetime,
        urls: set[str],
        observed_at: datetime,
    ) -> dict[str, int]:
        _aware(scheduled_for, "scheduled_for")
        _aware(observed_at, "observed_at")
        if observed_at < scheduled_for:
            raise ValueError("observed_at cannot precede scheduled_for")
        if not urls:
            raise ValueError("complete snapshot must contain at least one URL")
        if not run_key.startswith(f"site:{site_id}:"):
            raise ValueError("run_key does not match site_id")

        with connect(self.dsn, schema=self.schema) as connection:
            site = connection.execute(
                "SELECT host, enabled FROM radar_sites WHERE id = %s FOR UPDATE", (site_id,)
            ).fetchone()
            if site is None:
                raise ValueError("unknown site")
            if not site["enabled"]:
                raise SitePaused("paused site cannot advance its snapshot")
            if any(
                urlsplit(url).scheme not in {"http", "https"}
                or urlsplit(url).hostname != site["host"]
                for url in urls
            ):
                raise ValueError("snapshot URLs must use the site's HTTP(S) host")

            state = connection.execute(
                "SELECT version, url_count, last_run_key, last_scheduled_for "
                "FROM radar_site_state WHERE site_id = %s FOR UPDATE",
                (site_id,),
            ).fetchone()
            if state is not None:
                if scheduled_for < state["last_scheduled_for"]:
                    raise StaleSiteSnapshot("an older slot cannot replace a newer complete snapshot")
                if scheduled_for == state["last_scheduled_for"]:
                    if run_key != state["last_run_key"]:
                        raise StaleSiteSnapshot("another run already completed this slot")
                    return {
                        "added": 0,
                        "removed": 0,
                        "version": state["version"],
                        "url_count": state["url_count"],
                    }

            previous = {
                row["url"]
                for row in connection.execute("SELECT url FROM radar_site_urls WHERE site_id = %s", (site_id,))
            }
            first = state is None
            added = sorted(urls - previous)
            removed = sorted(previous - urls)
            if removed:
                connection.execute(
                    "DELETE FROM radar_site_urls WHERE site_id = %s AND url = ANY(%s::text[])",
                    (site_id, removed),
                )
            if added:
                connection.execute(
                    "INSERT INTO radar_site_urls (site_id, url, first_seen_at) "
                    "SELECT %s, url, %s FROM unnest(%s::text[]) AS url",
                    (site_id, observed_at, added),
                )
            if not first:
                for event_type, changed in (("added", added), ("removed", removed)):
                    if changed:
                        connection.execute(
                            "INSERT INTO radar_site_events "
                            "(id, site_id, run_key, event_type, url, discovered_at) "
                            "SELECT gen_random_uuid(), %s, %s, %s, url, %s "
                            "FROM unnest(%s::text[]) AS url "
                            "ON CONFLICT (site_id, run_key, event_type, url) DO NOTHING",
                            (site_id, run_key, event_type, observed_at, changed),
                        )

            version = 1 if first else state["version"] + 1
            connection.execute(
                "INSERT INTO radar_site_state "
                "(site_id, version, url_count, last_success_at, last_run_key, last_scheduled_for) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (site_id) DO UPDATE SET "
                "version = EXCLUDED.version, url_count = EXCLUDED.url_count, "
                "last_success_at = EXCLUDED.last_success_at, "
                "last_run_key = EXCLUDED.last_run_key, "
                "last_scheduled_for = EXCLUDED.last_scheduled_for",
                (site_id, version, len(urls), observed_at, run_key, scheduled_for),
            )
            return {
                "added": 0 if first else len(added),
                "removed": 0 if first else len(removed),
                "version": version,
                "url_count": len(urls),
            }
