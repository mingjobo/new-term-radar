# GitHub / Hugging Face → Neon verification

Date: 2026-10-15 UTC. Target: Neon project `wandering-bonus-68047611`, branch `dev-free-platform` (`br-icy-hill-aqlxwahb`). No production database was used.

## Offline rules

`tests/platform/test_github.py`, `test_huggingface.py`, `test_runner.py`, and `test_probe.py` passed 22 tests. They cover:

- HF first-run top-100 baselines, top-50 entry detection, same-slot idempotency, changed/empty payload protection, distinct model/demo/quantized identities, and explicit aliases.
- GitHub 14-day / 300-star / 200-per-day thresholds, nearest 20–28-hour delta selection, rejection of an 8-hour delta as a daily delta, 48-hour count retention, and empty/truncated response protection.
- Runner success, incomplete result, collection failure, write failure and five-minute retry behavior.
- Probe source expansion and non-sensitive structural summaries.

The isolated-database ingest test then injected a successful collection followed by a write failure. Source state remained at version zero; HF committed independently; retrying GitHub produced exactly one term and one evidence row. A separate incomplete response recorded an `incomplete` run without changing source state.

## Live structure probe

Command shape:

```bash
python scripts/platform_probe.py \
  --sources github,hf \
  --max-requests 8 \
  --out artifacts/probes/free-sources.json
```

At `2026-10-15T10:30:47Z`, the probe used four requests:

| Source | Result | Complete items | Discoveries |
|---|---:|---:|---:|
| GitHub breakout | ok | 187 / 187 | 45 |
| HF Models | baseline | 100 | 0 |
| HF Spaces | baseline | 100 | 0 |

HF zero discoveries are expected on the first run: the first complete top-100 response establishes its baseline. This run validates response shape, not a later real top-50 transition.

## Live development write and repeat

The same probe was run with explicit `--write-test-db` and the development writer role. It committed:

- 45 GitHub terms and 45 evidence rows in one source transaction;
- GitHub source state version 1 with 187 retained count observations;
- HF Models and HF Spaces source state version 1 with 100 IDs each and no false first-run terms;
- three complete jobs and three run records.

Repeating in the same probe slot made zero HTTP requests and returned `already_processed` for all three source instances. Database counts remained `terms=45`, `evidence=45`, `source_states=3`, `jobs=3`, `runs=3`. This proves slot idempotency; a real HF new-entry difference still requires a later observation.

Sample stored evidence links resolved to GitHub repositories and retained the actual repository ID, star count, collection time, URL and description. No `radar_test_*` schemas remained after verification.

