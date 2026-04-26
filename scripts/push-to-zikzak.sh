#!/bin/bash
#
# Push transcoded media from loki to zikzak
# Then trigger playlist regeneration on zikzak
#

set -euo pipefail

ZIKZAK="zikzak.local"
SRC_DIR="/mnt/media_transcoded"
DST_DIR="/mnt/media"

echo "=========================================="
echo "Push Transcoded Media to zikzak"
echo "=========================================="

echo ""
echo "Syncing $SRC_DIR -> ${ZIKZAK}:${DST_DIR}"
echo "-------------------------------------------"
# Limit bandwidth to avoid interrupting zikzak's icecast2 stream
rsync -avh --progress --bwlimit=20000 "$SRC_DIR/" "${ZIKZAK}:${DST_DIR}/"

if [[ $? -eq 0 ]]; then
    echo ""
    echo "=========================================="
    echo "Sync complete!"
    echo ""
    echo "Triggering playlist regeneration on zikzak..."
    ssh "$ZIKZAK" "sudo -u max /home/max/bin/regenerate-playlists.sh" || true
    
    echo ""
    echo "Done! New media is now available on zikzak."
    echo "=========================================="
else
    echo ""
    echo "ERROR: Sync failed!"
    exit 1
fi
