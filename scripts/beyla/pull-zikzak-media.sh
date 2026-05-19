#!/bin/bash
# pull-zikzak-media.sh — mirror zikzak's /mnt/media to beyla.
# Run on beyla as nthmost. Cron: daily at 03:30 (after the DB dump).
#
# Mirror semantics: rsync --delete so beyla matches zikzak's current state
# exactly. No point-in-time snapshots — for that, use --link-dest into a
# timestamped subdir, but for now we trust zikzak's own state as authoritative
# and just keep beyla as a warm copy.

set -uo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/media/music-archive/backups}"
DEST="$BACKUP_ROOT/zikzak-media"
LOG_DIR="$BACKUP_ROOT/logs"
LOG="$LOG_DIR/zikzak-media.$(date +%Y%m%d).log"
LOCK="$BACKUP_ROOT/.lock-zikzak-media"

mkdir -p "$DEST" "$LOG_DIR"

# Avoid overlap if previous run is still going
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "[$(date -Is)] previous run still in progress, skipping" >> "$LOG"
    exit 0
fi

echo "[$(date -Is)] === start ===" >> "$LOG"

# --delete: drop files on beyla that no longer exist on zikzak (mirror)
# --no-perms --no-owner --no-group --omit-dir-times: cross-user dest, same
#   pattern as intake's _rsync_to_dropbox_bash (avoids EPERM on metadata)
# --partial --append-verify: resumeable
# --bwlimit=20000: 20 MB/s cap so we don't saturate the link
rsync -rv --delete \
      --no-perms --no-owner --no-group --omit-dir-times \
      --partial --append-verify \
      --bwlimit=20000 \
      -e 'ssh -o BatchMode=yes -J nthmost@149.28.77.210' \
      "nthmost@10.100.0.5:/mnt/media/" \
      "$DEST/" \
      >> "$LOG" 2>&1
RC=$?

DU=$(du -sh "$DEST" 2>/dev/null | cut -f1)
FILES=$(find "$DEST" -type f -name "*.mp4" -o -name "*.webm" -o -name "*.mkv" 2>/dev/null | wc -l)
echo "[$(date -Is)] === done rc=$RC, $FILES files, $DU on disk ===" >> "$LOG"

# rsync exit 23/24 = some files/attrs not transferred — treat as warning
case "$RC" in
    0)    exit 0 ;;
    23|24) echo "[$(date -Is)] WARNING: non-fatal rsync warnings (rc=$RC)" >> "$LOG"; exit 0 ;;
    *)    echo "[$(date -Is)] ERROR: rsync failed rc=$RC" >> "$LOG"; exit "$RC" ;;
esac
