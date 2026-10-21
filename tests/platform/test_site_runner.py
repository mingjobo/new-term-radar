from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from radar.platform.models import HttpResponse, Lease


NOW = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)


class MemoryRepo:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.finished: list[dict] = []
        self.claim_limits: list[int] = []

    def enqueue(self, key, task, due, payload):
        if key in self.jobs:
            return False
        self.jobs[key] = {"task": task, "due": due, "payload": payload, "status": "pending"}
        return True

    def claim_due(self, now, *, limit=1, lease_seconds=300, task=None):
        self.claim_limits.append(limit)
        keys = [
            key for key, value in sorted(self.jobs.items())
            if value["status"] == "pending" and value["due"] <= now and value["task"] == task
        ][:limit]
        for key in keys:
            self.jobs[key]["status"] = "leased"
        return [Lease(key, "token", self.jobs[key]["task"], self.jobs[key]["payload"], self.jobs[key]["due"]) for key in keys]

    def finish_job(self, lease, result, now):
        self.jobs[lease.job_key]["status"] = "complete"
        self.finished.append(result)

    def fail_job(self, lease, error, retry_at, now):
        self.jobs[lease.job_key]["status"] = "failed"
        self.finished.append({"status": "failed", "error": error})


class MemorySites:
    def __init__(self) -> None:
        self.rows = [
            {"id": uuid.uuid4(), "name": "Bad", "host": "bad.example", "homepage_url": "https://bad.example/", "sitemap_url": None},
            {"id": uuid.uuid4(), "name": "Good", "host": "good.example", "homepage_url": "https://good.example/", "sitemap_url": None},
        ]
        self.commits: list[uuid.UUID] = []

    def list_enabled_sites(self):
        return self.rows

    def commit_complete(self, site_id, run_key, scheduled_for, urls, observed_at):
        self.commits.append(site_id)
        return {"added": 0, "removed": 0, "version": 1, "url_count": len(urls)}


class Http:
    tick_requests = 0

    def __init__(self, host: str):
        self.host = host

    def request(self, method, url, *, headers=None):
        self.tick_requests += 1
        if url.endswith("robots.txt"):
            return HttpResponse(404, {}, b"")
        if self.host == "bad.example":
            return HttpResponse(500, {}, b"")
        return HttpResponse(200, {}, b"<urlset><url><loc>https://good.example/a</loc></url></urlset>")


def test_one_site_failure_does_not_block_other_site() -> None:
    from radar.platform.schedule import run_due_sites

    repo = MemoryRepo()
    sites = MemorySites()
    result = run_due_sites(repo, sites, NOW, lambda host: Http(host), max_jobs=10)

    assert result.status == "partial"
    assert result.jobs == 2
    assert sites.commits == [sites.rows[1]["id"]]
    assert sorted(item["status"] for item in repo.finished) == ["incomplete", "ok"]
    assert repo.claim_limits == [1, 1, 1]


def test_site_jobs_once_per_beijing_day_without_backfill() -> None:
    from radar.platform.schedule import seed_site_jobs

    repo = MemoryRepo()
    sites = MemorySites()
    assert seed_site_jobs(repo, sites, NOW) == 2
    assert seed_site_jobs(repo, sites, NOW + timedelta(hours=14)) == 0
    assert seed_site_jobs(repo, sites, NOW + timedelta(days=2)) == 2
    assert len(repo.jobs) == 4
    assert all(job["task"] == "collect-site" for job in repo.jobs.values())


def test_missed_previous_day_job_is_skipped_without_fetching_history() -> None:
    from radar.platform.schedule import run_due_sites

    repo = MemoryRepo()
    sites = MemorySites()
    sites.rows = [sites.rows[1]]
    old_day = NOW - timedelta(days=1)
    old_key = f"site:{sites.rows[0]['id']}:2026-10-20"
    repo.enqueue(
        old_key, "collect-site", old_day,
        {"site_id": str(sites.rows[0]["id"]), "source_instance": f"site:{sites.rows[0]['id']}"},
    )

    result = run_due_sites(repo, sites, NOW, lambda host: Http(host), max_jobs=10)

    assert result.jobs == 2
    assert sites.commits == [sites.rows[0]["id"]]
    assert [item["status"] for item in repo.finished] == ["skipped", "ok"]
