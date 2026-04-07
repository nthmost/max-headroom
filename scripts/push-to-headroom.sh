#!/bin/bash
#
# Push transcoded media from loki to headroom
# Then update playlists on headroom
#

set -euo pipefail

HEADROOM="headroom.local"
SRC_DIR="/mnt/media_transcoded"
DST_DIR="/mnt/media"

echo "=========================================="
echo "Push Transcoded Media to Headroom"
echo "=========================================="

echo ""
echo "Syncing $SRC_DIR -> ${HEADROOM}:${DST_DIR}"
echo "-------------------------------------------"
rsync -avh --progress "$SRC_DIR/" "${HEADROOM}:${DST_DIR}/"

echo ""
echo "=========================================="
echo "Sync complete!"
echo ""
echo "Next steps on headroom:"
echo "  1. Verify files: ls -la /mnt/media/"
echo "  2. Regenerate playlists or update paths"
echo "  3. Restart liquidsoap"
echo "=========================================="
