#!/usr/bin/env bash
# build_playlist.sh — Scan content library and report stats
#
# Usage: ./build_playlist.sh [content_dir]
#
# Prints counts and total duration per content category.
# Useful for sanity-checking your library before starting the station.
#
# Requires: ffprobe (comes with ffmpeg)

set -euo pipefail

CONTENT_DIR="${1:-$(dirname "$0")/../content}"

echo "==> Cursed TV Station — Content Library Report"
echo "==> $(date)"
echo ""

total_files=0
total_seconds=0

for CATEGORY in main glitch dead_air idents bumpers; do
  DIR="$CONTENT_DIR/$CATEGORY"
  if [[ ! -d "$DIR" ]]; then
    echo "  [$CATEGORY] directory not found, skipping"
    continue
  fi

  files=0
  seconds=0

  while IFS= read -r -d '' f; do
    dur=$(ffprobe -v quiet -show_entries format=duration \
          -of default=noprint_wrappers=1:nokey=1 "$f" 2>/dev/null || echo "0")
    dur=${dur%.*}  # truncate to int
    seconds=$((seconds + dur))
    files=$((files + 1))
  done < <(find "$DIR" -maxdepth 1 \
    \( -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" -o -name "*.webm" \) \
    -print0 2>/dev/null)

  hours=$((seconds / 3600))
  mins=$(( (seconds % 3600) / 60 ))

  echo "  [$CATEGORY]  ${files} files  /  ${hours}h ${mins}m"

  total_files=$((total_files + files))
  total_seconds=$((total_seconds + seconds))
done

total_hours=$((total_seconds / 3600))
total_mins=$(( (total_seconds % 3600) / 60 ))

echo ""
echo "  TOTAL: ${total_files} files  /  ${total_hours}h ${total_mins}m"
echo ""

if [[ $total_files -eq 0 ]]; then
  echo "  WARNING: Library is empty. Run harvest_archive.sh and make_dead_air.sh first."
elif [[ $total_seconds -lt 3600 ]]; then
  echo "  WARNING: Less than 1 hour of content. Station will loop quickly."
fi
