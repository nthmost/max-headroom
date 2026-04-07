#!/bin/bash
#
# Sync media from headroom.local to loki.local
# 1. Backup headroom originals to loki
# 2. Copy any headroom-only content to loki for transcoding
#

set -euo pipefail

HEADROOM="headroom.local"
BACKUP_DIR="/mnt/media_originals_backup"
MEDIA_DIR="/mnt/media"

echo "=========================================="
echo "Sync from Headroom"
echo "=========================================="

# Create backup directory
sudo mkdir -p "$BACKUP_DIR"
sudo chown $USER:$USER "$BACKUP_DIR"

echo ""
echo "Step 1: Backup headroom originals to $BACKUP_DIR"
echo "-------------------------------------------"
rsync -avh --progress "${HEADROOM}:/mnt/media/" "$BACKUP_DIR/"

echo ""
echo "Step 2: Copy non-prelinger content to $MEDIA_DIR for transcoding"
echo "-------------------------------------------"
# Sync everything except prelinger (we already have it)
rsync -avh --progress --exclude="prelinger/" "${HEADROOM}:/mnt/media/" "$MEDIA_DIR/"

echo ""
echo "=========================================="
echo "Sync complete!"
echo "Backup:     $BACKUP_DIR"
echo "To process: $MEDIA_DIR"
echo "=========================================="
