# Beyla mirror backup

Pull-model backup of zikzak's `/mnt/media` and loki's `mhbn` postgres
database to `beyla:/media/music-archive/max-headroom/backups/`. Single cron'd host
(beyla) coordinates both pulls — sources don't need to know about the
backup target.

## Topology

```
                            ┌─────────────────────────────────────┐
                            │   beyla  10.100.0.2 (via zephyr)    │
                            │                                     │
                            │   ┌──── cron 03:00 ────┐            │
                            │   │ pull-mhbn-dump.sh  │            │
                            │   │   ssh pipe pg_dump │ ──────────────────▶  loki:mhbn (sudo -u postgres)
                            │   │   custom format    │            │       (text2gene.org, 10.100.0.6)
                            │   └────────────────────┘            │
                            │                                     │
                            │   ┌──── cron 03:30 ────┐            │
                            │   │ pull-zikzak-media. │            │
                            │   │   rsync --delete   │ ◀────────────────── zikzak:/mnt/media
                            │   │   (mirror)         │            │       (10.100.0.5)
                            │   └────────────────────┘            │
                            │                                     │
                            │   ┌──── cron 04:00 ────┐            │
                            │   │ gfs-rotate.sh      │ (local hardlinks; no ssh)
                            │   │   daily->weekly->m │            │
                            │   └────────────────────┘            │
                            │                                     │
                            │   /media/music-archive/max-headroom/backups/     │
                            │     ├─ zikzak-media/   (mirror)     │
                            │     ├─ mhbn-dumps/                  │
                            │     │    ├─ daily/   (keep 7)       │
                            │     │    ├─ weekly/  (keep 4)       │
                            │     │    └─ monthly/ (keep 6)       │
                            │     └─ logs/                        │
                            └─────────────────────────────────────┘
```

Disk budget: media is ~120 GB at time of setup; weekly+monthly dumps are
~50 KB each (mhbn is schema-light, no media bytes); plenty of room on
the 4.6 TB `/media/music-archive/max-headroom` partition.

## Scripts (live in `scripts/beyla/` in this repo)

| Script | What | Schedule |
|---|---|---|
| `pull-mhbn-dump.sh` | Streams `pg_dump -Fc mhbn` over SSH from loki; writes to `daily/mhbn-<ts>.dump`. Lockfile prevents overlap. | 03:00 daily |
| `pull-zikzak-media.sh` | `rsync --delete` from zikzak's `/mnt/media` to `zikzak-media/`. Mirror semantics: beyla matches zikzak exactly. 20 MB/s bwlimit. Tolerates rsync rc=23/24 (metadata warnings — same cross-user pattern as the intake rsync). | 03:30 daily |
| `gfs-rotate.sh` | Hardlinks today's daily dump to `weekly/` on Mondays, to `monthly/` on the 1st. Prunes daily>7, weekly>4, monthly>6. | 04:00 daily |

Deployed at `/home/nthmost/bin/` on beyla. To update them, edit in this
repo and `scp scripts/beyla/*.sh nthmost@10.100.0.2:bin/`.

## Crontab

```
# Max Headroom backups (managed; see ~/bin/*.sh)
0 3  * * * /home/nthmost/bin/pull-mhbn-dump.sh
30 3 * * * /home/nthmost/bin/pull-zikzak-media.sh
0 4  * * * /home/nthmost/bin/gfs-rotate.sh
```

Output goes to `/media/music-archive/max-headroom/backups/logs/<script>.<YYYYMMDD>.log`,
plus systemd-journal whatever cron decides to forward (usually nothing
unless the script exits non-zero).

## Authentication

beyla's `nthmost` SSH key (`~/.ssh/id_ed25519.pub`) is authorized on:
- zephyr (jump host) — required for both pulls
- zikzak (target) — for `pull-zikzak-media.sh` rsync
- loki (target) — for `pull-mhbn-dump.sh` SSH pipe

The pg_dump runs as `postgres` via `sudo -u postgres` (NOPASSWD already
configured for nthmost on loki, used by intake's tunnel checks too).

## Restoring

### Database
```bash
# On any host with pg_restore + the dump file:
pg_restore --clean --if-exists -d mhbn /path/to/mhbn-YYYYMMDD-HHMMSS.dump
```

`pg_restore --list <dump>` shows what's inside; selective restore is
possible (`--data-only --table=jobs` etc).

### Media
```bash
# Reverse the rsync — beyla → zikzak. Be VERY sure about --delete
# semantics here (it would wipe new content on zikzak that hasn't yet
# been mirrored to beyla):
rsync -av --no-perms --no-owner --no-group --omit-dir-times \
      -e 'ssh -J nthmost@149.28.77.210' \
      /media/music-archive/max-headroom/backups/zikzak-media/ \
      nthmost@10.100.0.5:/mnt/media/
```

Without `--delete` it's purely additive (safe). With `--delete` it
restores beyla's snapshot exactly — only use for a full disaster
recovery.

## Monitoring

Daily log files are written even on success. To spot trouble:

```bash
ssh -J zephyr nthmost@10.100.0.2 '
  tail -5 /media/music-archive/max-headroom/backups/logs/mhbn-dump.$(date +%Y%m%d).log
  tail -5 /media/music-archive/max-headroom/backups/logs/zikzak-media.$(date +%Y%m%d).log
  ls /media/music-archive/max-headroom/backups/mhbn-dumps/{daily,weekly,monthly}/ | head
  du -sh /media/music-archive/max-headroom/backups/zikzak-media/
'
```

A healthy run shows `=== done <size> ===` in each log. The media log
also shows a file-count + total bytes. If rsync exits with a code other
than 0/23/24, the script logs an ERROR line and propagates the failure.

## Off-site / second-tier (not implemented)

Beyla is single-site. If you want disaster-recovery resilience beyond
"beyla's disk doesn't fail," nightly tarball the latest weekly mhbn
dump + a manifest-only of media → some second host (zephyr would work;
storage there is the constraint). Not built yet.
