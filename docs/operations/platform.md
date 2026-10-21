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
| Roles | SQL-created least-privilege `radar_platform_reader`, `radar_platform_writer`, `radar_platform_migrator`, `radar_platform_site_admin` |

The branch was created on 2026-10-15. The account does not permit a custom suspend interval, so the branch uses the account default rather than silently changing plan or buying compute.

Do not create application roles with the Neon control-plane `create role` action: on this project it bootstraps them as members of `neon_superuser`. Create the four login roles with SQL using `NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER NOREPLICATION NOBYPASSRLS`, set a temporary password, then immediately rotate that password through Neon. Migrations `002_roles.sql` and `005_site_roles.sql` abort if their respective application roles inherit `neon_superuser`.

## Required secrets

- `RADAR_MIGRATION_DATABASE_URL`: direct URL for the migrator role; used only by the explicit migration command.
- `RADAR_WRITE_DATABASE_URL`: writer-role URL for scheduled collection.
- `RADAR_READ_DATABASE_URL`: reader-role URL for the website.
- `RADAR_SITE_ADMIN_DATABASE_URL`: site-admin-role URL for changing monitored-site settings only. Never expose it to the browser or a collection job.
- `RADAR_TEST_DATABASE_URL` and `RADAR_TEST_ALLOWED_HOST`: isolated branch URL plus the exact allowed host. Tests reject the production endpoint and never fall back to `DATABASE_URL`.
- `RADAR_TEST_READER_DATABASE_URL`: reader-role URL used by the permission integration test.
- `RADAR_TEST_WRITER_DATABASE_URL`: writer-role URL used to verify that unrelated tables stay inaccessible.
- `RADAR_TEST_SITE_ADMIN_DATABASE_URL`: site-admin-role URL used to verify that it cannot change terms, URL snapshots, or events.

Use the Neon console or secret manager to obtain these values. Do not put them in tracked files or copy the old project's `.env`.

## Daily monitored-site collection

After the site-admin role adds a site through settings, the next daily collector run reads its public robots.txt and complete Sitemap. The first complete run saves URLs without emitting change events. Later complete runs compare URL sets; an incomplete or failed read retains the previous baseline. Pausing a site keeps its history and prevents new daily jobs. This collector uses only `RADAR_WRITE_DATABASE_URL` and never accepts the site-admin or reader URL as a fallback.

For a manual development-branch check only:

```bash
python -m radar collect --kind sites --max-jobs 20
```

The job key is one per site per Beijing calendar day. Repeating the command on the same day does not reread a completed site. Missing days are not reconstructed. The runner claims sites one at a time so a long crawl cannot expire another site's lease before it starts.

## Free GitHub Actions collector

`.github/workflows/free-platform.yml` is the only V1 collector workflow. Its source slot is UTC 00:00, 08:00 and 16:00 (GitHub, HF Models, HF Spaces); its site slot is UTC 01:30 daily. GitHub Actions scheduled workflows run only after this workflow reaches the repository default branch, and the job remains **off** unless the repository variable `FREE_RADAR_ENABLED` is exactly `true`. Keep the old `RADAR_ENABLED` variable unset; it controls the separate upstream/paid workflow.

For the development preview, create a protected GitHub Actions environment named `free-radar-dev` containing only the development-branch writer secret `RADAR_WRITE_DATABASE_URL`. If the production schedule is later enabled, use a separate `free-radar-production` environment containing the **production-branch** writer secret under the same key. The workflow picks the environment by event type, so a production cron cannot use the development credential. The workflow also receives GitHub's short-lived `GITHUB_TOKEN`; it must not receive the reader, site-admin, migrator, legacy Trends or paid API secrets. A manual `workflow_dispatch` run accepts `kind=sources|sites` only from `codex/free-keyword-platform`, and must be explicitly chosen in GitHub Actions. GitHub requires the workflow file to exist on the default branch before the manual Run workflow control is available; a file present only on the development branch cannot yet be dispatched. A failed or incomplete source returns a nonzero job status and does not advance its baseline. Inspect the JSON collector summary and fix the cause; the next eight-hour slot creates a fresh job automatically. A normal same-slot rerun does not reclaim a terminal job. Same-slot recovery requires a deliberate, reviewed requeue of that exact development job key. Neon, not Actions cache, holds job and snapshot state.

Do not set `FREE_RADAR_ENABLED=true` or broaden the manual branch guard until the preview and its separate permissions have been accepted. Production enablement, production migration and default-branch merge are separate decisions.

## Read-only website

The dashboard reads only through `RADAR_READ_DATABASE_URL`; it deliberately refuses to fall back to the writer or legacy `DATABASE_URL`. Configure these additional server-side values:

- `RADAR_WEB_USERNAME`: the Basic Auth username.
- `RADAR_WEB_PASSWORD_SHA256`: the lowercase SHA-256 digest of the password, never the plain-text password.
- `RADAR_WEB_ALLOWED_ORIGINS`: comma-separated exact website origins (for example, the protected Vercel preview URL). Required only when `RADAR_SITE_ADMIN_DATABASE_URL` enables settings writes. Browser writes require an authenticated same-origin JSON request; no Origin or a mismatched Host is rejected.

Run the local preview after exporting those three variables:

```bash
uv run --no-project --with 'psycopg[binary]' \
  python -m radar serve --host 127.0.0.1 --port 8000
```

The WSGI entry point for Vercel is `api/index.py`, selected explicitly by `tool.vercel.entrypoint` in `pyproject.toml`. Vercel's native WSGI routing sends every request to the application; do not add a catch-all rewrite to `/api/index.py`, because current Vercel Python routing exposes that rewritten path to the application. Runtime dependencies must also be declared in `pyproject.toml`, which takes precedence over `requirements.txt` during the Vercel build. `.vercelignore` excludes local environments, probes, test output and caches. The page has no collection or research mutation action. Every route requires Basic Auth, and PostgreSQL separately enforces SELECT-only access for the website role.

## Preview deployment

The Vercel Hobby project is `new-term-radar`. The stable preview alias for `codex/free-keyword-platform` is:

`https://new-term-radar-git-codex-free-keyword-b14d3b-mingjobos-projects.vercel.app`

The preview is protected twice: Vercel Preview Authentication first, then the application's Basic Auth. It uses only the pooled `radar_platform_reader` URL on the isolated `dev-free-platform` Neon branch. Production has not been switched, and no writer or migrator credential is present in the website deployment.

To enable the V1 settings form on **Preview only**, add the development branch's pooled `radar_platform_site_admin` URL as `RADAR_SITE_ADMIN_DATABASE_URL` and the exact protected preview origin as `RADAR_WEB_ALLOWED_ORIGINS`. Keep `RADAR_READ_DATABASE_URL`, `RADAR_WEB_USERNAME` and `RADAR_WEB_PASSWORD_SHA256` in Preview as server-side secrets. Never set `RADAR_WRITE_DATABASE_URL` or `RADAR_MIGRATION_DATABASE_URL` in Vercel. After the new preview build, verify an authenticated GET for overview/competitors/settings, a same-origin site add/pause/resume, and a cross-origin write rejection. The settings form is intentionally read-only until the separate admin URL is configured.

Rollback order: first turn off `FREE_RADAR_ENABLED` (and leave old `RADAR_ENABLED` unset), then roll back the preview website deployment. Do not drop new radar tables or legacy Trends tables during a website rollback; keep their state for a later retry.

## Migrations

Run migrations deliberately; application startup never creates or changes tables:

```bash
uv run --no-project --with 'psycopg[binary]' \
  python -m radar migrate \
  --database-env RADAR_MIGRATION_DATABASE_URL
```

Migration filenames and SHA-256 checksums are recorded in `radar_schema_migrations`. A changed checksum is an error. The initial migration creates only the original nine `radar_*` tables and their indexes. Migration `004_sitemap.sql` adds monitored sites, URL state and URL change events. The roles migrations grant the reader SELECT only, the collector writer platform-table access, and the site-admin role access only to monitored-site configuration. Migration `003_role_defaults.sql` removes broad default privileges, so unrelated legacy or future tables are not exposed automatically.

Every integration test creates a unique `radar_test_<uuid>` schema and drops only that schema during cleanup. It refuses the known production endpoint, including its pooler hostname.

## Legacy Trends guard

Before the development migration, the inherited branch had these row counts: `rising_queries=5294`, `root_snapshots=242`, `refresh_runs=7`, `snapshot_comparisons=4`, `snapshot_keyword_diffs=242`, `snapshot_keyword_diff_items=5584`. Its ordered legacy column-shape hash was `2b20fffcad8cf095611aa5f06c9d7cb8`. The post-migration verification must match both the counts and hash.

On 2026-10-15 the development branch applied `001_initial.sql`, `002_roles.sql`, and `003_role_defaults.sql`; an immediate second migration run applied nothing. It had nine `radar_*` tables, three 64-character recorded checksums, no leftover `radar_test_*` schema, and the legacy counts and shape hash above were unchanged. The integration gate passed 15 tests against unique remote schemas, including rollback, slot idempotency, lease expiry, terminal/retry behavior, and database-enforced reader/writer permissions.

On 2026-10-21 the development branch also applied `004_sitemap.sql` and `005_site_roles.sql`. A second run again applied nothing, and all six legacy row counts stayed unchanged. The original `001_initial.sql` and `002_roles.sql` must retain their historically applied trailing blank line: a prior formatting commit removed it and caused a checksum mismatch, even though the SQL meaning was the same. Never alter an applied migration or overwrite its recorded checksum; add a new migration instead.
