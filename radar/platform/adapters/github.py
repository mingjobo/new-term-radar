from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from ...breakout import qualifies, repo_term

from ..models import CollectionResult, EvidenceInput, HttpResponse, PlatformConfig, SourceSnapshot
from ..normalize import canonical_key

from . import json_body, slot_for


API = "https://api.github.com"
REQUIRED = {"id", "full_name", "name", "html_url", "created_at", "stargazers_count"}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _history(previous: SourceSnapshot, now: datetime) -> dict[str, list[dict[str, Any]]]:
    raw = previous.payload.get("repos", {})
    if not isinstance(raw, dict):
        return {}
    cutoff = now - timedelta(hours=48)
    output: dict[str, list[dict[str, Any]]] = {}
    for repo_id, observations in raw.items():
        if not isinstance(observations, list):
            continue
        kept = []
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            observed_at = _parse_time(observation.get("observed_at"))
            if observed_at is not None and observed_at >= cutoff and isinstance(observation.get("stars"), int):
                kept.append({"observed_at": observed_at.isoformat(), "stars": observation["stars"]})
        if kept:
            output[str(repo_id)] = kept
    return output


def _nearest_daily(history: list[dict[str, Any]], now: datetime) -> tuple[dict[str, Any] | None, datetime | None]:
    candidates = []
    for observation in history:
        observed_at = _parse_time(observation.get("observed_at"))
        if observed_at is None:
            continue
        age_hours = (now - observed_at).total_seconds() / 3600
        if 20 <= age_hours <= 28:
            candidates.append((abs(age_hours - 24), observation, observed_at))
    if not candidates:
        return None, None
    _, observation, observed_at = min(candidates, key=lambda item: item[0])
    return observation, observed_at


def _settings(cfg: PlatformConfig) -> dict[str, int]:
    raw = cfg.sources.get("github:breakout", {})
    return {
        "window_days": int(raw.get("window_days", 14)),
        "min_stars": int(raw.get("min_stars", 300)),
        "velocity_min": int(raw.get("velocity_min", 200)),
        "delta_min": int(raw.get("delta_min", 400)),
        "pages": int(raw.get("pages", 10)),
    }


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "new-term-radar-free/0.1",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _search(http, now: datetime, settings: dict[str, int]) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    since = (now.astimezone(timezone.utc) - timedelta(days=settings["window_days"])).date().isoformat()
    query = quote(f"created:>={since} stars:>={settings['min_stars']}")
    items: list[dict[str, Any]] = []
    total: int | None = None
    for page in range(1, settings["pages"] + 1):
        response: HttpResponse = http.request(
            "GET",
            f"{API}/search/repositories?q={query}&sort=stars&order=desc&per_page=100&page={page}",
            headers=_headers(),
        )
        payload = json_body(response, source="github:breakout")
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            return None, {"complete": False, "reason": "changed_shape"}
        if payload.get("incomplete_results") is True:
            return None, {"complete": False, "reason": "github_incomplete_results"}
        if not isinstance(payload.get("total_count"), int):
            return None, {"complete": False, "reason": "missing_total_count"}
        total = payload["total_count"]
        page_items = payload["items"]
        if any(not isinstance(item, dict) or not REQUIRED.issubset(item) for item in page_items):
            return None, {"complete": False, "reason": "changed_item_shape"}
        items.extend(page_items)
        if len(page_items) < 100:
            break
    if not items:
        return None, {"complete": False, "reason": "empty_result"}
    if total is None or len(items) < total:
        return None, {"complete": False, "reason": "truncated", "items": len(items), "total": total}
    return items, {"complete": True, "items": len(items), "total": total}


def collect(
    cfg: PlatformConfig,
    previous: SourceSnapshot,
    now: datetime,
    http,
    *,
    source_instance: str,
) -> CollectionResult:
    if source_instance != "github:breakout":
        raise ValueError(f"unsupported GitHub source: {source_instance}")
    settings = _settings(cfg)
    repos, coverage = _search(http, now, settings)
    if repos is None:
        return CollectionResult("incomplete", [], None, coverage)

    histories = _history(previous, now)
    raw_flagged = previous.payload.get("flagged", {})
    flagged = dict(raw_flagged) if isinstance(raw_flagged, dict) else {}
    flag_cutoff = (now - timedelta(days=30)).date().isoformat()
    flagged = {str(key): value for key, value in flagged.items() if isinstance(value, str) and value >= flag_cutoff}
    slot = slot_for(now)
    observations: list[EvidenceInput] = []

    for repo in repos:
        repo_id = str(repo["id"])
        created_at = _parse_time(repo["created_at"])
        stars = repo["stargazers_count"]
        if created_at is None or not isinstance(stars, int) or stars < 0 or created_at > now:
            return CollectionResult("incomplete", [], None, {"complete": False, "reason": "invalid_repo_values"})
        age_days = max((now - created_at).total_seconds() / 86400, 1.0)
        velocity = round(stars / age_days)
        daily_observation, daily_time = _nearest_daily(histories.get(repo_id, []), now)
        delta = None if daily_observation is None else stars - int(daily_observation["stars"])
        meets_bar = (
            age_days <= settings["window_days"]
            and stars >= settings["min_stars"]
            and qualifies(stars, age_days, delta, settings["velocity_min"], settings["delta_min"])
        )
        is_discovery = meets_bar and repo_id not in flagged
        if is_discovery:
            flagged[repo_id] = now.date().isoformat()
        metrics = {
            "repo_id": repo["id"],
            "full_name": repo["full_name"],
            "stars": stars,
            "velocity_per_day": velocity,
            "delta_24h": delta,
            "age_days": round(age_days, 1),
        }
        data_window = {
            "slot": slot,
            "window_days": settings["window_days"],
            "delta_observed_at": None if daily_time is None else daily_time.isoformat(),
        }
        event = EvidenceInput(
            source_instance=source_instance,
            external_id=repo_id,
            entity_key=repo_id,
            name=repo_term(repo["name"]),
            kind="name",
            language="en",
            url=repo["html_url"],
            excerpt=str(repo.get("description") or "")[:500],
            observed_at=now,
            data_window=data_window,
            metrics=metrics,
            content_hash=hashlib.sha256(
                json.dumps({"repo": repo_id, "metrics": metrics}, sort_keys=True, default=str).encode()
            ).hexdigest(),
            is_discovery=is_discovery,
        )
        observations.append(replace(event, entity_key=canonical_key(event, cfg.aliases)))

        current = {"observed_at": now.isoformat(), "stars": stars}
        prior = [item for item in histories.get(repo_id, []) if item["observed_at"] != current["observed_at"]]
        histories[repo_id] = prior + [current]

    next_snapshot = {"repos": histories, "flagged": flagged, "slot": slot, "observed_at": now.isoformat()}
    return CollectionResult("ok", observations, next_snapshot, coverage)
