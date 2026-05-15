# Testing architecture

Three-layer pyramid for the intake pipeline. Each layer skips itself when
its infra isn't reachable so the lower tiers stay usable in isolation.

```
                    ┌─────────────────────────────────────┐
                    │  e2e/                               │
                    │  full pipeline against headroom     │  minutes/job
                    │  loki -> dropbox -> watchdog -> DB  │
                    └────────────────────┬────────────────┘
                                         │ skips when headroom unreachable
                    ┌────────────────────┴────────────────┐
                    │  integration/                       │
                    │  db.py against mhbn_test on loki    │  ~1–5 s
                    └────────────────────┬────────────────┘
                                         │ skips when MHBN_TEST_DATABASE_URL unset
                    ┌────────────────────┴────────────────┐
                    │  unit/                              │
                    │  pure helpers, no infra             │  <1 s
                    └─────────────────────────────────────┘
```

## Why a test-pair?

The intake pipeline writes through to a postgres DB and pushes files to a
remote host that runs a watchdog. Both behaviors are central to its
correctness, and neither can be honestly mocked. Mocking the postgres calls
would skip the schema constraints that catch real bugs (`ON CONFLICT`,
`FOR UPDATE SKIP LOCKED`, default values). Mocking the watchdog would skip
the `pipeline_status` round-trip — the exact contract we care about.

So we provision a parallel "test pair": **loki (live) ↔ headroom (test target)**.
Loki keeps running production intake against zikzak; the test harness flips
two env vars to route a single job through headroom + `mhbn_test` instead.

Production is never touched.

## Topology

```
                    ┌─────────────────────────────────────────┐
                    │             loki.nthmost.net            │
                    │                                         │
                    │   intake.service ─────────────────────────────┐
                    │     │                                   │     │
                    │     │ (job from DB)                     │     │
                    │     ▼                                   │     │
                    │   downloader.run_job ─┬─────────────────┼─────┼─▶ zikzak (PROD)
                    │                       │                 │     │   :/mnt/dropbox
                    │   pytest run ─────────┘                 │     │
                    │     │                                   │     │
                    │     │ env override:                     │     │
                    │     │   ZIKZAK_HOST=10.100.0.4 ◀───────┐│     │
                    │     │   DATABASE_URL=…/mhbn_test       ││     │
                    │     ▼                                   │     │
                    │   downloader.run_job ─────────────────────────┼─▶ headroom (TEST)
                    │                                         │     │   :/mnt/dropbox
                    │   postgres                              │     │
                    │     ├─ mhbn (production)        ◀───────┘     │
                    │     └─ mhbn_test (e2e target)                 │
                    └─────────────────────────────────────────┘
                                                                    │
                    ┌─────────────────────────────────────────┐     │
                    │             headroom (TEST)             │ ◀───┘
                    │                                         │
                    │   dropbox-watchdog ──▶ /mnt/media/…     │
                    │     uses mhbn_test via loki-pg-tunnel:  │
                    │     127.0.0.1:5436 → loki:5432          │
                    └─────────────────────────────────────────┘
```

Same source tree on both sides — only inventory vars differ.

## What's where

| File | Purpose |
|------|---------|
| `intake/tests/unit/*.py` | Pure-helper coverage. Runs anywhere, no infra. |
| `intake/tests/integration/test_db.py` | `db.py` round-trips against `mhbn_test`. |
| `intake/tests/e2e/test_{ia,youtube}_pipeline.py` | Full pipeline through headroom. |
| `intake/tests/conftest.py` | sys.path shim so tests can `import db` directly. |
| `intake/tests/{integration,e2e}/conftest.py` | Per-layer fixtures + skip guards. |
| `intake/pytest.ini` | Markers: `integration`, `e2e`. |
| `scripts/setup-mhbn-test-db.sh` | Loki-side: create `mhbn_test`, clone schema. |
| `ansible/playbooks/headroom.yml` | Deploys the test target. |

## Setup

**One-time, on loki:**

```bash
./scripts/setup-mhbn-test-db.sh
```

This creates `mhbn_test` and clones the schema from `mhbn`. Idempotent —
re-running drops/recreates `mhbn_test` but never touches prod.

**One-time, from your workstation (deploys headroom):**

```bash
cd ansible
ansible-playbook playbooks/headroom.yml
```

After the playbook runs, headroom has `/mnt/dropbox/`, `/mnt/media/`,
the `loki-pg-tunnel` reaching `mhbn_test`, and the `dropbox-watchdog`
filing into `/mnt/media/<category>/<length>/`.

**Per-session, on loki when running tests:**

```bash
export MHBN_TEST_DATABASE_URL=postgresql://mhbn:***@127.0.0.1:5432/mhbn_test
export HEADROOM_HOST=10.100.0.4
export HEADROOM_USER=nthmost
export HEADROOM_JUMP=zephyr
cd intake
python -m pytest tests/         # everything
python -m pytest tests/unit     # ~1 s, no infra
python -m pytest tests/integration  # ~5 s
python -m pytest tests/e2e -v   # minutes
```

## Cleanup contract

Every test that touches DB rows or remote files uses the `clean_e2e_state`
or `clean_jobs` fixture, which sweeps both *before* and *after* the test
runs. If a Ctrl-C aborts mid-run, the next test's setup wipes the
leftovers — no manual cleanup needed.

The cleanup targets are scoped narrowly:
- DB: rows with `category='zzz_test'` or `url LIKE 'test://%'` only
- Headroom: files matching `<digits>__*` in `/mnt/dropbox/` (job-id prefix
  pattern that the production pipeline also produces) and the whole
  `/mnt/media/zzz_test/` subtree

Nothing outside those patterns is ever touched.

## What's NOT covered

- **Liquidsoap encoding correctness** — the e2e tests stop at "file landed
  in mhbn with pipeline_status='live'". Encoded HLS output is verified
  visually on the actual broadcast pipeline, not in CI.
- **Network failures mid-rsync** — we trust autossh + rsync's `--partial`;
  no chaos-style test.
- **Concurrent submissions through `intake.py` Flask routes** — single-job
  e2e only. The DB-side `FOR UPDATE SKIP LOCKED` is exercised by the
  integration tests.
