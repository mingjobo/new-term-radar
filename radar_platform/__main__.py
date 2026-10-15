from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .config import load_config
from .migrations import apply_migrations


def _config_check(path: Path) -> int:
    cfg = load_config(path)
    output = {
        "timezone": cfg.timezone,
        "budgets": cfg.budgets,
        "sources": {
            name: {key: value for key, value in source.items() if key in {"enabled", "mode", "provider"}}
            for name, source in cfg.sources.items()
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m radar_platform")
    commands = parser.add_subparsers(dest="command", required=True)
    config_check = commands.add_parser("config-check", help="validate and summarize the free platform config")
    config_check.add_argument("--config", type=Path, default=Path("config/platform.json"))
    migrate = commands.add_parser("migrate", help="apply versioned platform database migrations")
    migrate.add_argument("--database-env", default="RADAR_MIGRATION_DATABASE_URL")
    migrate.add_argument("--schema", default="public")
    migrate.add_argument("--migrations-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "config-check":
        return _config_check(args.config)
    if args.command == "migrate":
        dsn = os.environ.get(args.database_env)
        if not dsn:
            raise SystemExit(f"{args.database_env} is required")
        applied = apply_migrations(dsn, schema=args.schema, migrations_dir=args.migrations_dir)
        print(json.dumps({"schema": args.schema, "applied": applied}, ensure_ascii=False))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

