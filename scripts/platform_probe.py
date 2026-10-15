from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from radar_platform.adapters import github, huggingface  # noqa: E402
from radar_platform.config import load_config  # noqa: E402
from radar_platform.db import validate_test_database_url  # noqa: E402
from radar_platform.http import HttpClient  # noqa: E402
from radar_platform.models import CollectionResult, SourceSnapshot  # noqa: E402
from radar_platform.repository import Repository  # noqa: E402
from radar_platform.runner import run_source  # noqa: E402


SOURCE_ALIASES = {
    "github": ["github:breakout"],
    "hf": ["hf:models", "hf:spaces"],
}
ADAPTERS = {
    "github:breakout": github,
    "hf:models": huggingface,
    "hf:spaces": huggingface,
}


def expand_sources(value: str) -> list[str]:
    expanded: list[str] = []
    for raw in value.split(","):
        name = raw.strip()
        if not name:
            continue
        candidates = SOURCE_ALIASES.get(name, [name])
        for candidate in candidates:
            if candidate not in ADAPTERS:
                raise ValueError(f"unknown source: {candidate}")
            if candidate not in expanded:
                expanded.append(candidate)
    if not expanded:
        raise ValueError("at least one source is required")
    return expanded


def summarize(result: CollectionResult) -> dict:
    return {
        "status": result.status,
        "observations": len(result.observations),
        "discoveries": sum(event.is_discovery for event in result.observations),
        "coverage": result.coverage,
        "snapshot_ready": result.next_snapshot is not None,
    }


def _http_client(cfg, sources: list[str], max_requests: int) -> HttpClient:
    hosts = {
        host
        for source_instance in sources
        for host in cfg.sources.get(source_instance, {}).get("allowed_hosts", [])
    }
    return HttpClient(
        allowed_hosts=hosts,
        tick_limit=max_requests,
        source_limit=max_requests,
        timeout=float(cfg.budgets.get("request_timeout_seconds", 30)),
    )


def probe_structures(cfg, sources: list[str], now: datetime, http: HttpClient) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for source_instance in sources:
        try:
            result = ADAPTERS[source_instance].collect(
                cfg,
                SourceSnapshot(0, {}, None),
                now,
                http,
                source_instance=source_instance,
            )
            output[source_instance] = summarize(result)
        except Exception as exc:
            output[source_instance] = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)[:300]}
    return output


def probe_database(cfg, sources: list[str], now: datetime, http: HttpClient) -> dict[str, dict]:
    dsn = os.environ.get("RADAR_TEST_DATABASE_URL")
    allowed_host = os.environ.get("RADAR_TEST_ALLOWED_HOST")
    if not dsn or not allowed_host:
        raise SystemExit("RADAR_TEST_DATABASE_URL and RADAR_TEST_ALLOWED_HOST are required with --write-test-db")
    validate_test_database_url(dsn, allowed_host)
    repository = Repository(dsn)
    output: dict[str, dict] = {}
    slot = now.replace(minute=0, second=0, microsecond=0).isoformat()
    for source_instance in sources:
        job_key = f"probe:{source_instance}:{slot}"
        if not repository.enqueue(job_key, "probe", now, {"source_instance": source_instance}):
            output[source_instance] = {"status": "already_processed", "job_key": job_key}
            continue
        leases = repository.claim_due(now, limit=1)
        if not leases or leases[0].job_key != job_key:
            raise RuntimeError(f"could not claim newly enqueued probe job {job_key}")
        output[source_instance] = run_source(repository, leases[0], cfg, now, http)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe free source response shapes with a strict request budget")
    parser.add_argument("--config", type=Path, default=ROOT / "config/platform.json")
    parser.add_argument("--sources", default="github,hf")
    parser.add_argument("--max-requests", type=int, default=8)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--write-test-db", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_requests <= 0:
        raise SystemExit("--max-requests must be positive")
    cfg = load_config(args.config)
    sources = expand_sources(args.sources)
    now = datetime.now(timezone.utc)
    http = _http_client(cfg, sources, args.max_requests)
    results = (
        probe_database(cfg, sources, now, http)
        if args.write_test_db
        else probe_structures(cfg, sources, now, http)
    )
    payload = {
        "observed_at": now.isoformat(),
        "write_test_db": bool(args.write_test_db),
        "request_count": http.tick_requests,
        "sources": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if all(row.get("status") != "failed" for row in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
