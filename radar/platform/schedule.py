"""Free source scheduling. Job keys make repeated launches of one slot harmless."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Callable
from uuid import UUID
from zoneinfo import ZoneInfo

from .adapters import slot_for
from .models import PlatformConfig, RunSummary
from .runner import _safe_error, run_source


SOURCE_INSTANCES = ("github:breakout", "hf:models", "hf:spaces")
BEIJING = ZoneInfo("Asia/Shanghai")


def seed_source_jobs(repo, now: datetime) -> int:
    slot = slot_for(now)
    due_at = datetime.fromisoformat(slot.replace("Z", "+00:00"))
    return sum(
        repo.enqueue(
            f"source:{name}:{slot}",
            "collect-source",
            due_at,
            {"source_instance": name},
        )
        for name in SOURCE_INSTANCES
    )


def run_due_sources(
    repo,
    cfg: PlatformConfig,
    now: datetime,
    http_factory: Callable,
    *,
    max_jobs: int,
) -> RunSummary:
    if max_jobs <= 0:
        raise ValueError("max_jobs must be positive")
    seed_source_jobs(repo, now)
    leases = repo.claim_due(
        now,
        limit=max_jobs,
        lease_seconds=int(cfg.budgets.get("lease_seconds", 300)),
        task="collect-source",
    )
    errors = []
    new_terms = 0
    requests = 0
    for lease in leases:
        source = lease.payload["source_instance"]
        if not cfg.sources.get(source, {}).get("enabled", False):
            repo.finish_job(lease, {"status": "off"}, now)
            continue
        try:
            http = http_factory(source)
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)[:300]}
            repo.fail_job(lease, error, None, now)
            errors.append({"source_instance": source, **error})
            continue
        result = run_source(repo, lease, cfg, now, http)
        requests += int(getattr(http, "tick_requests", 0))
        new_terms += int(result.get("new_terms", 0))
        if result["status"] == "failed":
            errors.append({"source_instance": source, **result["error"]})
        elif result["status"] == "incomplete":
            errors.append({
                "source_instance": source,
                "type": "IncompleteSource",
                "message": str(result.get("coverage", {}).get("reason", "incomplete")),
            })
    status = "partial" if errors and len(errors) < len(leases) else "failed" if errors else "ok"
    return RunSummary(status=status, jobs=len(leases), new_terms=new_terms, requests=requests, errors=errors)


def seed_site_jobs(repo, sites, now: datetime) -> int:
    """Seed only the current Beijing day; missed days are never backfilled."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    day = now.astimezone(BEIJING).date()
    due_at = datetime.combine(day, time.min, BEIJING).astimezone(timezone.utc)
    return sum(
        repo.enqueue(
            f"site:{site['id']}:{day.isoformat()}",
            "collect-site",
            due_at,
            {"site_id": str(site["id"]), "source_instance": f"site:{site['id']}"},
        )
        for site in sites.list_enabled_sites()
    )


def run_due_sites(
    repo,
    sites,
    now: datetime,
    http_factory: Callable,
    *,
    max_jobs: int,
) -> RunSummary:
    if max_jobs <= 0:
        raise ValueError("max_jobs must be positive")
    from .adapters.sitemap import discover_and_collect

    seed_site_jobs(repo, sites, now)
    active = {str(site["id"]): site for site in sites.list_enabled_sites()}
    jobs = 0
    errors: list[dict] = []
    requests = 0
    for _ in range(max_jobs):
        # Claim immediately before work so later sites never wait out their lease.
        claim_now = max(now, datetime.now(timezone.utc))
        claimed = repo.claim_due(claim_now, limit=1, lease_seconds=300, task="collect-site")
        if not claimed:
            break
        lease = claimed[0]
        jobs += 1
        site_id = str(lease.payload.get("site_id", ""))
        current_day = max(now, datetime.now(timezone.utc)).astimezone(BEIJING).date()
        job_day = lease.scheduled_for.astimezone(BEIJING).date()
        if job_day != current_day:
            repo.finish_job(
                lease,
                {"status": "skipped", "reason": "missed daily slot"},
                max(now, datetime.now(timezone.utc)),
            )
            continue
        site = active.get(site_id)
        if site is None:
            repo.finish_job(
                lease,
                {"status": "skipped", "reason": "site paused or removed"},
                max(now, datetime.now(timezone.utc)),
            )
            continue
        http = None
        try:
            http = http_factory(site["host"])
            collected = discover_and_collect(site, http)
            finished_at = max(now, datetime.now(timezone.utc))
            if collected.status == "incomplete":
                repo.finish_job(
                    lease,
                    {"status": "incomplete", "reason": collected.error, "documents": collected.documents},
                    finished_at,
                )
                errors.append({
                    "source_instance": f"site:{site_id}",
                    "type": "IncompleteSitemap",
                    "message": collected.error or "incomplete Sitemap",
                })
                continue
            changed = sites.commit_complete(
                UUID(site_id), lease.job_key, lease.scheduled_for, collected.urls, finished_at
            )
            repo.finish_job(
                lease,
                {"status": "ok", **changed, "documents": collected.documents},
                finished_at,
            )
        except Exception as exc:
            error = _safe_error(exc)
            repo.fail_job(lease, error, None, max(now, datetime.now(timezone.utc)))
            errors.append({"source_instance": f"site:{site_id}", **error})
        finally:
            requests += int(getattr(http, "tick_requests", 0))
    status = "partial" if errors and len(errors) < jobs else "failed" if errors else "ok"
    return RunSummary(status=status, jobs=jobs, new_terms=0, requests=requests, errors=errors)
