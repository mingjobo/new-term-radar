# Vercel preview verification — 2026-10-16

## Scope

This verifies the early read-only deployment slice requested after Gate A. It does not mark Tasks 5–9 complete: sitemap/GSC collection, phrase extraction, scheduling, reports, production cutover and the 14-day observation period remain planned.

## Target

| Item | Verified value |
|---|---|
| Vercel project | `new-term-radar` on Hobby |
| Git branch | `codex/free-keyword-platform` |
| Verified commit | `83b632e868d24fb2acc92cf54986dfb6fac4d555` |
| Stable preview alias | `https://new-term-radar-git-codex-free-keyword-b14d3b-mingjobos-projects.vercel.app` |
| Neon project/branch | `keyword-detective` / `dev-free-platform` |
| Database role | pooled `radar_platform_reader` only |

## Deployment findings and fixes

1. Vercel selected `pyproject.toml` for dependency installation, so the older nested `requirements.txt` declaration did not install `psycopg`. Commit `412a45e` declares the locked runtime dependency in the file Vercel actually reads and adds a regression test.
2. Current Vercel Python routing passes the rewritten destination path to backend applications. The old catch-all rewrite therefore turned `/` into `/api/index.py`. Commit `83b632e` selects `api.index:app` explicitly and uses native WSGI routing, with a regression test that forbids the obsolete rewrite.

## Evidence

- Local deployment and platform regression suite: `149 passed in 0.52s`.
- Vercel deployment status: Ready; build duration 10 seconds.
- Browser home page: 3 sources online, 0 failed sources, and 45 saved terms.
- Source cards: GitHub baseline 187; Hugging Face models baseline 100; Hugging Face spaces baseline 100.
- Browser detail page: `dsh ops` returned one GitHub evidence record, original source link, 2,017 stars, repository ID and observed time.
- Browser console: no warning or error entries after loading the home and detail pages.
- Address bar was returned to a credential-free URL after authentication; no database URL or plaintext website password was committed.

## Remaining limits

- This is a preview deployment and requires the signed-in Vercel account before application Basic Auth.
- The displayed data is the verified baseline collected on 2026-10-15; automatic recurring collection is not enabled yet.
- Production domain and default branch are intentionally untouched.
