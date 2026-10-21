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
            [sys.executable, "-c", "from new_term_radar.platform.web import create_app_from_env; assert callable(create_app_from_env)"],
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
        RADAR_WEB_USERNAME="researcher",
        RADAR_WEB_PASSWORD_SHA256="0" * 64,
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
