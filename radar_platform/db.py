from __future__ import annotations

import re
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class DatabaseSafetyError(ValueError):
    pass


PRODUCTION_ENDPOINT = "ep-silent-tooth-aq1rgb46"
_SCHEMA = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def database_host(dsn: str) -> str:
    host = urlsplit(dsn).hostname
    if not host:
        raise DatabaseSafetyError("database URL must contain a hostname")
    return host.casefold().rstrip(".")


def _endpoint_name(host: str) -> str:
    first = host.split(".", 1)[0]
    return first.removesuffix("-pooler")


def validate_test_database_url(dsn: str, allowed_host: str) -> str:
    host = database_host(dsn)
    allowed = allowed_host.casefold().rstrip(".")
    if _endpoint_name(host) == PRODUCTION_ENDPOINT:
        raise DatabaseSafetyError("production database endpoint is forbidden for tests")
    if host != allowed and _endpoint_name(host) != _endpoint_name(allowed):
        raise DatabaseSafetyError(f"test database host {host!r} does not match RADAR_TEST_ALLOWED_HOST")
    return host


def validate_schema_name(schema: str) -> str:
    if not _SCHEMA.fullmatch(schema):
        raise ValueError(f"invalid PostgreSQL schema name: {schema!r}")
    return schema


def connect(dsn: str, *, schema: str, autocommit: bool = False) -> psycopg.Connection:
    schema = validate_schema_name(schema)
    connection = psycopg.connect(dsn, autocommit=autocommit, row_factory=dict_row)
    connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    return connection

