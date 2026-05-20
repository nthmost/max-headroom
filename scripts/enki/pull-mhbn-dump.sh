#!/bin/bash
# pull-mhbn-dump.sh — pg_dump loki's mhbn to enki.
# Run on enki as nthmost. Cron: daily at 02:00.
#
# Second, independent copy alongside beyla's nightly pull (which runs 03:00).
# Enki has direct WG access to loki (no jump host needed).
# Streams over SSH; loki's postgres never opens to the network.
# Format = custom (-Fc) so pg_restore can do parallel/selective restore.

set -uo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/backups}"
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

ssh -o BatchMode=yes loki \
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
