"""The source checkout, installed wheel and Vercel must use one platform package."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_all_three_entrypoints_after_merge() -> None:
    from radar.platform.web import create_app_from_env

    assert callable(create_app_from_env)

    with tempfile.TemporaryDirectory() as tmp:
        wheel_dir = Path(tmp) / "wheel"
        target = Path(tmp) / "installed"
        wheel_dir.mkdir()
        built = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheel_dir), str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert built.returncode == 0, built.stderr
        wheels = list(wheel_dir.glob("*.whl"))
        assert len(wheels) == 1
        installed = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheels[0])],
            capture_output=True,
            text=True,
            check=False,
        )
        assert installed.returncode == 0, installed.stderr
        env = dict(os.environ, PYTHONPATH=str(target))
        checked = subprocess.run(
            [sys.executable, "-c", "from new_term_radar.platform.web import create_app_from_env; "
             "from new_term_radar.platform.migrations import DEFAULT_MIGRATIONS; "
             "assert callable(create_app_from_env); "
             "assert len(list(DEFAULT_MIGRATIONS.glob('*.sql'))) == 5"],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert checked.returncode == 0, checked.stderr

    env = dict(os.environ)
    env.update(
        RADAR_READ_DATABASE_URL="postgresql://reader:secret@example.com/db",
    )
    vercel = subprocess.run(
        [sys.executable, "-c", "from api.index import app; assert callable(app)"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert vercel.returncode == 0, vercel.stderr


@pytest.mark.parametrize("command", ["daily", "sources", "keywords", "leads", "pains"])
def test_legacy_cli_commands_still_parse(command: str) -> None:
    from radar.__main__ import main

    with pytest.raises(SystemExit) as result:
        main([command, "--help"])
    assert result.value.code == 0


def test_platform_command_dispatches_before_legacy_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from radar.__main__ import main

    monkeypatch.delenv("RADAR_MIGRATION_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="RADAR_MIGRATION_DATABASE_URL is required"):
        main(["migrate"])


def test_no_live_radar_platform_imports() -> None:
    roots = [ROOT / "radar", ROOT / "api", ROOT / "tests/platform", ROOT / "tests/platform_integration"]
    for root in roots:
        for file in root.rglob("*.py"):
            tree = ast.parse(file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                else:
                    continue
                assert all(name != "radar_platform" and not name.startswith("radar_platform.") for name in names), file


def test_default_migrations_still_resolve_after_package_move() -> None:
    from radar.platform.migrations import DEFAULT_MIGRATIONS

    assert DEFAULT_MIGRATIONS == ROOT / "schema/platform"
    assert [path.name for path in sorted(DEFAULT_MIGRATIONS.glob("*.sql"))] == [
        "001_initial.sql",
        "002_roles.sql",
        "003_role_defaults.sql",
        "004_sitemap.sql",
        "005_site_roles.sql",
    ]


def test_packaged_migrations_match_canonical_sql() -> None:
    packaged = ROOT / "radar/platform/schema"
    canonical = ROOT / "schema/platform"
    assert [path.name for path in sorted(packaged.glob("*.sql"))] == [path.name for path in sorted(canonical.glob("*.sql"))]
    for source in canonical.glob("*.sql"):
        assert (packaged / source.name).read_bytes() == source.read_bytes()
