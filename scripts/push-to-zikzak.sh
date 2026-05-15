#!/bin/bash
#
# Push transcoded media from loki to zikzak
# Then trigger playlist regeneration on zikzak
#

set -euo pipefail

ZIKZAK="zikzak.local"
SRC_DIR="/mnt/media_transcoded"
DROPBOX="/mnt/dropbox"

echo "=========================================="
echo "Push Transcoded Media to zikzak dropbox"
echo "=========================================="
echo ""
echo "Files go to ${ZIKZAK}:${DROPBOX}/ where the"
echo "dropbox-watchdog validates and files them."
echo ""
echo "Syncing $SRC_DIR -> ${ZIKZAK}:${DROPBOX}"
echo "-------------------------------------------"

# Ensure dropbox exists
ssh "$ZIKZAK" "mkdir -p ${DROPBOX}" || true

# Limit bandwidth to avoid interrupting zikzak's icecast2 stream
rsync -avh --progress --bwlimit=20000 "$SRC_DIR/" "${ZIKZAK}:${DROPBOX}/"

if [[ $? -eq 0 ]]; then
    echo ""
    echo "=========================================="
    echo "Sync complete!"
    echo ""
    echo "The dropbox-watchdog on zikzak will validate"
    echo "and file the media automatically."
    echo "=========================================="
else
    echo ""
    echo "ERROR: Sync failed!"
    exit 1
fi
