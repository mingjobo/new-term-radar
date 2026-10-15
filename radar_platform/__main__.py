from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .config import load_config


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "config-check":
        return _config_check(args.config)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

