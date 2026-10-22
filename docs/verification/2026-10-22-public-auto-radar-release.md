# Public radar release verification — 2026-10-22

## New Neon database gate

- User-selected new Neon Free project: `new-term-radar` / `curly-breeze-91368134` (AWS US East 2). The old `keyword-detective` project was neither copied nor deleted.
- Production branch: `production` / `br-jolly-brook-b53hsuhn`. Isolated test branch: `dev-validation` / `br-polished-forest-b5k2xxcy` (expires 2026-10-23 12:58 Beijing time).
- Before initialization, the production public schema had zero `radar_*` tables. After applying the unchanged migration files `001`–`005`, the production branch has 13 `radar_*` tables and five migration records. A second migration run applied zero files.
- Production `radar_terms` and `radar_sites` both have zero rows; there are no `radar_test_*` schemas. No old data was imported.
- SQL-created reader, writer, migrator, and site-admin roles are not members of `neon_superuser`. Grant checks passed: reader cannot insert terms; writer can insert terms but cannot insert sites; site-admin can insert sites but cannot insert terms. All four roles logged in successfully after credential rotation.
- Production role connection URLs are stored only in the local macOS Keychain under service names `new-term-radar/neon/production/<role>`. They are not in Git, CI logs, or browser code.
- The `free-radar-production` GitHub environment now contains only `RADAR_WRITE_DATABASE_URL` for the writer role. Repository-level `FREE_RADAR_ENABLED` remains unset, so scheduled collection is off.

## Tests

- Local application tests: `python3 -m pytest -q tests/test_radar.py tests/platform tests/e2e` → **212 passed**.
- GitHub-hosted isolated Neon integration run: [Actions run 39742226957](https://github.com/mingjobo/new-term-radar/actions/runs/39742226957) → **40 passed in 152.26 seconds**, no skips. This run used only `dev-validation` credentials from the `free-radar-dev` environment. The test guard rejects the known production endpoint.
- GitHub push tests for Python 3.10 and 3.12: [Actions run 39742206945](https://github.com/mingjobo/new-term-radar/actions/runs/39742206945) → both jobs passed.
- The earlier local integration runs were not treated as a release gate because the local proxy/tunnel intermittently broke PostgreSQL connections. The successful GitHub-hosted run is the release gate.

## Remaining release gates

- Configure the existing Vercel project's Production-only reader and site-admin environment variables plus exact allowed HTTPS origin; remove old login variables. Do not place writer or migrator connections in Vercel.
- Update `main` normally, confirm a successful production deployment, and verify public GETs and same-origin settings writes.
- After the site is live, manually run sources and sites with the prepared `free-radar-production` environment. Enable `FREE_RADAR_ENABLED=true` only after both modes succeed and the dashboard reflects the results.
- Observe at least one scheduled source run and one scheduled site run before calling the full automatic-collection release complete.
