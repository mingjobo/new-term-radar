from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server

from .config import load_config
from .migrations import apply_migrations
from .web import create_app_from_env


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
    parser = argparse.ArgumentParser(prog="python -m radar")
    commands = parser.add_subparsers(dest="command", required=True)
    config_check = commands.add_parser("config-check", help="validate and summarize the free platform config")
    config_check.add_argument("--config", type=Path, default=Path("config/platform.json"))
    migrate = commands.add_parser("migrate", help="apply versioned platform database migrations")
    migrate.add_argument("--database-env", default="RADAR_MIGRATION_DATABASE_URL")
    migrate.add_argument("--schema", default="public")
    migrate.add_argument("--migrations-dir", type=Path)
    serve = commands.add_parser("serve", help="serve the read-only research dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    collect = commands.add_parser("collect", help="collect free sources into Neon")
    collect.add_argument("--kind", choices=["sources", "sites"], required=True)
    collect.add_argument("--config", type=Path, default=Path("config/platform.json"))
    collect.add_argument("--max-jobs", type=int, default=3)
    return parser


def run_platform_command(command: str, argv: list[str]) -> int:
    args = build_parser().parse_args([command, *argv])
    if args.command == "config-check":
        return _config_check(args.config)
    if args.command == "migrate":
        dsn = os.environ.get(args.database_env)
        if not dsn:
            raise SystemExit(f"{args.database_env} is required")
        applied = apply_migrations(dsn, schema=args.schema, migrations_dir=args.migrations_dir)
        print(json.dumps({"schema": args.schema, "applied": applied}, ensure_ascii=False))
        return 0
    if args.command == "serve":
        app = create_app_from_env()
        with make_server(args.host, args.port, app) as server:
            print(f"Serving read-only dashboard on http://{args.host}:{args.port}")
            server.serve_forever()
        return 0
    if args.command == "collect":
        dsn = os.environ.get("RADAR_WRITE_DATABASE_URL")
        if not dsn:
            raise SystemExit("RADAR_WRITE_DATABASE_URL is required")
        if args.kind == "sites":
            raise SystemExit("site collection is not available yet")
        from .http import HttpClient
        from .repository import Repository
        from .schedule import run_due_sources

        cfg = load_config(args.config)

        def http_factory(source: str) -> HttpClient:
            settings = cfg.sources[source]
            return HttpClient(
                allowed_hosts=set(settings.get("allowed_hosts", [])),
                tick_limit=int(cfg.budgets.get("tick_requests", 200)),
                source_limit=int(cfg.budgets.get("source_requests", 60)),
                timeout=float(cfg.budgets.get("request_timeout_seconds", 30)),
            )

        summary = run_due_sources(
            Repository(dsn), cfg, datetime.now(timezone.utc), http_factory, max_jobs=args.max_jobs
        )
        print(json.dumps(asdict(summary), ensure_ascii=False))
        return 0 if summary.status == "ok" else 1
    raise AssertionError(f"unhandled command: {args.command}")
