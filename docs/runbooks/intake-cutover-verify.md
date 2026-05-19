# Intake cutover verification

Pattern for high-risk service deploys (this repo's `intake.service` lives
in this category — it's the user-facing web app, restart-during-deploy is
visible). Used during the 2026-05-18 cutover that swapped the live
`intake.service` from system-python + `--user` pip to a venv-python path
via the `intake-app` ansible role.

The point: **"service is active" is necessary but not sufficient.** The
following 12 checks plus a single live job submission proves the deploy
end-to-end without involving a human user clicking around.

## Pre-flight (capture baseline)

```bash
ssh <host> '
  systemctl show -p MainPID -p ExecStart intake
  curl -sf -m 5 http://localhost:8765/api/categories | jq length
  curl -sf -m 5 http://localhost:8765/api/recent     | jq length
  sudo -u postgres psql mhbn -tAc "SELECT COUNT(*) FROM categories WHERE is_tag_only=FALSE"
'
```

Save: pre-deploy `MainPID`, current `/api/categories` count via HTTP,
current `/api/recent` count, and the direct DB count for categories.

## Deploy

```bash
ansible-playbook playbooks/loki.yml
```

## Post-flight (each must pass)

| # | Check | What it proves |
|---|---|---|
| 1 | `systemctl is-active intake` = `active` after 5s | Unit didn't crashloop |
| 2 | `MainPID` ≠ pre-deploy pid | Service actually restarted (not reloaded) |
| 3 | `ExecStart` contains `/home/max/intake/venv/bin/python` (or current target) | New systemd unit took effect |
| 4 | `readlink /proc/$PID/exe` → expected python (system or venv) | Right interpreter running |
| 5 | `journalctl -u intake --since "2 min ago"` has no `ERROR`/`Traceback`/`Exception` | Clean startup |
| 6 | `curl -sf http://localhost:8765/` → 200 | Flask + index template + DB query path |
| 7 | `curl -sf /api/categories` length == pre-deploy | DB connection is the **same DB** (not a test DB by accident) |
| 8 | `curl -sf /api/queue` → JSON | DB read via worker code path |
| 9 | `curl -sf /api/recent` → JSON length == pre-deploy | Recent-jobs view works |
| 10 | `curl -sf -X POST -d '{"source":"ia","url":""}' /api/quickmeta` → 400 with `error` key | POST + JSON parsing + validation |
| 11 | Wait 60s; re-check is-active + MainPID unchanged | Service is **stable**, not flapping |
| 12 | `pgrep -c -f intake.py` = 1 | No leftover old process |

## Live job test (belt-and-suspenders)

The above proves the deploy is correct; the following proves the
pipeline actually works against production:

```bash
# Submit (Popeye-for-President is small + always available on archive.org)
curl -sf -X POST -H "Content-Type: application/json" \
  -d '{"source":"ia","urls":["PopeyeForPresident1956"],
       "category":"cartoons","length":"short","crop_sides":false}' \
  http://localhost:8765/api/submit

# Note the returned job_id (e.g. 65). Then poll:
JID=65
for i in $(seq 1 60); do
  STATE=$(psql -h 127.0.0.1 -p 5435 -U mhbn -d mhbn -tAc \
    "SELECT status||'/'||COALESCE(pipeline_status,'NULL')||'/'||COALESCE(filename,'') FROM jobs WHERE id=$JID")
  echo "[$i] $STATE"
  case "$STATE" in
    *"done/live/"*) break ;;
    "failed/"*) echo FAILED; break ;;
  esac
  sleep 5
done

# Verify file landed on zikzak
ssh -J zephyr nthmost@10.100.0.5 \
  "ls -la '/mnt/media/cartoons/short/Popeye for President (1956).mp4'"

# Cleanup
curl -sf -X POST http://localhost:8765/api/job/$JID/purge
```

Total: ~60s test job, full pipeline exercised. The file briefly appears in
the broadcast pool — liquidsoap's random sampler is unlikely to pick it in
that window. If you want a zero-impact test, redirect to the headroom
test target instead (see `testing-architecture.md`).

## Rollback

If checks 1–12 reveal a problem:

```bash
# Stop the broken unit
sudo systemctl stop intake

# Revert the role + redeploy (preferred — keeps ansible state authoritative)
cd ~/projects/git/max-headroom
git revert <bad-commit>
cd ansible && ansible-playbook playbooks/loki.yml

# Or, if ansible itself is the problem, restore the previous systemd unit
# from /etc/systemd/system/intake.service.NNNNN (ansible's backup=yes leaves
# numbered backups). Then daemon-reload + start.
```

## Pre-existing infrastructure pitfalls

The 2026-05-18 cutover surfaced two latent issues that have nothing to
do with the deploy itself but block the live test job:

- **max user's `~/.ssh/known_hosts` had a stale zikzak host key** from
  before zikzak's drive rebuild. The intake worker SSHes from loki to
  zikzak via zephyr; SSH refused due to host-key mismatch. Fix:
  `sudo -u max ssh-keygen -R 10.100.0.5` then re-keyscan.
- **max user's pubkey wasn't authorized** on zephyr (jump host) and
  zikzak (target) post-rebuild. Push it to both.

Any time a host is rebuilt or its host key rotates, re-validate that
`sudo -u max ssh -J zephyr nthmost@<host>` works from loki before
running a live test job. The 12 deploy checks don't surface these —
they only show up under the actual `run_job` execution path.
