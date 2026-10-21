from __future__ import annotations

from datetime import datetime, timedelta, timezone

from radar.platform import runner
from radar.platform.models import CollectionResult, Lease, PlatformConfig, SourceSnapshot


NOW = datetime(2026, 10, 15, 8, 17, tzinfo=timezone.utc)
LEASE = Lease("job", "token", "collect", {"source_instance": "github:breakout"}, NOW)
CFG = PlatformConfig({}, [], {}, {}, {}, "Asia/Shanghai")


class FakeRepository:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.commits = []
        self.finishes = []
        self.failures = []

    def get_source_state(self, source_instance: str) -> SourceSnapshot:
        return SourceSnapshot(3, {"state": "before"}, NOW - timedelta(hours=8))

    def commit_source(self, lease, result, *, expected_version, now):
        if self.commit_error:
            raise self.commit_error
        self.commits.append((lease, result, expected_version, now))
        return {"observations": len(result.observations), "new_terms": 0, "source_version": 4}

    def finish_job(self, lease, result, now):
        self.finishes.append((lease, result, now))

    def fail_job(self, lease, error, retry_at, now):
        self.failures.append((lease, error, retry_at, now))


class Adapter:
    def __init__(self, result: CollectionResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def collect(self, cfg, previous, now, http, *, source_instance):
        if self.error:
            raise self.error
        return self.result


def test_complete_collection_commits_expected_source_version(monkeypatch) -> None:
    repo = FakeRepository()
    result = CollectionResult("baseline", [], {"ids": ["one"]}, {"items": 1})
    monkeypatch.setitem(runner.ADAPTERS, "github:breakout", Adapter(result))

    summary = runner.run_source(repo, LEASE, CFG, NOW, object())

    assert summary == {"status": "baseline", "observations": 0, "new_terms": 0, "source_version": 4}
    assert repo.commits[0][2] == 3
    assert repo.finishes == []
    assert repo.failures == []


def test_incomplete_collection_finishes_without_advancing_snapshot(monkeypatch) -> None:
    repo = FakeRepository()
    result = CollectionResult("incomplete", [], None, {"reason": "truncated"})
    monkeypatch.setitem(runner.ADAPTERS, "github:breakout", Adapter(result))

    summary = runner.run_source(repo, LEASE, CFG, NOW, object())

    assert summary["status"] == "incomplete"
    assert repo.commits == []
    assert repo.finishes[0][1]["status"] == "incomplete"


def test_collection_or_commit_failure_is_recorded_without_slot_retry(monkeypatch) -> None:
    for adapter, repository in (
        (Adapter(error=RuntimeError("network unavailable")), FakeRepository()),
        (Adapter(CollectionResult("ok", [], {"ids": []}, {})), FakeRepository(commit_error=RuntimeError("write failed"))),
    ):
        monkeypatch.setitem(runner.ADAPTERS, "github:breakout", adapter)

        summary = runner.run_source(repository, LEASE, CFG, NOW, object())

        assert summary["status"] == "failed"
        assert repository.failures[0][2] is None
        assert "RuntimeError" in repository.failures[0][1]["type"]
