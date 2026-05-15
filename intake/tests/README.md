# intake/ tests

Three layers, picked by directory:

| Layer | Path | Speed | Infra needed |
|-------|------|-------|--------------|
| **unit** | `tests/unit/` | <100 ms total | none — pure-Python helpers |
| **integration** | `tests/integration/` | ~1–5 s | postgres reachable at `MHBN_TEST_DATABASE_URL` |
| **e2e** | `tests/e2e/` | ~minutes/job | full headroom test-pair pipeline (WG, SSH, ffmpeg, etc.) |

## Running

From `intake/`:

```bash
# Unit only (default, runs in CI / pre-commit)
pytest tests/unit

# Integration — needs a populated mhbn_test schema on loki:
export MHBN_TEST_DATABASE_URL=postgresql://mhbn:***@127.0.0.1:5435/mhbn_test
pytest tests/integration

# E2E — needs intake configured to push to headroom (see e2e/conftest.py).
# These will hit YouTube / Internet Archive for real downloads and require
# the headroom test target to be deployed (see ansible/playbooks/headroom.yml).
pytest tests/e2e
```

`pytest tests/` runs everything; layers will skip themselves if their infra isn't reachable.

## Setting up the test DB on loki

```bash
sudo -u postgres createdb mhbn_test
sudo -u postgres pg_dump --schema-only mhbn | sudo -u postgres psql mhbn_test
sudo -u postgres psql -c "GRANT ALL ON ALL TABLES IN SCHEMA public TO mhbn;" mhbn_test
sudo -u postgres psql -c "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO mhbn;" mhbn_test
```

## Test data — known-safe identifiers

These are picked to be short, always-available, license-clean:

| Source | id | Why |
|--------|----|------|
| IA short  | `Popeye_forPresident_512kb` | ~5 MB transcoded, ~1 min runtime, public domain |
| IA medium | `prelinger-1953`           | from existing prelinger archive |
| YouTube   | `https://www.youtube.com/watch?v=BHACKCNDMW8` | Big Buck Bunny trailer, CC-BY |

E2E test cleanup is mandatory — fixtures always purge after themselves.
