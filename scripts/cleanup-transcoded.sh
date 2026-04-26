#!/bin/bash
#
# Cleanup old transcoded files on loki after they've been pushed to zikzak
# Run this periodically via cron to free up disk space
#

set -euo pipefail

MEDIA="/mnt/media"
TRANSCODED="/mnt/media_transcoded"
LOG_DIR="/var/log/transcode"
CLEANUP_AFTER_DAYS=7  # Delete files older than this many days

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "Starting cleanup of transcoded files older than $CLEANUP_AFTER_DAYS days..."

# Find and delete old transcoded files
DELETED_COUNT=0
FREED_SPACE=0

while IFS= read -r -d '' file; do
    SIZE=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo 0)
    FREED_SPACE=$((FREED_SPACE + SIZE))
    rm -f "$file"
    DELETED_COUNT=$((DELETED_COUNT + 1))
done < <(find "$TRANSCODED" -type f -mtime +${CLEANUP_AFTER_DAYS} -print0 2>/dev/null)

# Remove empty directories
find "$TRANSCODED" -type d -empty -delete 2>/dev/null || true

FREED_MB=$((FREED_SPACE / 1024 / 1024))

log "Cleanup complete: Deleted $DELETED_COUNT file(s), freed ${FREED_MB}MB"

# Also cleanup old originals in /mnt/media (optional - can be disabled)
# Uncomment if you want to auto-delete originals after transcoding
# log "Cleaning up old originals..."
# find "$MEDIA" -type f -mtime +${CLEANUP_AFTER_DAYS} -print0 2>/dev/null | xargs -0 rm -f || true
# find "$MEDIA" -type d -empty -delete 2>/dev/null || true

log "Done"
