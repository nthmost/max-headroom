# Enki backup (mhbn pg_dumps, with zikzak side-mirror)

Second, independent copy of loki's `mhbn` postgres DB, kept on enki at
`~/backups/mhbn-dumps/` and side-mirrored to zikzak. Runs alongside (not
in place of) the beyla pulls in [beyla-backup.md](./beyla-backup.md) —
two unrelated chains so a failure on one host doesn't compromise both.

## Topology

```
                          ┌──────────────────────────────────────┐
                          │  enki  10.21.1.136 / wg 10.100.0.4   │
                          │                                      │
                          │  ┌──── cron 02:00 ────┐              │
                          │  │ pull-mhbn-dump.sh  │ ───ssh───▶  loki:mhbn (sudo -u postgres)
                          │  │   ssh pipe pg_dump │             (text2gene.org over WG)
                          │  │   -Fc custom       │
                          │  └────────────────────┘
                          │                                      │
                          │  ┌──── cron 02:15 ────┐              │
                          │  │ push-mhbn-to-     │ ───rsync───▶ zikzak:~/backups/mhbn-from-enki/
                          │  │   zikzak.sh       │              (via NB LAN, zikzak.local)
                          │  └────────────────────┘              │
                          │                                      │
                          │  ┌──── cron 02:30 ────┐              │
                          │  │ gfs-rotate.sh      │ (local hardlinks)
                          │  │   daily→weekly→m   │              │
                          │  └────────────────────┘              │
                          │                                      │
                          │  ~/backups/                          │
                          │   ├─ mhbn-dumps/                     │
                          │   │   ├─ daily/   (keep 7)           │
                          │   │   ├─ weekly/  (keep 4)           │
                          │   │   └─ monthly/ (keep 6)           │
                          │   └─ logs/                           │
                          └──────────────────────────────────────┘
```

Cron times are offset 1 hour earlier than beyla so the two hosts don't
hammer loki simultaneously. Beyla still runs the canonical media rsync
and its own mhbn pull — nothing here replaces that.

## Scripts (live in `scripts/enki/` in this repo)

| Script | What | Schedule |
|---|---|---|
| `pull-mhbn-dump.sh` | Streams `pg_dump -Fc mhbn` from loki over SSH; writes to `~/backups/mhbn-dumps/daily/mhbn-<ts>.dump`. Lockfile prevents overlap. | 02:00 daily |
| `push-mhbn-to-zikzak.sh` | rsyncs the newest daily dump to zikzak; prunes zikzak to most-recent 7. | 02:15 daily |
| `gfs-rotate.sh` | Hardlinks today's daily into `weekly/` on Mondays, `monthly/` on the 1st. Prunes daily>7, weekly>4, monthly>6. | 02:30 daily |

Deployed at `~/bin/` on enki. To update: edit here, `scp scripts/enki/*.sh nthmost@enki:bin/`.

## Crontab (enki, user nthmost)

```
# Max Headroom backups — second copy (see docs/runbooks/enki-backup.md)
0  2 * * * /home/nthmost/bin/pull-mhbn-dump.sh
15 2 * * * /home/nthmost/bin/push-mhbn-to-zikzak.sh
30 2 * * * /home/nthmost/bin/gfs-rotate.sh
```

## Authentication

Enki's `nthmost` SSH key (`~/.ssh/id_ed25519.pub`) is authorized on:
- **loki** — for the SSH pipe pg_dump (NOPASSWD sudo to `postgres` already
  configured via the same mechanism beyla uses)
- **zikzak** — for the rsync push (added 2026-05-20)

Enki reaches loki via its `Host loki` SSH alias (HostName `text2gene.org`,
routes over WG to 10.100.0.6). Enki reaches zikzak via `zikzak.local`
mDNS over the NB LAN — WG (10.100.0.5) is configured but the route is
not reachable from enki, so don't switch back to it without testing.

## Zikzak side

Zikzak just holds a flat stash of recent dump files at
`~/backups/mhbn-from-enki/`. No rotation logic of its own; the push
script prunes to the most-recent 7. Nothing on zikzak reads these
today — they're a third-location stash in case both loki and enki are
lost. If zikzak ever needs to query the data, revisit the question of a
live postgres replica then.

## Restoring

```
# pick the dump you want
ls -la ~/backups/mhbn-dumps/{daily,weekly,monthly}/

# restore to a scratch DB on the same host (or wherever)
createdb mhbn_restore
pg_restore -d mhbn_restore --no-owner --no-privileges \
    ~/backups/mhbn-dumps/daily/mhbn-YYYYMMDD-HHMMSS.dump
```

## Verifying it ran

```
tail ~/backups/logs/mhbn-dump.$(date +%Y%m%d).log
tail ~/backups/logs/push-zikzak.$(date +%Y%m%d).log
tail ~/backups/logs/gfs-rotate.$(date +%Y%m%d).log
ls -la ~/backups/mhbn-dumps/daily/ | tail
ssh zikzak ls -la ~/backups/mhbn-from-enki/
```
