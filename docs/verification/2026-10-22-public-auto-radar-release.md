# Public radar release verification — 2026-10-22

## New Neon database gate

- User-selected new Neon Free project: `new-term-radar` / `curly-breeze-91368134` (AWS US East 2). The old `keyword-detective` project was neither copied nor deleted.
- Production branch: `production` / `br-jolly-brook-b53hsuhn`. Isolated test branch: `dev-validation` / `br-polished-forest-b5k2xxcy` (expires 2026-10-23 12:58 Beijing time).
- Before initialization, the production public schema had zero `radar_*` tables. After applying the unchanged migration files `001`–`005`, the production branch has 13 `radar_*` tables and five migration records. A second migration run applied zero files.
- Before launch, production `radar_terms` and `radar_sites` both had zero rows; there were no `radar_test_*` schemas. No old data was imported. The verified production collectors have since populated the new database.
- SQL-created reader, writer, migrator, and site-admin roles are not members of `neon_superuser`. Grant checks passed: reader cannot insert terms; writer can insert terms but cannot insert sites; site-admin can insert sites but cannot insert terms. All four roles logged in successfully after credential rotation.
- Production role connection URLs have local backups in macOS Keychain under service names `new-term-radar/neon/production/<role>`. The reader and site-admin URLs are also stored in Vercel Production, and the writer URL in the GitHub production environment. None are in Git, CI logs, or browser code.
- The `free-radar-production` GitHub environment contains only `RADAR_WRITE_DATABASE_URL` for the writer role. Repository-level `FREE_RADAR_ENABLED` was switched to `true` at 2026-10-22 09:19 UTC, after both manual collector modes succeeded. Legacy `RADAR_ENABLED` remains unset.

## Tests

- Local application tests after the coverage fixes: `python3 -m pytest -q tests` → **219 passed, 36 skipped**. The skipped cases require isolated Neon test credentials not exposed to the local process; the isolated integration suite passed in GitHub Actions below.
- GitHub-hosted isolated Neon integration run: [Actions run 39742226957](https://github.com/mingjobo/new-term-radar/actions/runs/39742226957) → **40 passed in 152.26 seconds**, no skips. This run used only `dev-validation` credentials from the `free-radar-dev` environment. The test guard rejects the known production endpoint.
- Follow-up isolated Neon integration run for commit `792cf3b`: [Actions run 39756446550](https://github.com/mingjobo/new-term-radar/actions/runs/39756446550) → **42 passed in 131.93 seconds**, no skips. It verified old site jobs expire without consuming the next day's allowance and that a later source failure makes the day's zero count unconfirmed.
- GitHub push tests for Python 3.10 and 3.12: [Actions run 39742206945](https://github.com/mingjobo/new-term-radar/actions/runs/39742206945) → both jobs passed.
- The earlier local integration runs were not treated as a release gate because the local proxy/tunnel intermittently broke PostgreSQL connections. The successful GitHub-hosted run is the release gate.

## Public website and collector verification

- Existing Vercel project: `mingjobos-projects/new-term-radar`. Production-only `RADAR_READ_DATABASE_URL` points to the new Neon reader; Production-only `RADAR_SITE_ADMIN_DATABASE_URL` points to the new Neon site-admin role; `RADAR_WEB_ALLOWED_ORIGINS=https://new-term-radar.vercel.app`. Writer and migrator connections were not added to Vercel. The obsolete `RADAR_WEB_USERNAME` and `RADAR_WEB_PASSWORD_SHA256` variables remain stored but are ignored by the deployed no-login code; removing those legacy secrets is optional cleanup, not a functional release gate.
- `origin/main` was an ancestor of the development branch. Main was updated by normal fast-forward to commit `7e5a7b9`, without force-pushing. Vercel Production deployment `J7PEFCtSGYmLn16PxTvMEA8VX3Ap` was Ready. Public address: https://new-term-radar.vercel.app/ .
- Unauthenticated `/`, `/api/overview`, `/api/daily-terms`, `/api/competitors`, and `/api/settings/status` returned HTTP 200; the website showed its overview, new-term board, competitor board, settings, and a real new-term research card without a login prompt. Missing-Origin and foreign-Origin POST requests to `/api/settings/sites` both returned HTTP 403; a same-origin request naming a loopback URL returned HTTP 400 and created no site.
- The real competitor `AI Photo Editor` (`aiphotoeditor.com`) was added through the website, paused, and restored. It remained the only configured site; no dummy competitor was left behind.
- [Production source run 39754013099](https://github.com/mingjobo/new-term-radar/actions/runs/39754013099) completed successfully on `main` using `free-radar-production`: 3 source jobs, 40 new terms, 5 HTTP requests, no errors. The settings API showed GitHub with a complete 246-item snapshot and 40 new terms; Hugging Face Models and Spaces each established a complete 100-item first baseline. The public overview and new-term board showed 40 new terms and 40 clues for 2026-10-22 Beijing time.
- [Production site run 39754059887](https://github.com/mingjobo/new-term-radar/actions/runs/39754059887) completed successfully: 1 site job, 2 HTTP requests, no errors. `aiphotoeditor.com` established a complete 139-URL first baseline; the competitor board showed zero added and zero removed URLs, as expected on first observation. [Same-day repeat run 39754240125](https://github.com/mingjobo/new-term-radar/actions/runs/39754240125) completed with 0 jobs and 0 requests, leaving the baseline timestamp unchanged.
- Independent code review found two coverage edge cases. Commit `792cf3b` fixes both: with more than 20 sites, missed prior-day jobs are retired before today's 20-job crawl budget; and a later failed source slot makes overview counts unknown instead of confirming zero. A 21-site, two-day unit test and the isolated database tests cover these paths.
- Repository variable `FREE_RADAR_ENABLED=true` was read back after setting it. The workflow's source cron is UTC 00:00, 08:00, and 16:00 (Beijing 08:00, 16:00, and 00:00 next day); the site cron is UTC 01:30 (Beijing 09:30).

## Remaining observation

- The manual end-to-end chain and schedule switch are verified. No post-enable `schedule` event has occurred yet as of this record. Observe the next source and site scheduled runs before claiming that unattended cadence has been verified in production.
- To stop automatic collection if a later run fails, set repository variable `FREE_RADAR_ENABLED=false`; do not delete Neon tables or snapshots. Vercel's deployment history and normal Git history provide the website rollback path.
