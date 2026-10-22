# Free platform operations

## Environments

The active database is in the new Neon Free project `new-term-radar`. The previous `keyword-detective` project is not used or copied; its data remains untouched. No connection string is stored in Git.

| Item | Value |
|---|---|
| Project | `new-term-radar` / `curly-breeze-91368134` (AWS US East 2, Free plan) |
| Production branch | `production` / `br-jolly-brook-b53hsuhn` |
| Production host | `ep-fancy-paper-b527wslw.c-7.us-east-2.aws.neon.tech` |
| Temporary test branch | `dev-validation` / `br-polished-forest-b5k2xxcy`; expires 2026-10-23 12:58 Beijing time |
| Test host | `ep-dawn-block-b52e3qeb.c-7.us-east-2.aws.neon.tech` |
| Database | `neondb` |
| Roles | SQL-created least-privilege `radar_platform_reader`, `radar_platform_writer`, `radar_platform_migrator`, `radar_platform_site_admin` |

The temporary branch was created from the new, empty production branch on 2026-10-22. Integration tests run only on a non-production branch. Recreate an isolated branch when this one expires; never point `RADAR_TEST_*` at production.

Do not create application roles with the Neon control-plane `create role` action: it may bootstrap them as members of `neon_superuser`. Create the four login roles with SQL using `NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER NOREPLICATION NOBYPASSRLS` and unique random passwords. Migrations `002_roles.sql` and `005_site_roles.sql` abort if their respective application roles inherit `neon_superuser`.

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

For a manual development-branch check, or a deliberate production check with the matching writer-role environment:

```bash
python -m radar collect --kind sites --max-jobs 20
```

The job key is one per site per Beijing calendar day. Repeating the command on the same day does not reread a completed site. Missing days are not reconstructed. The runner claims sites one at a time so a long crawl cannot expire another site's lease before it starts.

## Free GitHub Actions collector

`.github/workflows/free-platform.yml` is the only V1 collector workflow. Its GitHub/HF source slots are UTC 00:00, 08:00 and 16:00 (Beijing 08:00, 16:00 and next-day 00:00). Its daily competitor Sitemap slot is UTC 01:30 (Beijing 09:30). GitHub may start a scheduled job after its nominal time. Each site run handles at most 20 jobs; sites left over are uncollected, not confirmed zero-change. Scheduled workflows run only from `main` after `FREE_RADAR_ENABLED` is exactly `true`. Keep the old `RADAR_ENABLED` variable unset or `false`; it controls the separate upstream/paid workflow.

The `free-radar-dev` GitHub Actions environment contains only the development Neon writer secret `RADAR_WRITE_DATABASE_URL`. The separate `free-radar-production` environment contains only the production Neon writer secret under the same name. The workflow picks the environment by branch: `main` uses production, `codex/free-keyword-platform` uses development. It also receives GitHub's short-lived `GITHUB_TOKEN`; it must not receive reader, site-admin, migrator, legacy Trends or paid API secrets. A manual `workflow_dispatch` run accepts `kind=sources|sites` on those two branches. Manual runs do **not** enable cron; first run both modes on `main` and verify production Neon before setting `FREE_RADAR_ENABLED=true`. A failed or incomplete source returns a nonzero job status and does not advance its baseline. Inspect the JSON collector summary and fix the cause; the next eight-hour slot creates a fresh job automatically. A normal same-slot rerun does not reclaim a terminal job. Same-slot recovery requires a deliberate, reviewed requeue of that exact job key. Neon, not Actions cache, holds job and snapshot state.

Do not set `FREE_RADAR_ENABLED=true` until the production permissions, public website, and both manual collector modes have been accepted.

## Public website

The dashboard reads through `RADAR_READ_DATABASE_URL`; it deliberately refuses to fall back to the writer or legacy `DATABASE_URL`. There is no website account, Basic Auth, password, passcode, or login session. Any visitor can read the data. If settings writes are enabled, any visitor can also add, edit, pause, and resume monitored competitors. This is an accepted first-version risk, not an access-control guarantee. Configure these additional server-side values:

- `RADAR_SITE_ADMIN_DATABASE_URL`: separate, narrowly scoped site-configuration role, required for settings writes. Never substitute the collector writer URL.
- `RADAR_WEB_ALLOWED_ORIGINS`: comma-separated exact HTTPS website origins. Required when the site-admin URL enables settings writes. Browser writes require a same-origin JSON request; a missing Origin or mismatched Host is rejected. This check does not authenticate a person.

Run the local website after exporting the reader URL and, if needed, the site-admin URL plus allowed origin:

```bash
uv run --no-project --with 'psycopg[binary]' \
  python -m radar serve --host 127.0.0.1 --port 8000
```

The WSGI entry point for Vercel is `api/index.py`, selected explicitly by `tool.vercel.entrypoint` in `pyproject.toml`. Vercel's native WSGI routing sends every request to the application; do not add a catch-all rewrite to `/api/index.py`, because current Vercel Python routing exposes that rewritten path to the application. Runtime dependencies must also be declared in `pyproject.toml`, which takes precedence over `requirements.txt` during the Vercel build. `.vercelignore` excludes local environments, probes, test output and caches. The page has no manual collection action. PostgreSQL enforces SELECT-only access for the website reader role; the separate site-admin role can change only monitored-site configuration.

The dashboard shows `未采集` instead of a confirmed zero until all three discovery sources or every eligible monitored site has a successful run for the selected Beijing day. A competitor date range is complete only if each eligible site has a successful run on every eligible Beijing day. For past days, site eligibility is conservatively based on whether the site already existed, not its current pause state; V1 does not record historical pause intervals, so a site paused at that time may leave an old day marked uncollected rather than incorrectly certifying zero. On the current day, a paused site remains eligible if it already attempted collection that day, so pausing cannot erase a confirmed result or hide a failed attempt. The site-list date range carries through to the URL detail view, and its status filter follows the displayed range status.

## Vercel deployment

The Vercel Hobby project is `new-term-radar`. The stable preview alias for `codex/free-keyword-platform` is:

`https://new-term-radar-git-codex-free-keyword-b14d3b-mingjobos-projects.vercel.app`

The existing development preview may still have Vercel Preview Authentication until its access setting is changed. The application itself no longer requires a login. The preview may still point to the old Neon project; repoint it before relying on its data. The production deployment must use the new project's production reader URL. Neither deployment should contain a collector writer or migrator URL.

For settings writes, set the matching branch's pooled `radar_platform_site_admin` URL as `RADAR_SITE_ADMIN_DATABASE_URL` and the exact deployment origin as `RADAR_WEB_ALLOWED_ORIGINS`. Remove obsolete `RADAR_WEB_USERNAME` and `RADAR_WEB_PASSWORD_SHA256` values. Never set `RADAR_WRITE_DATABASE_URL` or `RADAR_MIGRATION_DATABASE_URL` in Vercel. On production, disable Vercel-level visitor authentication, then verify public GETs for overview/terms/competitors/settings, a same-origin site add/pause/resume using the real `aiphotoeditor.com` site only if it is absent, and a cross-origin write rejection. The settings form remains read-only until the separate admin URL is configured.

Rollback order: first set `FREE_RADAR_ENABLED=false` (and leave old `RADAR_ENABLED` unset or `false`), then roll back the website to its previous verified deployment. Do not drop radar or legacy Trends tables during a website rollback; keep their state for investigation and a later retry.

## Migrations

Run migrations deliberately; application startup never creates or changes tables:

```bash
uv run --no-project --with 'psycopg[binary]' \
  python -m radar migrate \
  --database-env RADAR_MIGRATION_DATABASE_URL
```

Migration filenames and SHA-256 checksums are recorded in `radar_schema_migrations`. A changed checksum is an error. The initial migration creates only the original nine `radar_*` tables and their indexes. Migration `004_sitemap.sql` adds monitored sites, URL state and URL change events. The roles migrations grant the reader SELECT only, the collector writer platform-table access, and the site-admin role access only to monitored-site configuration. Migration `003_role_defaults.sql` removes broad default privileges, so unrelated legacy or future tables are not exposed automatically.

Every integration test creates a unique `radar_test_<uuid>` schema and drops only that schema during cleanup. It refuses both known production endpoints, including their pooler hostnames.

## Old account data

The old `keyword-detective` Neon project is historical only. Its Trends tables and radar snapshots are not copied into the new project, and this release does not delete them. The new dashboard begins with empty baselines until the first successful collection. Existing migration files must retain their bytes and checksums; add a new migration for future schema changes rather than rewriting an applied one.
