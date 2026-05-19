#!/bin/bash
# pull-mhbn-dump.sh — pg_dump loki's mhbn to beyla.
# Run on beyla as nthmost. Cron: daily at 03:00.
#
# Streams the dump over SSH; loki's postgres never opens to the network.
# Format = custom (-Fc) so pg_restore can do parallel/selective restore.

set -uo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/media/music-archive/backups}"
DEST="$BACKUP_ROOT/mhbn-dumps/daily"
LOG_DIR="$BACKUP_ROOT/logs"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/mhbn-$STAMP.dump"
LOG="$LOG_DIR/mhbn-dump.$(date +%Y%m%d).log"
LOCK="$BACKUP_ROOT/.lock-mhbn-dump"

mkdir -p "$DEST" "$LOG_DIR"

exec 9>"$LOCK"
if ! flock -n 9; then
    echo "[$(date -Is)] previous run still in progress, skipping" >> "$LOG"
    exit 0
fi

echo "[$(date -Is)] === dump start -> $OUT ===" >> "$LOG"

# pg_dump --format=custom is binary, compressed by default.
# Stream over SSH to keep the dump off loki's local disk (which is the host
# we're backing up — would be embarrassing to fill it with backups of itself).
ssh -o BatchMode=yes -J nthmost@149.28.77.210 nthmost@10.100.0.6 \
    'sudo -u postgres pg_dump -Fc mhbn' \
    > "$OUT.partial" 2>>"$LOG"
RC=$?

if [ $RC -ne 0 ] || [ ! -s "$OUT.partial" ]; then
    echo "[$(date -Is)] ERROR: pg_dump failed rc=$RC, removing partial" >> "$LOG"
    rm -f "$OUT.partial"
    exit "${RC:-1}"
fi

mv "$OUT.partial" "$OUT"
SIZE=$(du -h "$OUT" | cut -f1)
echo "[$(date -Is)] === done $SIZE ===" >> "$LOG"
