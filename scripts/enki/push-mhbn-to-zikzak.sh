#!/bin/bash
# push-mhbn-to-zikzak.sh — copy newest mhbn dump from enki to zikzak.
# Run on enki as nthmost. Cron: daily at 02:15 (after pull-mhbn-dump.sh).
#
# Zikzak gets a flat mirror of enki's daily/ — no rotation on zikzak's side.
# Use a temp filename + atomic rename so a partial transfer is never visible
# as the "latest" dump.

set -uo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/backups}"
SRC_DIR="$BACKUP_ROOT/mhbn-dumps/daily"
ZIKZAK_DEST="${ZIKZAK_DEST:-/home/nthmost/backups/mhbn-from-enki}"
LOG="$BACKUP_ROOT/logs/push-zikzak.$(date +%Y%m%d).log"
LOCK="$BACKUP_ROOT/.lock-push-zikzak"

mkdir -p "$(dirname "$LOG")"

exec 9>"$LOCK"
if ! flock -n 9; then
    echo "[$(date -Is)] previous run still in progress, skipping" >> "$LOG"
    exit 0
fi

LATEST=$(ls -1t "$SRC_DIR"/mhbn-*.dump 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    echo "[$(date -Is)] no dump to push, skipping" >> "$LOG"
    exit 0
fi

echo "[$(date -Is)] === push start: $LATEST -> zikzak:$ZIKZAK_DEST ===" >> "$LOG"

ssh -o BatchMode=yes zikzak "mkdir -p '$ZIKZAK_DEST'" 2>>"$LOG"

# rsync handles temp-naming + atomic rename. --bwlimit keeps NB LAN polite.
rsync -a --bwlimit=20000 \
    -e "ssh -o BatchMode=yes" \
    "$LATEST" \
    "zikzak:$ZIKZAK_DEST/" \
    >>"$LOG" 2>&1
RC=$?

# Also prune zikzak to the most recent 7 — zikzak is a stash, not a vault.
ssh -o BatchMode=yes zikzak \
    "ls -1t '$ZIKZAK_DEST'/mhbn-*.dump 2>/dev/null | tail -n +8 | xargs -r rm -f" \
    >>"$LOG" 2>&1 || true

if [ $RC -ne 0 ]; then
    echo "[$(date -Is)] ERROR: rsync failed rc=$RC" >> "$LOG"
    exit "$RC"
fi

echo "[$(date -Is)] === push done ===" >> "$LOG"
