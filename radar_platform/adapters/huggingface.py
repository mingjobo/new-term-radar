from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from radar.sources import SPACE_NOISE, base_name

from radar_platform.models import CollectionResult, EvidenceInput, HttpResponse, PlatformConfig, SourceSnapshot
from radar_platform.normalize import canonical_key

from . import json_body, slot_for


TOP_DISCOVERY = 50
TOP_SNAPSHOT = 100


def _valid_items(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, list) or not payload:
        return None
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] for item in payload):
        return None
    return payload[:TOP_SNAPSHOT]


def _name(item_id: str, kind: str) -> str:
    value = base_name(item_id)
    if kind == "spaces":
        value = " ".join(word for word in value.split() if word not in SPACE_NOISE)
    return value or item_id.rsplit("/", 1)[-1].casefold()


def _event(
    item: dict[str, Any],
    *,
    rank: int,
    source_instance: str,
    kind: str,
    now: datetime,
    slot: str,
    is_discovery: bool,
    cfg: PlatformConfig,
) -> EvidenceInput:
    item_id = item["id"]
    metric_tag = item.get("pipeline_tag") if kind == "models" else item.get("sdk")
    metrics = {
        "rank": rank,
        "likes": int(item.get("likes") or 0),
        "trending_score": item.get("trendingScore"),
        "task": metric_tag,
        "source_kind": kind,
    }
    if kind == "models" and item.get("downloads") is not None:
        metrics["downloads"] = item.get("downloads")
    url = f"https://huggingface.co/{'spaces/' if kind == 'spaces' else ''}{item_id}"
    excerpt = str(item.get("description") or metric_tag or "")[:500]
    event = EvidenceInput(
        source_instance=source_instance,
        external_id=item_id,
        entity_key=item_id,
        name=_name(item_id, kind),
        kind="name",
        language="en",
        url=url,
        excerpt=excerpt,
        observed_at=now,
        data_window={"slot": slot, "rank_window": TOP_SNAPSHOT},
        metrics=metrics,
        content_hash=hashlib.sha256(
            json.dumps({"id": item_id, "metrics": metrics}, sort_keys=True, default=str).encode()
        ).hexdigest(),
        is_discovery=is_discovery,
    )
    return replace(event, entity_key=canonical_key(event, cfg.aliases))


def collect(
    cfg: PlatformConfig,
    previous: SourceSnapshot,
    now: datetime,
    http,
    *,
    source_instance: str,
) -> CollectionResult:
    if source_instance not in {"hf:models", "hf:spaces"}:
        raise ValueError(f"unsupported Hugging Face source: {source_instance}")
    kind = source_instance.split(":", 1)[1]
    response: HttpResponse = http.request(
        "GET",
        f"https://huggingface.co/api/{kind}?sort=trendingScore&direction=-1&limit={TOP_SNAPSHOT}",
        headers={"Accept": "application/json", "User-Agent": "new-term-radar-free/0.1"},
    )
    items = _valid_items(json_body(response, source=source_instance))
    if items is None:
        return CollectionResult(
            status="incomplete",
            observations=[],
            next_snapshot=None,
            coverage={"complete": False, "reason": "empty_or_changed_shape"},
        )

    before = previous.payload.get("ids") if previous.version > 0 else None
    if previous.version > 0 and (
        not isinstance(before, list) or any(not isinstance(item_id, str) for item_id in before)
    ):
        return CollectionResult(
            status="incomplete",
            observations=[],
            next_snapshot=None,
            coverage={"complete": False, "reason": "invalid_previous_snapshot"},
        )
    before_ids = set(before or [])
    slot = slot_for(now)
    ids = [item["id"] for item in items]
    next_snapshot = {"ids": ids, "slot": slot, "observed_at": now.isoformat()}
    coverage = {"complete": True, "items": len(items), "top": TOP_SNAPSHOT}
    if previous.version == 0:
        return CollectionResult("baseline", [], next_snapshot, coverage)

    observations = [
        _event(
            item,
            rank=rank,
            source_instance=source_instance,
            kind=kind,
            now=now,
            slot=slot,
            is_discovery=rank <= TOP_DISCOVERY and item["id"] not in before_ids,
            cfg=cfg,
        )
        for rank, item in enumerate(items, 1)
    ]
    return CollectionResult("ok", observations, next_snapshot, coverage)

