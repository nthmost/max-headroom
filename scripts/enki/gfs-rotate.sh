#!/bin/bash
# gfs-rotate.sh — Grandfather-Father-Son rotation for mhbn pg_dumps on enki.
# Run on enki as nthmost. Cron: daily at 02:30 (after pull + push).
#
# Policy:
#   daily/   keep most-recent 7
#   weekly/  promote one per ISO week (Mondays), keep 4
#   monthly/ promote one per calendar month (first of month), keep 6
#
# Hardlinks where possible (same filesystem) so promotion is free.

set -uo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/backups}"
DAILY="$BACKUP_ROOT/mhbn-dumps/daily"
WEEKLY="$BACKUP_ROOT/mhbn-dumps/weekly"
MONTHLY="$BACKUP_ROOT/mhbn-dumps/monthly"
LOG="$BACKUP_ROOT/logs/gfs-rotate.$(date +%Y%m%d).log"

mkdir -p "$DAILY" "$WEEKLY" "$MONTHLY"

log() { echo "[$(date -Is)] $*" >> "$LOG"; }

LATEST=$(ls -1t "$DAILY"/mhbn-*.dump 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    log "no daily dump found, nothing to rotate"
    exit 0
fi

DOW=$(date +%u)
DOM=$(date +%d)
ISOWEEK=$(date +%G-W%V)
MONTH=$(date +%Y-%m)

if [ "$DOW" = "1" ]; then
    DEST="$WEEKLY/mhbn-${ISOWEEK}.dump"
    if [ ! -e "$DEST" ]; then
        ln "$LATEST" "$DEST"
        log "promoted $LATEST -> $DEST"
    fi
fi

if [ "$DOM" = "01" ]; then
    DEST="$MONTHLY/mhbn-${MONTH}.dump"
    if [ ! -e "$DEST" ]; then
        ln "$LATEST" "$DEST"
        log "promoted $LATEST -> $DEST"
    fi
fi

PRUNED_D=$(ls -1t "$DAILY"/mhbn-*.dump 2>/dev/null | tail -n +8)
for f in $PRUNED_D; do
    rm -f "$f"
    log "pruned daily: $f"
done

PRUNED_W=$(ls -1t "$WEEKLY"/mhbn-*.dump 2>/dev/null | tail -n +5)
for f in $PRUNED_W; do
    rm -f "$f"
    log "pruned weekly: $f"
done

PRUNED_M=$(ls -1t "$MONTHLY"/mhbn-*.dump 2>/dev/null | tail -n +7)
for f in $PRUNED_M; do
    rm -f "$f"
    log "pruned monthly: $f"
done

D_COUNT=$(ls "$DAILY"/mhbn-*.dump 2>/dev/null | wc -l)
W_COUNT=$(ls "$WEEKLY"/mhbn-*.dump 2>/dev/null | wc -l)
M_COUNT=$(ls "$MONTHLY"/mhbn-*.dump 2>/dev/null | wc -l)
log "post-rotate: daily=$D_COUNT weekly=$W_COUNT monthly=$M_COUNT"
