from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql

from radar.platform.db import validate_test_database_url
from radar.platform.migrations import apply_migrations
from radar.platform.repository import Repository


@pytest.fixture(scope="session")
def test_dsn() -> str:
    dsn = os.environ.get("RADAR_TEST_DATABASE_URL")
    allowed_host = os.environ.get("RADAR_TEST_ALLOWED_HOST")
    if not dsn or not allowed_host:
        pytest.skip("RADAR_TEST_DATABASE_URL and RADAR_TEST_ALLOWED_HOST are required")
    validate_test_database_url(dsn, allowed_host)
    return dsn


@pytest.fixture(scope="session")
def reader_dsn() -> str:
    dsn = os.environ.get("RADAR_TEST_READER_DATABASE_URL")
    allowed_host = os.environ.get("RADAR_TEST_ALLOWED_HOST")
    if not dsn or not allowed_host:
        pytest.skip("RADAR_TEST_READER_DATABASE_URL is required for role tests")
    validate_test_database_url(dsn, allowed_host)
    return dsn


@pytest.fixture(scope="session")
def writer_dsn() -> str:
    dsn = os.environ.get("RADAR_TEST_WRITER_DATABASE_URL")
    allowed_host = os.environ.get("RADAR_TEST_ALLOWED_HOST")
    if not dsn or not allowed_host:
        pytest.skip("RADAR_TEST_WRITER_DATABASE_URL is required for role tests")
    validate_test_database_url(dsn, allowed_host)
    return dsn


@pytest.fixture
def test_schema(test_dsn: str) -> Iterator[str]:
    schema = f"radar_test_{uuid.uuid4().hex}"
    assert re.fullmatch(r"radar_test_[0-9a-f]{32}", schema)
    with psycopg.connect(test_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield schema
    finally:
        with psycopg.connect(test_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def migrated_schema(test_dsn: str, test_schema: str) -> str:
    apply_migrations(test_dsn, schema=test_schema)
    return test_schema


@pytest.fixture
def repository(test_dsn: str, migrated_schema: str) -> Repository:
    return Repository(test_dsn, schema=migrated_schema)
