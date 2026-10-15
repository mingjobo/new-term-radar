from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import PlatformConfig
from .normalize import normalize_text


class ConfigError(ValueError):
    pass


_PAID_PROVIDERS = {"aisa", "goanyapi", "openai", "dataforseo"}
_FREE_PROVIDERS = {"github", "huggingface", "gsc", "sitemap"}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"missing config file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc


def _referenced(base: Path, files: dict[str, Any], name: str) -> Path:
    value = files.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"files.{name} must name a JSON file")
    return (base / value).resolve()


def load_config(path: Path) -> PlatformConfig:
    path = path.resolve()
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ConfigError("platform config must be a JSON object")

    sources = raw.get("sources")
    if not isinstance(sources, dict):
        raise ConfigError("sources must be an object")
    clean_sources: dict[str, dict[str, Any]] = {}
    for name, source in sources.items():
        if not isinstance(source, dict):
            raise ConfigError(f"source {name!r} must be an object")
        provider = normalize_text(str(source.get("provider", name.split(":", 1)[0])))
        if provider in _PAID_PROVIDERS:
            raise ConfigError(f"paid provider {provider!r} is not allowed in the free platform")
        if provider not in _FREE_PROVIDERS:
            raise ConfigError(f"unknown free provider {provider!r}")
        clean_sources[str(name)] = dict(source)

    files = raw.get("files")
    if not isinstance(files, dict):
        raise ConfigError("files must be an object")
    roots_doc = _read_json(_referenced(path.parent, files, "roots"))
    if not isinstance(roots_doc, dict) or not isinstance(roots_doc.get("roots"), list):
        raise ConfigError("roots file must contain a roots array")
    roots = [normalize_text(str(item)) for item in roots_doc["roots"]]
    if not all(roots) or len(roots) != len(set(roots)):
        raise ConfigError("roots must be non-empty and unique after normalization")

    aliases_doc = _read_json(_referenced(path.parent, files, "aliases"))
    if not isinstance(aliases_doc, dict):
        raise ConfigError("aliases file must be an object")
    aliases = aliases_doc.get("aliases", aliases_doc)
    if not isinstance(aliases, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()):
        raise ConfigError("aliases must map strings to strings")

    hf_doc = _read_json(_referenced(path.parent, files, "hf_task_map"))
    if not isinstance(hf_doc, dict):
        raise ConfigError("HF task map must be an object")
    hf_task_map = hf_doc.get("tasks", hf_doc)
    if not isinstance(hf_task_map, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in hf_task_map.items()):
        raise ConfigError("HF task map must map strings to strings")

    budgets = raw.get("budgets")
    if not isinstance(budgets, dict):
        raise ConfigError("budgets must be an object")
    for key in ("tick_requests", "source_requests"):
        if not isinstance(budgets.get(key), int) or budgets[key] <= 0:
            raise ConfigError(f"budgets.{key} must be a positive integer")

    timezone_name = raw.get("timezone")
    if not isinstance(timezone_name, str):
        raise ConfigError("timezone must be a string")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"unknown timezone: {timezone_name}") from exc

    return PlatformConfig(
        sources=clean_sources,
        roots=roots,
        aliases=dict(aliases),
        hf_task_map=dict(hf_task_map),
        budgets=dict(budgets),
        timezone=timezone_name,
        legacy_roots_sha256=str(roots_doc.get("source_sha256", "")),
    )

