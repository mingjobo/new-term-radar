from __future__ import annotations

import hashlib
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from radar.platform.db import DatabaseSafetyError, validate_test_database_url
from radar.platform.migrations import MigrationChecksumError, apply_migrations


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {
    "radar_schema_migrations",
    "radar_terms",
    "radar_evidence",
    "radar_relations",
    "radar_source_state",
    "radar_jobs",
    "radar_runs",
    "radar_checks",
    "radar_reports",
    "radar_sites",
    "radar_site_state",
    "radar_site_urls",
    "radar_site_events",
}
LEGACY_TABLES = {
    "rising_queries",
    "root_snapshots",
    "refresh_runs",
    "snapshot_comparisons",
    "snapshot_keyword_diffs",
    "snapshot_keyword_diff_items",
}

APPLIED_MIGRATION_HASHES = {
    "001_initial.sql": "d3f8a898cb71cd2bf04223287d8470f735ada41b91331de0fbb28d08b7b20f01",
    "002_roles.sql": "4937f168cb06afb1edd3515f0af9d5e71a36953b962ce67adf3e33435328ed6d",
    "003_role_defaults.sql": "645a6c6b9913cfbac512fb01681af5fd37713f3e1a191a31f38e59e061b0f2ae",
}


def test_historical_migration_bytes_are_immutable() -> None:
    for name, expected in APPLIED_MIGRATION_HASHES.items():
        assert hashlib.sha256((ROOT / "schema/platform" / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize(
    ("dsn", "allowed_host"),
    [
        (
            "postgresql://u:p@ep-silent-tooth-aq1rgb46.c-8.us-east-1.aws.neon.tech/neondb",
            "ep-silent-tooth-aq1rgb46.c-8.us-east-1.aws.neon.tech",
        ),
        (
            "postgresql://u:p@ep-silent-tooth-aq1rgb46-pooler.c-8.us-east-1.aws.neon.tech/neondb",
            "ep-silent-tooth-aq1rgb46.c-8.us-east-1.aws.neon.tech",
        ),
        (
            "postgresql://u:p@ep-fancy-paper-b527wslw.c-7.us-east-2.aws.neon.tech/neondb",
            "ep-fancy-paper-b527wslw.c-7.us-east-2.aws.neon.tech",
        ),
        (
            "postgresql://u:p@ep-fancy-paper-b527wslw-pooler.c-7.us-east-2.aws.neon.tech/neondb",
            "ep-fancy-paper-b527wslw.c-7.us-east-2.aws.neon.tech",
        ),
    ],
)
def test_known_production_endpoint_is_always_rejected(dsn: str, allowed_host: str) -> None:
    with pytest.raises(DatabaseSafetyError, match="production"):
        validate_test_database_url(dsn, allowed_host)


def test_test_database_host_must_match_allowlist() -> None:
    with pytest.raises(DatabaseSafetyError, match="does not match"):
        validate_test_database_url(
            "postgresql://u:p@ep-dev-example.neon.tech/neondb",
            "ep-somewhere-else.neon.tech",
        )


def test_migrations_idempotent_and_checksums_match(test_dsn: str, test_schema: str, tmp_path: Path) -> None:
    first = apply_migrations(test_dsn, schema=test_schema)
    second = apply_migrations(test_dsn, schema=test_schema)

    assert first == ["001_initial.sql", "002_roles.sql", "003_role_defaults.sql", "004_sitemap.sql", "005_site_roles.sql"]
    assert second == []
    with psycopg.connect(test_dsn) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(test_schema)))
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = %s",
                (test_schema,),
            ).fetchall()
        }
        versions = connection.execute(
            "SELECT version, checksum FROM radar_schema_migrations ORDER BY version"
        ).fetchall()
    assert tables == EXPECTED_TABLES
    assert [row[0] for row in versions] == ["001_initial.sql", "002_roles.sql", "003_role_defaults.sql", "004_sitemap.sql", "005_site_roles.sql"]
    assert all(len(row[1]) == 64 for row in versions)

    changed_dir = tmp_path / "migrations"
    changed_dir.mkdir()
    for source in sorted((ROOT / "schema/platform").glob("*.sql")):
        target = changed_dir / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    initial = changed_dir / "001_initial.sql"
    initial.write_text(initial.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8")

    with pytest.raises(MigrationChecksumError, match="001_initial.sql"):
        apply_migrations(test_dsn, schema=test_schema, migrations_dir=changed_dir)


def _legacy_shape_and_counts(dsn: str) -> dict[str, tuple[int, tuple[tuple[str, str], ...]]]:
    result: dict[str, tuple[int, tuple[tuple[str, str], ...]]] = {}
    with psycopg.connect(dsn) as connection:
        for table in sorted(LEGACY_TABLES):
            exists = connection.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0]
            if exists is None:
                continue
            count = connection.execute(
                sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table))
            ).fetchone()[0]
            columns = tuple(
                connection.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table,),
                ).fetchall()
            )
            result[table] = (count, columns)
    return result


def test_migration_does_not_change_legacy_trends_tables_if_present(test_dsn: str, test_schema: str) -> None:
    before = _legacy_shape_and_counts(test_dsn)
    apply_migrations(test_dsn, schema=test_schema)
    after = _legacy_shape_and_counts(test_dsn)

    assert after == before


def test_reader_role_can_select_but_cannot_insert(
    test_dsn: str,
    reader_dsn: str,
    migrated_schema: str,
) -> None:
    with psycopg.connect(test_dsn) as owner_connection:
        assert owner_connection.execute(
            "SELECT pg_has_role('radar_platform_reader', 'neon_superuser', 'member')"
        ).fetchone()[0] is False
        assert owner_connection.execute(
            "SELECT has_schema_privilege('radar_platform_reader', %s, 'USAGE')",
            (migrated_schema,),
        ).fetchone()[0] is True
        assert owner_connection.execute(
            "SELECT has_table_privilege('radar_platform_reader', %s, 'SELECT')",
            (f"{migrated_schema}.radar_terms",),
        ).fetchone()[0] is True
        assert owner_connection.execute(
            "SELECT has_table_privilege('radar_platform_reader', %s, 'INSERT')",
            (f"{migrated_schema}.radar_terms",),
        ).fetchone()[0] is False
    with psycopg.connect(reader_dsn) as connection:
        assert connection.execute("SELECT current_user").fetchone()[0] == "radar_platform_reader"
        assert connection.execute(
            sql.SQL("SELECT count(*) FROM {}.radar_terms").format(sql.Identifier(migrated_schema))
        ).fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                sql.SQL(
                    "INSERT INTO {}.radar_terms "
                    "(id, canonical_key, name, kind, language, first_seen_at, last_seen_at) "
                    "VALUES ('00000000-0000-0000-0000-000000000001', "
                    "'forbidden', 'forbidden', 'name', 'en', now(), now())"
                ).format(sql.Identifier(migrated_schema))
            )


def test_roles_do_not_gain_default_access_to_unrelated_tables(
    test_dsn: str,
    reader_dsn: str,
    writer_dsn: str,
    migrated_schema: str,
) -> None:
    with psycopg.connect(test_dsn, autocommit=True) as owner_connection:
        owner_connection.execute(
            sql.SQL("CREATE TABLE {}.unrelated_after_migration (id INTEGER)").format(
                sql.Identifier(migrated_schema)
            )
        )
        assert owner_connection.execute(
            "SELECT has_table_privilege('radar_platform_writer', %s, 'INSERT')",
            (f"{migrated_schema}.radar_terms",),
        ).fetchone()[0] is True
        assert owner_connection.execute(
            "SELECT has_table_privilege('radar_platform_writer', %s, 'SELECT')",
            (f"{migrated_schema}.unrelated_after_migration",),
        ).fetchone()[0] is False

    for dsn in (reader_dsn, writer_dsn):
        with psycopg.connect(dsn) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    sql.SQL("SELECT * FROM {}.unrelated_after_migration").format(
                        sql.Identifier(migrated_schema)
                    )
                )
