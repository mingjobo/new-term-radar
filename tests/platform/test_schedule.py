from __future__ import annotations

import importlib
import importlib.util
from datetime import datetime, timedelta, timezone

from radar.platform.models import CollectionResult, Lease, PlatformConfig, SourceSnapshot


def _schedule():
    assert importlib.util.find_spec("radar.platform.schedule") is not None, "free source scheduler is missing"
    return importlib.import_module("radar.platform.schedule")


NOW = datetime(2026, 10, 21, 8, 17, tzinfo=timezone.utc)
SOURCES = ("github:breakout", "hf:models", "hf:spaces")
CFG = PlatformConfig(
    sources={name: {"enabled": True, "allowed_hosts": ["example.com"]} for name in SOURCES},
    roots=[],
    aliases={},
    hf_task_map={},
    budgets={"lease_seconds": 300, "source_requests": 10, "tick_requests": 30},
    timezone="Asia/Shanghai",
)


class MemoryRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.commits: list[str] = []
        self.failures: list[str] = []

    def enqueue(self, job_key, task, due_at, payload):
        if job_key in self.jobs:
            return False
        self.jobs[job_key] = {"task": task, "due_at": due_at, "payload": payload, "status": "pending"}
        return True

    def claim_due(self, now, *, limit=1, lease_seconds=300, task=None):
        candidates = sorted(
            (key, job)
            for key, job in self.jobs.items()
            if job["status"] == "pending" and job["due_at"] <= now and (task is None or job["task"] == task)
        )
        leases = []
        for key, job in candidates[:limit]:
            job["status"] = "leased"
            leases.append(Lease(key, "token", job["task"], job["payload"], job["due_at"]))
        return leases

    def get_source_state(self, source_instance):
        return SourceSnapshot(0, {}, None)

    def commit_source(self, lease, result, *, expected_version, now):
        self.commits.append(lease.job_key)
        self.jobs[lease.job_key]["status"] = "complete"
        return {"observations": len(result.observations), "new_terms": 0, "source_version": 1}

    def fail_job(self, lease, error, retry_at, now):
        self.failures.append(lease.job_key)
        self.jobs[lease.job_key]["status"] = "pending"
        self.jobs[lease.job_key]["due_at"] = retry_at

    def finish_job(self, lease, result, now):
        self.jobs[lease.job_key]["status"] = "complete"


class CompleteAdapter:
    def collect(self, cfg, previous, now, http, *, source_instance):
        return CollectionResult("baseline", [], {"ids": [source_instance]}, {"items": 1})


class FailingAdapter:
    def collect(self, cfg, previous, now, http, *, source_instance):
        raise RuntimeError("source temporarily unavailable")


class IncompleteAdapter:
    def collect(self, cfg, previous, now, http, *, source_instance):
        return CollectionResult("incomplete", [], None, {"reason": "truncated", "items": 200, "total": 246})


class HttpStub:
    tick_requests = 1


def test_three_source_jobs_once_per_eight_hour_slot() -> None:
    repo = MemoryRepository()

    assert _schedule().seed_source_jobs(repo, NOW) == 3
    assert _schedule().seed_source_jobs(repo, NOW + timedelta(hours=7)) == 0
    assert len(repo.jobs) == 3
    assert all("2026-10-21T08:00:00Z" in key for key in repo.jobs)
    assert all(job["due_at"] == NOW.replace(minute=0) for job in repo.jobs.values())
    assert _schedule().seed_source_jobs(repo, NOW + timedelta(hours=8)) == 3


def test_second_run_does_not_duplicate_term_or_slot_evidence(monkeypatch) -> None:
    from radar.platform import runner

    repo = MemoryRepository()
    for name in SOURCES:
        monkeypatch.setitem(runner.ADAPTERS, name, CompleteAdapter())

    first = _schedule().run_due_sources(repo, CFG, NOW, lambda source: HttpStub(), max_jobs=3)
    repeated = _schedule().run_due_sources(repo, CFG, NOW + timedelta(minutes=1), lambda source: HttpStub(), max_jobs=3)

    assert first.jobs == 3
    assert repeated.jobs == 0
    assert len(repo.commits) == 3
    assert len(repo.jobs) == 3


def test_one_source_failure_does_not_block_others(monkeypatch) -> None:
    from radar.platform import runner

    repo = MemoryRepository()
    for name in SOURCES:
        monkeypatch.setitem(runner.ADAPTERS, name, FailingAdapter() if name == "hf:models" else CompleteAdapter())

    result = _schedule().run_due_sources(repo, CFG, NOW, lambda source: HttpStub(), max_jobs=3)

    assert result.jobs == 3
    assert len(repo.commits) == 2
    assert len(repo.failures) == 1
    assert result.status == "partial"


def test_incomplete_source_is_not_reported_as_success(monkeypatch) -> None:
    from radar.platform import runner

    repo = MemoryRepository()
    for name in SOURCES:
        monkeypatch.setitem(runner.ADAPTERS, name, IncompleteAdapter() if name == "github:breakout" else CompleteAdapter())

    result = _schedule().run_due_sources(repo, CFG, NOW, lambda source: HttpStub(), max_jobs=3)

    assert result.status == "partial"
    assert result.errors[0]["source_instance"] == "github:breakout"
    assert result.errors[0]["message"] == "truncated"


def test_source_runner_leaves_site_jobs_unclaimed(monkeypatch) -> None:
    from radar.platform import runner

    repo = MemoryRepository()
    repo.enqueue("site:example:2026-10-21", "collect-site", NOW.replace(minute=0), {"site_id": "example"})
    for name in SOURCES:
        monkeypatch.setitem(runner.ADAPTERS, name, CompleteAdapter())

    result = _schedule().run_due_sources(repo, CFG, NOW, lambda source: HttpStub(), max_jobs=3)

    assert result.jobs == 3
    assert repo.jobs["site:example:2026-10-21"]["status"] == "pending"


def test_collect_cli_requires_writer_without_legacy_fallback(monkeypatch) -> None:
    from radar.__main__ import main

    monkeypatch.delenv("RADAR_WRITE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://untrusted:untrusted@example.com/db")
    monkeypatch.setenv("RADAR_READ_DATABASE_URL", "postgresql://reader:reader@example.com/db")

    try:
        main(["collect", "--kind", "sources"])
    except SystemExit as exc:
        assert "RADAR_WRITE_DATABASE_URL is required" in str(exc)
    else:
        assert False, "collector must reject missing writer credentials"
