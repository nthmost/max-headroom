#!/bin/bash
# gfs-rotate.sh — Grandfather-Father-Son rotation for mhbn pg_dumps.
# Run on beyla as nthmost. Cron: daily at 04:00 (after the dump completes).
#
# Policy:
#   daily/   keep most-recent 7
#   weekly/  promote one per ISO week (Mondays), keep 4
#   monthly/ promote one per calendar month (first of month), keep 6
#
# We use hardlinks where possible (same filesystem) so promotion is free.
# When the daily falls off the 7-day window, it's still preserved via the
# weekly/monthly links until those rotate too.

set -uo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/media/music-archive/backups}"
DAILY="$BACKUP_ROOT/mhbn-dumps/daily"
WEEKLY="$BACKUP_ROOT/mhbn-dumps/weekly"
MONTHLY="$BACKUP_ROOT/mhbn-dumps/monthly"
LOG="$BACKUP_ROOT/logs/gfs-rotate.$(date +%Y%m%d).log"

mkdir -p "$DAILY" "$WEEKLY" "$MONTHLY"

log() { echo "[$(date -Is)] $*" >> "$LOG"; }

# Find the newest daily dump from today (or most recent if cron lags)
LATEST=$(ls -1t "$DAILY"/mhbn-*.dump 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    log "no daily dump found, nothing to rotate"
    exit 0
fi

DOW=$(date +%u)        # 1=Mon ... 7=Sun
DOM=$(date +%d)        # 01..31
ISOWEEK=$(date +%G-W%V) # e.g. 2026-W20
MONTH=$(date +%Y-%m)    # e.g. 2026-05

# Monday → promote to weekly (hardlink, free)
if [ "$DOW" = "1" ]; then
    DEST="$WEEKLY/mhbn-${ISOWEEK}.dump"
    if [ ! -e "$DEST" ]; then
        ln "$LATEST" "$DEST"
        log "promoted $LATEST -> $DEST"
    fi
fi

# 1st of month → promote to monthly (hardlink)
if [ "$DOM" = "01" ]; then
    DEST="$MONTHLY/mhbn-${MONTH}.dump"
    if [ ! -e "$DEST" ]; then
        ln "$LATEST" "$DEST"
        log "promoted $LATEST -> $DEST"
    fi
fi

# Prune daily: keep newest 7
PRUNED_D=$(ls -1t "$DAILY"/mhbn-*.dump 2>/dev/null | tail -n +8)
for f in $PRUNED_D; do
    rm -f "$f"
    log "pruned daily: $f"
done

# Prune weekly: keep newest 4
PRUNED_W=$(ls -1t "$WEEKLY"/mhbn-*.dump 2>/dev/null | tail -n +5)
for f in $PRUNED_W; do
    rm -f "$f"
    log "pruned weekly: $f"
done

# Prune monthly: keep newest 6
PRUNED_M=$(ls -1t "$MONTHLY"/mhbn-*.dump 2>/dev/null | tail -n +7)
for f in $PRUNED_M; do
    rm -f "$f"
    log "pruned monthly: $f"
done

D_COUNT=$(ls "$DAILY"/mhbn-*.dump 2>/dev/null | wc -l)
W_COUNT=$(ls "$WEEKLY"/mhbn-*.dump 2>/dev/null | wc -l)
M_COUNT=$(ls "$MONTHLY"/mhbn-*.dump 2>/dev/null | wc -l)
log "post-rotate: daily=$D_COUNT weekly=$W_COUNT monthly=$M_COUNT"
