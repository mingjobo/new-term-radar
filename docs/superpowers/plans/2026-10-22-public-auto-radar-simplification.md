# Public Automated Keyword Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the existing `new-term-radar` workbench without website login and continuously populate it from GitHub, Hugging Face, and competitor Sitemaps on the confirmed free schedule.

**Architecture:** Keep the existing Python WSGI application, vanilla browser UI, Neon schema, and collectors. GitHub Actions runs the collectors and writes to Neon; Vercel reads platform data and may edit only monitored-site configuration through a separate server-side connection. The browser never receives database credentials.

**Tech Stack:** Python 3.10–3.12, WSGI, psycopg 3.3.6, PostgreSQL on Neon, vanilla HTML/CSS/JavaScript, pytest, Playwright/Chrome, GitHub Actions, Vercel.

**Spec:** `docs/superpowers/specs/2026-10-22-public-auto-radar-simplification-design.md`

## Global Constraints

- No website account, Basic Auth, password, passcode, session, or user table; public visitors may read data and edit competitor settings.
- Keep `RADAR_READ_DATABASE_URL`, `RADAR_SITE_ADMIN_DATABASE_URL`, `RADAR_WRITE_DATABASE_URL`, and migration access server-side; never expose a database URL to browser JavaScript.
- Keep same-origin write checks, public-URL validation, JSON/body limits, duplicate-host rejection, complete-Sitemap safeguards, and parameterized SQL.
- GitHub/HF schedules are UTC `00:00`, `08:00`, `16:00`; competitor Sitemap schedule is UTC `01:30`; site collection processes at most 20 jobs per run.
- A failed or incomplete source cannot advance its baseline; a failed or incomplete Sitemap cannot create removal events or replace its previous URL set.
- Do not add Google Trends history, paid APIs, page-content diffing, manual collection buttons, delete-history actions, or a new frontend framework.
- Do not drop existing `radar_*` or legacy Trends tables, rewrite applied migration files, force-push `main`, or point destructive integration fixtures at production Neon.

## Review Focus

- Anonymous requests to `/`, static assets, and read APIs must return normal content without a `WWW-Authenticate` challenge; Task 1 pins this.
- Public same-origin site writes must work while missing/cross-origin requests remain rejected; Task 1 pins this.
- Missing site-admin configuration must disable settings writes without falling back to the collector credential; Task 1 pins this.
- A manual run from `main` must use `free-radar-production`, while cron remains disabled until `FREE_RADAR_ENABLED=true`; Task 2 pins this.
- Failed/incomplete collection and a site count above the 20-job run cap must remain visibly uncollected rather than becoming confirmed zero or removals; Tasks 2 and 6 pin this through policy, existing collector tests, and production evidence.

---

### Task 1: Remove Website Login Without Weakening Settings Validation

**Files:**
- Modify: `radar/platform/web.py`
- Modify: `radar/platform/auth.py`
- Modify: `radar/platform/commands.py`
- Modify: `tests/platform/test_web.py`
- Modify: `tests/platform/test_site_admin_web.py`
- Modify: `tests/platform/test_workflow_policy.py`
- Modify: `tests/platform/test_package_merge.py`
- Modify: `tests/e2e/test_workbench.py`

**Interfaces:**
- Produces: `create_app(queries: ReadQueries, *, site_admin: SiteAdmin | None = None, allowed_origins: set[str] | None = None) -> Callable`
- Produces: `create_app_from_env(environ: Mapping[str, str] | None = None) -> Callable`, requiring `RADAR_READ_DATABASE_URL` and conditionally `RADAR_SITE_ADMIN_DATABASE_URL` plus `RADAR_WEB_ALLOWED_ORIGINS`, but no web username/password.
- Preserves: `trusted_same_origin(origin: str | None, host: str | None, allowed_origins: set[str]) -> bool`.

- [ ] **Step 1: Replace authentication expectations with anonymous-access tests.** In `test_web.py`, add `test_public_routes_need_no_credentials` asserting `/`, `/api/overview`, `/api/daily-terms`, `/api/competitors`, `/api/settings/status`, and `/static/app.css` return `200` without an Authorization header and do not emit `WWW-Authenticate`. Update the app fixture to call the new signature.
- [ ] **Step 2: Pin public-write boundaries.** In `test_site_admin_web.py`, rename the write test to `test_admin_write_is_public_but_requires_same_origin`; assert same-origin POST without credentials returns `201`, missing/cross-origin returns `403`, JSON/body/duplicate/URL safety checks still behave as before, and absent `RADAR_SITE_ADMIN_DATABASE_URL` returns `405` without using `RADAR_WRITE_DATABASE_URL`.
- [ ] **Step 3: Run the focused tests and confirm they fail for the old login contract.** Run `python -m pytest -q tests/platform/test_web.py tests/platform/test_site_admin_web.py tests/platform/test_workflow_policy.py tests/platform/test_package_merge.py tests/e2e/test_workbench.py`. Expected: failures caused by the required Basic Auth arguments/challenge and old environment requirements.
- [ ] **Step 4: Implement the minimal public application contract.** Remove `BasicAuth` construction and the 401 branch from `web.py`; remove `username` and `password_sha256` parameters and environment checks; delete the unused `BasicAuth` class/imports while leaving same-origin validation intact. Change the serve help/status copy so it no longer calls the site read-only.
- [ ] **Step 5: Update test fixtures only for the new contract.** Remove generated password hashes, Authorization helpers, and Playwright `http_credentials`; do not loosen CSP, safe-link rendering, write-origin checks, or database-credential separation assertions.
- [ ] **Step 6: Run the focused tests.** Run the command from Step 3. Expected: all selected tests pass, including real Chrome cases.
- [ ] **Step 7: Commit.** Commit only the Task 1 code/tests as `feat: make keyword radar publicly accessible`.

### Task 2: Make the Existing Schedule Safe to Start in Production

**Files:**
- Modify: `.github/workflows/free-platform.yml`
- Modify: `tests/platform/test_workflow_policy.py`

**Interfaces:**
- Consumes: `python -m radar collect --kind sources|sites --max-jobs N` and server-side `RADAR_WRITE_DATABASE_URL`.
- Produces: manual `workflow_dispatch` from the development branch using `free-radar-dev`, manual `workflow_dispatch` from `main` using `free-radar-production`, and gated cron from `main` using `free-radar-production`.

- [ ] **Step 1: Write failing workflow-policy tests.** Assert manual runs accept only `refs/heads/codex/free-keyword-platform` and `refs/heads/main`; `main` and scheduled runs select `free-radar-production`; only scheduled runs require `FREE_RADAR_ENABLED == 'true'`; exact crons, `MAX_JOBS=20` for sites, `MAX_JOBS=3` for sources, 25-minute timeout, and the absence of reader/admin/migrator/paid secrets remain pinned.
- [ ] **Step 2: Run the policy tests.** Run `python -m pytest -q tests/platform/test_workflow_policy.py`. Expected: the new manual-`main` assertions fail.
- [ ] **Step 3: Update the workflow expressions.** Permit trusted manual dispatch from `main` without enabling cron and choose the production GitHub Environment whenever the ref is `main`; keep scheduled execution restricted to `main` plus the explicit repository variable.
- [ ] **Step 4: Run workflow and collector regressions.** Run `python -m pytest -q tests/platform/test_workflow_policy.py tests/platform/test_schedule.py tests/platform/test_site_runner.py tests/platform/test_runner.py`. Expected: all pass.
- [ ] **Step 5: Commit.** Commit Task 2 as `ci: prepare free collectors for production schedule`.

### Task 3: Update Operations Guidance and Pass the Development Release Gate

**Files:**
- Modify: `docs/operations/platform.md`
- Modify: `docs/verification/2026-10-21-unified-v1.md` only if an existing statement must be corrected; otherwise leave historical evidence unchanged.

**Interfaces:**
- Consumes: Task 1 public web contract and Task 2 production workflow contract.
- Produces: one current runbook that distinguishes Vercel display credentials from GitHub Actions collection credentials and gives the rollback order.

- [ ] **Step 1: Update the runbook.** Remove Basic Auth and protected-preview instructions; document the public settings risk, exact schedules in UTC and Beijing time, manual-`main` production smoke run, `FREE_RADAR_ENABLED` gate, 20-site capacity, environment names, secret separation, and rollback order.
- [ ] **Step 2: Scan tracked files for stale required-login instructions.** Run `rg -n "RADAR_WEB_USERNAME|RADAR_WEB_PASSWORD_SHA256|requires Basic Auth|Every route requires Basic Auth" radar tests api docs/operations .github pyproject.toml`. Expected: no live-code or current-runbook matches; dated design/verification history may remain explicitly historical.
- [ ] **Step 3: Run the complete local release gate.** Run `python -m pytest -q tests/test_radar.py tests/platform tests/e2e`. Expected: all pass with no unexpected skips; Chrome tests verify anonymous page load and public same-origin settings edits.
- [ ] **Step 4: Run isolated development-Neon integration tests.** With the existing development-only `RADAR_TEST_*` credentials, run `python -m pytest -q tests/platform_integration`. Expected: all pass; each test uses and removes only its unique `radar_test_*` schema.
- [ ] **Step 5: Review packaging.** Run `python -m pytest -q tests/platform/test_package_merge.py`. Expected: source import, installed wheel import, migration packaging, and Vercel entrypoint all pass without web credentials.
- [ ] **Step 6: Commit.** Commit runbook changes as `docs: explain public automated radar operations`.

### Task 4: Prepare Production Neon With Least-Privilege Server Connections

**Files:**
- No product-code changes expected.
- Record sanitized evidence later in: `docs/verification/2026-10-22-public-auto-radar-release.md`.

**Interfaces:**
- Produces server-side connection URLs for reader, site-admin, writer, and migrator use; none enters Git, browser code, screenshots, or verification logs.
- Produces explicit privileges: reader selects platform tables; site-admin selects/inserts/updates only `radar_sites`; writer changes collector tables and reads/updates site configuration; migrator manages platform schema changes.

- [ ] **Step 1: Inspect before changing anything.** Query the production Neon branch for applied `radar_schema_migrations`, all `radar_*` tables, the four role names, and the six legacy Trends row counts. Save only names/counts/checksums, never connection strings.
- [ ] **Step 2: Create only missing technical roles through SQL.** Use `LOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER NOREPLICATION NOBYPASSRLS`; do not create them through Neon control-plane role creation and do not add a fifth role. Generate/rotate secrets without printing them to command output.
- [ ] **Step 3: Apply only pending immutable migrations.** Run the existing migrator over production; expect `002_roles.sql`, `003_role_defaults.sql`, and `005_site_roles.sql` if `001_initial.sql` and `004_sitemap.sql` are already recorded. A second run must report no pending migrations; any checksum mismatch stops the task.
- [ ] **Step 4: Verify permissions without inserting test data.** Use `has_schema_privilege` and `has_table_privilege` plus a `SELECT 1` connection check for each role. Assert reader/site-admin cannot write terms/events, writer cannot alter schema, and the four roles do not inherit `neon_superuser`.
- [ ] **Step 5: Recheck legacy data and residue.** Confirm the six Trends counts are unchanged and no `radar_test_*` schema exists. If any invariant changes, stop before deployment and restore using Neon recovery rather than dropping tables.

### Task 5: Publish the Public Website Through the Existing Vercel Project

**Files:**
- Create/update: `docs/verification/2026-10-22-public-auto-radar-release.md`

**Interfaces:**
- Consumes: production reader and site-admin connection URLs from Task 4.
- Produces: the existing Vercel project's production URL with anonymous reads and same-origin site configuration writes.

- [ ] **Step 1: Inspect remote state.** Fetch GitHub; verify `origin/main` is an ancestor or reconcile normally, verify the current branch is clean and contains Tasks 1–3, and inspect the existing Vercel project's exact production domain/protection state. Never force-push.
- [ ] **Step 2: Configure Vercel server-side values.** Set production `RADAR_READ_DATABASE_URL`, `RADAR_SITE_ADMIN_DATABASE_URL`, and `RADAR_WEB_ALLOWED_ORIGINS` to the exact HTTPS production origin. Remove obsolete `RADAR_WEB_USERNAME` and `RADAR_WEB_PASSWORD_SHA256`; do not set writer or migrator credentials in Vercel.
- [ ] **Step 3: Push and publish normally.** Push the development branch, update `main` through a normal fast-forward/merge, and let the existing Vercel project build that exact commit.
- [ ] **Step 4: Verify anonymous production reads.** In a clean browser context, open `/`, switch among 总览/新词/竞品/设置, change dates, open a research card, and verify `/api/overview`, `/api/daily-terms`, `/api/competitors`, and `/api/settings/status` return `200` without login or redirects.
- [ ] **Step 5: Verify real settings writes without dummy residue.** Add `aiphotoeditor.com` only if absent, then pause and resume that same real site; verify cross-origin and malformed URL requests remain rejected. Do not create an undeletable fake competitor.
- [ ] **Step 6: Record evidence.** Add production deployment ID/commit, public URL, anonymous checks, settings result, and rollback deployment to the release verification document; omit all secret values.

### Task 6: Start Collection and Prove Both Manual and Scheduled Production Runs

**Files:**
- Modify: `docs/verification/2026-10-22-public-auto-radar-release.md`
- Modify: `docs/operations/platform.md` only if live behavior differs from the runbook.

**Interfaces:**
- Consumes: `free-radar-production` GitHub Environment containing only `RADAR_WRITE_DATABASE_URL`, and Task 2's workflow on `main`.
- Produces: real production source snapshots, a real competitor baseline, enabled future schedules, and evidence from at least one cron source run and one cron site run.

- [ ] **Step 1: Create the production Actions environment and writer secret.** Keep the repository variable `FREE_RADAR_ENABLED` absent or false; do not provide reader, site-admin, migrator, paid API, or Vercel secrets to the collector.
- [ ] **Step 2: Manually dispatch `sources` on `main`.** Require a successful Actions run, three source jobs (GitHub, HF Models, HF Spaces), production `radar_runs` evidence, and corresponding settings/new-word API output. A partial/incomplete run blocks schedule enablement.
- [ ] **Step 3: Manually dispatch `sites` on `main`.** Require a successful Actions run and a complete baseline for the real competitor. The first snapshot must produce zero URL-change events; a same-day duplicate launch must not create another effective snapshot.
- [ ] **Step 4: Enable cron.** Set the repository variable `FREE_RADAR_ENABLED=true` only after Steps 2–3 pass; confirm the old `RADAR_ENABLED` remains unset/false.
- [ ] **Step 5: Observe a scheduled source run.** After the next UTC `00:00`, `08:00`, or `16:00` trigger, verify the event type is `schedule`, the ref/commit is `main`, the environment is `free-radar-production`, Neon receives the expected run status, and the website reflects it.
- [ ] **Step 6: Observe a scheduled site run.** After the next UTC `01:30` trigger, verify the same production identity and confirm unchanged URLs create no events while failure/incomplete status would preserve the prior baseline. If more than 20 enabled sites exist, document the remainder as uncollected instead of zero.
- [ ] **Step 7: Run final verification and review.** Re-run `python -m pytest -q tests/test_radar.py tests/platform tests/e2e`; run a final branch diff review; verify no secret or local environment file is tracked.
- [ ] **Step 8: Commit and push release evidence.** Commit the sanitized verification record as `docs: record public radar production verification` and push it normally to `main` after confirming it contains no credentials.

## Rollback Trigger

If production writes to the wrong Neon branch, a collector advances an incomplete baseline, the public website still prompts for login, or either scheduled job repeatedly fails, immediately set `FREE_RADAR_ENABLED=false`, keep `RADAR_ENABLED` disabled, and roll Vercel back to the last known-good deployment. Preserve Neon tables and run history for diagnosis; do not drop or rewrite data as part of rollback.
