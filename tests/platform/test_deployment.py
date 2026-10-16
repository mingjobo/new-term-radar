from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_vercel_runtime_dependency_is_declared_in_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert "psycopg[binary]==3.3.6" in project["project"]["dependencies"]


def test_vercel_uses_native_wsgi_routing() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    vercel = json.loads((ROOT / "vercel.json").read_text())

    assert project["tool"]["vercel"]["entrypoint"] == "api.index:app"
    assert "rewrites" not in vercel
