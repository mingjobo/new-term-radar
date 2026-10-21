from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import sql

from radar.platform.config import load_config
from radar.platform.models import HttpResponse
from radar.platform.repository import Repository
from radar.platform.runner import run_source


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 15, 8, 17, tzinfo=timezone.utc)


class JsonHttp:
    def __init__(self, payload) -> None:
        self.payload = payload

    def request(self, method: str, url: str, *, headers=None, body=None) -> HttpResponse:
        return HttpResponse(200, {"content-type": "application/json"}, json.dumps(self.payload).encode())


class FailFirstCommit:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def commit_source(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise RuntimeError("injected write failure")
        return self.repository.commit_source(*args, **kwargs)


def _github_payload() -> dict:
    return {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "id": 101,
                "full_name": "Acme/Fast-Radar",
                "name": "Fast-Radar",
                "html_url": "https://github.com/Acme/Fast-Radar",
                "description": "An evidence-backed radar for emerging tools",
                "created_at": (NOW - timedelta(hours=48)).isoformat().replace("+00:00", "Z"),
                "stargazers_count": 1000,
            }
        ],
    }


def _counts(dsn: str, schema: str) -> dict[str, int]:
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        return {
            table: connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            for table in ("radar_terms", "radar_evidence", "radar_source_state", "radar_runs")
        }


def test_write_failure_retries_identically_while_other_source_commits(
    repository: Repository,
    test_dsn: str,
    migrated_schema: str,
) -> None:
    cfg = load_config(ROOT / "config/platform.json")
    failing = FailFirstCommit(repository)
    assert repository.enqueue(
        "probe:github:slot",
        "collect",
        NOW,
        {"source_instance": "github:breakout"},
    )
    github_lease = repository.claim_due(NOW)[0]

    failed = run_source(failing, github_lease, cfg, NOW, JsonHttp(_github_payload()))

    assert failed["status"] == "failed"
    assert repository.get_source_state("github:breakout").version == 0
    assert _counts(test_dsn, migrated_schema) == {
        "radar_terms": 0,
        "radar_evidence": 0,
        "radar_source_state": 0,
        "radar_runs": 1,
    }

    assert repository.enqueue(
        "probe:hf:slot",
        "collect",
        NOW,
        {"source_instance": "hf:models"},
    )
    hf_lease = repository.claim_due(NOW)[0]
    hf = run_source(
        repository,
        hf_lease,
        cfg,
        NOW,
        JsonHttp([{"id": "org/model", "likes": 3, "pipeline_tag": "text-generation"}]),
    )
    assert hf["status"] == "baseline"
    assert repository.get_source_state("hf:models").version == 1
    assert repository.get_source_state("github:breakout").version == 0

    retry_time = NOW + timedelta(minutes=5)
    retry_lease = repository.claim_due(retry_time)[0]
    retried = run_source(repository, retry_lease, cfg, retry_time, JsonHttp(_github_payload()))

    assert retried == {"status": "ok", "observations": 1, "new_terms": 1, "source_version": 1}
    assert _counts(test_dsn, migrated_schema) == {
        "radar_terms": 1,
        "radar_evidence": 1,
        "radar_source_state": 2,
        "radar_runs": 3,
    }


def test_incomplete_response_records_run_without_advancing_source(
    repository: Repository,
    test_dsn: str,
    migrated_schema: str,
) -> None:
    cfg = load_config(ROOT / "config/platform.json")
    assert repository.enqueue(
        "probe:github:incomplete",
        "collect",
        NOW,
        {"source_instance": "github:breakout"},
    )
    lease = repository.claim_due(NOW)[0]

    summary = run_source(
        repository,
        lease,
        cfg,
        NOW,
        JsonHttp({"total_count": 0, "incomplete_results": False, "items": []}),
    )

    assert summary["status"] == "incomplete"
    assert repository.get_source_state("github:breakout").version == 0
    assert _counts(test_dsn, migrated_schema) == {
        "radar_terms": 0,
        "radar_evidence": 0,
        "radar_source_state": 0,
        "radar_runs": 1,
    }
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(migrated_schema)))
        assert connection.execute("SELECT status FROM radar_runs").fetchone()[0] == "incomplete"
