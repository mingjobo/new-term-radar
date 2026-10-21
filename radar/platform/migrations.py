from __future__ import annotations

import hashlib
from pathlib import Path

from psycopg import sql

from .db import connect, validate_schema_name


DEFAULT_MIGRATIONS = Path(__file__).resolve().parents[2] / "schema/platform"


class MigrationError(RuntimeError):
    pass


class MigrationChecksumError(MigrationError):
    pass


_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS radar_schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _migration_files(directory: Path) -> list[Path]:
    files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise MigrationError(f"no migrations found in {directory}")
    return files


def apply_migrations(
    dsn: str,
    *,
    schema: str = "public",
    migrations_dir: Path | None = None,
) -> list[str]:
    schema = validate_schema_name(schema)
    directory = (migrations_dir or DEFAULT_MIGRATIONS).resolve()
    files = _migration_files(directory)
    applied: list[str] = []

    with connect(dsn, schema=schema) as connection:
        connection.execute(_MIGRATION_TABLE)

    for path in files:
        payload = path.read_bytes()
        checksum = hashlib.sha256(payload).hexdigest()
        with connect(dsn, schema=schema) as connection:
            existing = connection.execute(
                "SELECT checksum FROM radar_schema_migrations WHERE version = %s FOR UPDATE",
                (path.name,),
            ).fetchone()
            if existing is not None:
                if existing["checksum"] != checksum:
                    raise MigrationChecksumError(f"checksum mismatch for {path.name}")
                continue
            connection.execute(sql.SQL(payload.decode("utf-8")))
            connection.execute(
                "INSERT INTO radar_schema_migrations (version, checksum) VALUES (%s, %s)",
                (path.name, checksum),
            )
        applied.append(path.name)
    return applied
