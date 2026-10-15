# Free platform operations

## Environments

The first development database is an isolated Neon branch in the existing `keyword-detective` project. No connection string is stored in Git.

| Item | Value |
|---|---|
| Project | `keyword-detective` / `wandering-bonus-68047611` |
| Parent | production / `br-delicate-breeze-aqgmgrxx` |
| Development branch | `dev-free-platform` / `br-icy-hill-aqlxwahb` |
| Development host | `ep-gentle-water-aqsds45y-pooler.c-8.us-east-1.aws.neon.tech` |
| Database | `neondb` |
| Roles | SQL-created least-privilege `radar_platform_reader`, `radar_platform_writer`, `radar_platform_migrator` |

The branch was created on 2026-10-15. The account does not permit a custom suspend interval, so the branch uses the account default rather than silently changing plan or buying compute.

Do not create application roles with the Neon control-plane `create role` action: on this project it bootstraps them as members of `neon_superuser`. Create the three login roles with SQL using `NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER NOREPLICATION NOBYPASSRLS`, set a temporary password, then immediately rotate that password through Neon. Migration `002_roles.sql` aborts if any platform role inherits `neon_superuser`.

## Required secrets

- `RADAR_MIGRATION_DATABASE_URL`: direct URL for the migrator role; used only by the explicit migration command.
- `RADAR_WRITE_DATABASE_URL`: writer-role URL for scheduled collection.
- `RADAR_READ_DATABASE_URL`: reader-role URL for the website.
- `RADAR_TEST_DATABASE_URL` and `RADAR_TEST_ALLOWED_HOST`: isolated branch URL plus the exact allowed host. Tests reject the production endpoint and never fall back to `DATABASE_URL`.
- `RADAR_TEST_READER_DATABASE_URL`: reader-role URL used by the permission integration test.
- `RADAR_TEST_WRITER_DATABASE_URL`: writer-role URL used to verify that unrelated tables stay inaccessible.

Use the Neon console or secret manager to obtain these values. Do not put them in tracked files or copy the old project's `.env`.

## Read-only website

The dashboard reads only through `RADAR_READ_DATABASE_URL`; it deliberately refuses to fall back to the writer or legacy `DATABASE_URL`. Configure these additional server-side values:

- `RADAR_WEB_USERNAME`: the Basic Auth username.
- `RADAR_WEB_PASSWORD_SHA256`: the lowercase SHA-256 digest of the password, never the plain-text password.

Run the local preview after exporting those three variables:

```bash
uv run --no-project --with 'psycopg[binary]' \
  python -m radar_platform serve --host 127.0.0.1 --port 8000
```

The WSGI entry point for Vercel is `api/index.py`. `vercel.json` routes all requests through that entry point; `.vercelignore` excludes local environments, probes, test output and caches. The page has no collection or research mutation action. Every route requires Basic Auth, and PostgreSQL separately enforces SELECT-only access for the website role.

## Migrations

Run migrations deliberately; application startup never creates or changes tables:

```bash
uv run --no-project --with 'psycopg[binary]' \
  python -m radar_platform migrate \
  --database-env RADAR_MIGRATION_DATABASE_URL
```

Migration filenames and SHA-256 checksums are recorded in `radar_schema_migrations`. A changed checksum is an error. The initial migration creates only the nine `radar_*` tables and their indexes. The roles migration grants the reader SELECT only and grants the writer DML only on platform tables. Migration `003_role_defaults.sql` removes broad default privileges, so unrelated legacy or future tables are not exposed automatically.

Every integration test creates a unique `radar_test_<uuid>` schema and drops only that schema during cleanup. It refuses the known production endpoint, including its pooler hostname.

## Legacy Trends guard

Before the development migration, the inherited branch had these row counts: `rising_queries=5294`, `root_snapshots=242`, `refresh_runs=7`, `snapshot_comparisons=4`, `snapshot_keyword_diffs=242`, `snapshot_keyword_diff_items=5584`. Its ordered legacy column-shape hash was `2b20fffcad8cf095611aa5f06c9d7cb8`. The post-migration verification must match both the counts and hash.

On 2026-10-15 the development branch applied `001_initial.sql`, `002_roles.sql`, and `003_role_defaults.sql`; an immediate second migration run applied nothing. It had nine `radar_*` tables, three 64-character recorded checksums, no leftover `radar_test_*` schema, and the legacy counts and shape hash above were unchanged. The integration gate passed 15 tests against unique remote schemas, including rollback, slot idempotency, lease expiry, terminal/retry behavior, and database-enforced reader/writer permissions.
