#!/bin/bash
# Watches /mnt/media for new/removed files and regenerates playlists.
# Debounces rapid events (e.g. large copies) with a 10s settle wait.

MEDIA_ROOT="/mnt/media"
GEN_SCRIPT="/home/max/bin/gen-playlists.sh"
DEBOUNCE=10

echo "Watching $MEDIA_ROOT for changes..."

while true; do
    # Wait for any create/delete/move event recursively
    inotifywait -r -e create -e delete -e moved_to -e moved_from \
        --include '.*\.(mp4|mkv|avi|mov|webm|mpg|mpeg|m4v|ts|ogv|flv)$' \
        "$MEDIA_ROOT" 2>/dev/null

    echo "Change detected, waiting ${DEBOUNCE}s for activity to settle..."
    sleep "$DEBOUNCE"

    # Drain any queued events before regenerating
    inotifywait -r -e create -e delete -e moved_to -e moved_from \
        --timeout 2 "$MEDIA_ROOT" 2>/dev/null

    "$GEN_SCRIPT"
done
