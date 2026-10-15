# Gate A dashboard verification

Date: 2026-10-15 Asia/Shanghai. Target: Neon project `keyword-detective`, isolated branch `dev-free-platform` (`br-icy-hill-aqlxwahb`).

## Automated boundary checks

`tests/platform/test_web.py` passed 13 tests. The suite verifies that every page, API and static route requires Basic Auth; correct credentials allow only GET/HEAD; refresh/research POST routes return 405; the web process requires `RADAR_READ_DATABASE_URL` and never falls back to writer/legacy URLs; term limits, sort values and cursors stay bounded; untrusted text is inserted with `textContent`; and non-HTTP evidence URLs are not rendered as links.

`tests/platform_integration/test_readonly.py` passed against a unique schema on the development branch. A writer seeded one term and one evidence record, `ReadQueries` returned both through the reader role, and PostgreSQL rejected a reader INSERT with `InsufficientPrivilege`.

## Browser-to-database chain

The local WSGI preview used only the development reader URL. The browser displayed:

| Visible value | Page | Database |
|---|---:|---:|
| New names today | 45 | 45 |
| Evidence today | 45 | 45 |
| Sources online | 3 | 3 |
| GitHub snapshot | 187 | 187 |
| HF Models baseline | 100 | 100 |
| HF Spaces baseline | 100 | 100 |

The first research card was `dsh ops`. Its detail view showed one `github:breakout` evidence record, repository ID `1409893258`, 2,017 stars, the stored excerpt and a link back to `https://github.com/T-Auto/dsh-ops`. Browser error and warning logs were empty.

The local reference server is intentionally single-threaded, so its three parallel home API calls are served one after another when Neon resumes. This affected local wait time only; the final rendered values and authorization behavior were correct.

## Gate A result

The requested chain is complete on the isolated branch: bounded free GitHub/Hugging Face collection, transactional Neon persistence, database-enforced reader access, and an authenticated read-only web dashboard with traceable evidence links. HF currently shows a real top-100 baseline; a later observation is still required to prove a live top-50 entrant difference.
