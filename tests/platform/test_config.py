from __future__ import annotations

import json
from pathlib import Path

import pytest

from radar.platform.config import ConfigError, load_config


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ROOTS = [
    "translator", "generator", "example", "convert", "online", "downloader", "maker", "creator",
    "editor", "processor", "designer", "compiler", "analyzer", "evaluator", "sender", "receiver",
    "interpreter", "uploader", "calculator", "sample", "template", "format", "builder", "scheme",
    "pattern", "checker", "detector", "scraper", "manager", "explorer", "dashboard", "planner",
    "tracker", "recorder", "optimizer", "scheduler", "converter", "viewer", "extractor", "monitor",
    "notifier", "verifier", "simulator", "assistant", "constructor", "comparator", "navigator", "syncer",
    "connector", "cataloger", "responder", "api", "automation", "seo", "resume", "analysis", "code",
    "video", "pdf", "scanner", "email", "document", "website", "prompt", "cloud", "image", "text",
    "marketing", "security", "analytics", "visualization", "governance", "form", "chat", "enterprise",
    "audio", "privacy", "monitoring", "hr", "gpt", "content", "cybersecurity", "business", "affiliate",
    "source",
]


def test_default_config_is_free_only_and_preserves_legacy_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISA_API_KEY", "must-not-enable-anything")
    monkeypatch.setenv("GOANYAPI_API_KEY", "must-not-enable-anything")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enable-anything")

    cfg = load_config(ROOT / "config/platform.json")

    assert cfg.roots == EXPECTED_ROOTS
    assert len(cfg.roots) == len(set(cfg.roots)) == 85
    assert cfg.legacy_roots_sha256 == "0dc582c0767ee167019f23b3bbf751b73f98cd458a88fad3c6a0f6df9452cabf"
    assert {name for name, source in cfg.sources.items() if source["enabled"]} == {
        "github:breakout", "hf:models", "hf:spaces"
    }
    assert cfg.sources["gsc"]["enabled"] is False
    assert cfg.sources["sitemap"]["mode"] == "probe"
    assert not any(name in cfg.sources for name in ("aisa", "goanyapi", "openai"))


@pytest.mark.parametrize("provider", ["aisa", "goanyapi", "openai", "dataforseo"])
def test_paid_provider_configuration_is_rejected(tmp_path: Path, provider: str) -> None:
    (tmp_path / "roots.json").write_text(json.dumps({"roots": ["editor"], "source_sha256": "x"}))
    (tmp_path / "aliases.json").write_text("{}")
    (tmp_path / "hf.json").write_text("{}")
    config = {
        "timezone": "Asia/Shanghai",
        "files": {"roots": "roots.json", "aliases": "aliases.json", "hf_task_map": "hf.json"},
        "sources": {provider: {"enabled": True, "provider": provider}},
        "budgets": {"tick_requests": 200, "source_requests": 60},
    }
    path = tmp_path / "platform.json"
    path.write_text(json.dumps(config))

    with pytest.raises(ConfigError, match="paid provider"):
        load_config(path)
