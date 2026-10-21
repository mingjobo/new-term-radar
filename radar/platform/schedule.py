"""Free source scheduling. Job keys make repeated launches of one slot harmless."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .adapters import slot_for
from .models import PlatformConfig, RunSummary
from .runner import run_source


SOURCE_INSTANCES = ("github:breakout", "hf:models", "hf:spaces")


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
