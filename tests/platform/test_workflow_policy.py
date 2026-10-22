from __future__ import annotations

from pathlib import Path

import pytest

from radar.platform import web


ROOT = Path(__file__).resolve().parents[2]
FREE_WORKFLOW = ROOT / ".github/workflows/free-platform.yml"


def test_only_free_collect_is_scheduled() -> None:
    workflow = FREE_WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "0 0,8,16 * * *"' in workflow
    assert 'cron: "30 1 * * *"' in workflow
    assert "python -m radar collect --kind \"$KIND\"" in workflow
    assert "FREE_RADAR_ENABLED" in workflow
    assert "workflow_dispatch:" in workflow
    assert "free-radar-dev" in workflow
    assert "free-radar-production" in workflow
    assert "group: free-radar-${{ github.ref == 'refs/heads/main' && 'production' || 'dev' }}" in workflow
    assert "github.ref == 'refs/heads/main' && 'free-radar-production' || 'free-radar-dev'" in workflow
    assert "RADAR_WRITE_DATABASE_URL: ${{ secrets.RADAR_WRITE_DATABASE_URL }}" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert "(github.event_name == 'workflow_dispatch' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/codex/free-keyword-platform'))" in workflow
    assert "github.event_name == 'schedule' && github.ref == 'refs/heads/main' && vars.FREE_RADAR_ENABLED == 'true'" in workflow
    assert "if [ \"$KIND\" = sites ]; then MAX_JOBS=20; else MAX_JOBS=3; fi" in workflow
    assert "timeout-minutes: 25" in workflow
    for forbidden in ("AISA_API_KEY", "GOANYAPI_API_KEY", "DATAFORSEO", "OPENAI_API_KEY",
                      "RADAR_READ_DATABASE_URL", "RADAR_SITE_ADMIN_DATABASE_URL", "RADAR_MIGRATION_DATABASE_URL",
                      "python -m radar daily"):
        assert forbidden not in workflow


def test_paid_workflow_remains_disabled() -> None:
    old = (ROOT / ".github/workflows/radar.yml").read_text(encoding="utf-8")
    new = FREE_WORKFLOW.read_text(encoding="utf-8")
    assert "if: vars.RADAR_ENABLED == 'true'" in old
    assert "RADAR_ENABLED" not in new.replace("FREE_RADAR_ENABLED", "")
    assert "github.event_name == 'workflow_dispatch'" in new
    assert "refs/heads/codex/free-keyword-platform" in new
    assert "refs/heads/main" in new


def test_app_requires_read_and_site_admin_dsn_separately(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(web, "ReadQueries", lambda dsn: seen.append(("read", dsn)) or object())
    monkeypatch.setattr(web, "SiteAdmin", lambda dsn: seen.append(("admin", dsn)) or object())
    monkeypatch.setattr(web, "create_app", lambda queries, **kwargs: kwargs)

    env = {
        "RADAR_READ_DATABASE_URL": "reader-only",
        "RADAR_SITE_ADMIN_DATABASE_URL": "site-admin-only",
        "RADAR_WRITE_DATABASE_URL": "collector-only",
        "RADAR_WEB_ALLOWED_ORIGINS": "https://preview.example.org",
    }
    app = web.create_app_from_env(env)
    assert seen == [("read", "reader-only"), ("admin", "site-admin-only")]
    assert app["allowed_origins"] == {"https://preview.example.org"}


def test_collector_secret_never_used_by_web_factory() -> None:
    with pytest.raises(RuntimeError, match="RADAR_READ_DATABASE_URL"):
        web.create_app_from_env({
            "RADAR_WRITE_DATABASE_URL": "collector-only",
            "DATABASE_URL": "legacy",
        })
