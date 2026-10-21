from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")


@dataclass(frozen=True)
class EvidenceInput:
    source_instance: str
    external_id: str
    entity_key: str
    name: str
    kind: str
    language: str
    url: str
    excerpt: str
    observed_at: datetime
    data_window: dict[str, Any]
    metrics: dict[str, Any]
    content_hash: str
    is_discovery: bool
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"name", "generic", "unknown"}:
            raise ValueError(f"invalid evidence kind: {self.kind}")
        _require_aware(self.observed_at, "observed_at")
        if len(self.excerpt) > 500:
            raise ValueError("excerpt must be at most 500 characters")


@dataclass(frozen=True)
class SourceSnapshot:
    version: int
    payload: dict[str, Any]
    last_success_at: datetime | None

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError("snapshot version cannot be negative")
        if self.last_success_at is not None:
            _require_aware(self.last_success_at, "last_success_at")


@dataclass(frozen=True)
class CollectionResult:
    status: str
    observations: list[EvidenceInput]
    next_snapshot: dict[str, Any] | None
    coverage: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status not in {"ok", "baseline", "off", "incomplete"}:
            raise ValueError(f"invalid collection status: {self.status}")


@dataclass(frozen=True)
class Lease:
    job_key: str
    lease_token: str
    task: str
    payload: dict[str, Any]
    scheduled_for: datetime

    def __post_init__(self) -> None:
        _require_aware(self.scheduled_for, "scheduled_for")


@dataclass(frozen=True)
class RelationInput:
    name_key: str
    generic_key: str
    phrase: str
    language: str
    evidence_id: str
    quote: str
    rule_version: str


@dataclass(frozen=True)
class PlatformConfig:
    sources: dict[str, dict[str, Any]]
    roots: list[str]
    aliases: dict[str, str]
    hf_task_map: dict[str, str]
    budgets: dict[str, int | float]
    timezone: str
    legacy_roots_sha256: str = ""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class RunSummary:
    status: str
    jobs: int
    new_terms: int
    requests: int
    errors: list[dict[str, Any]] = field(default_factory=list)
