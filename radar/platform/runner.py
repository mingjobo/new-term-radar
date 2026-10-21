from __future__ import annotations

import re
from datetime import datetime

from .adapters import github, huggingface
from .models import Lease, PlatformConfig


ADAPTERS = {
    "github:breakout": github,
    "hf:models": huggingface,
    "hf:spaces": huggingface,
}
_SECRET_URL = re.compile(r"postgres(?:ql)?://\S+", re.IGNORECASE)


def _safe_error(exc: Exception) -> dict[str, str]:
    message = _SECRET_URL.sub("[database URL redacted]", str(exc))[:500]
    return {"type": type(exc).__name__, "message": message}


def run_source(repo, lease: Lease, cfg: PlatformConfig, now: datetime, http) -> dict:
    source_instance = lease.payload.get("source_instance")
    adapter = ADAPTERS.get(source_instance)
    if adapter is None:
        raise ValueError(f"unknown free source: {source_instance}")
    previous = repo.get_source_state(source_instance)
    try:
        result = adapter.collect(cfg, previous, now, http, source_instance=source_instance)
        if result.status in {"incomplete", "off"}:
            summary = {"status": result.status, "coverage": result.coverage, "observations": 0, "new_terms": 0}
            repo.finish_job(lease, summary, now)
            return summary
        committed = repo.commit_source(
            lease,
            result,
            expected_version=previous.version,
            now=now,
        )
        return {"status": result.status, **committed}
    except Exception as exc:
        error = _safe_error(exc)
        # The next eight-hour slot creates a fresh job. A delayed retry of this
        # slot would consume one of its three scheduled source slots instead.
        repo.fail_job(lease, error, None, now)
        return {"status": "failed", "error": error}
