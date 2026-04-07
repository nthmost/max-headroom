#!/usr/bin/env bash
# harvest_youtube.sh — Download content via yt-dlp, capped at 720p
#
# Requires: yt-dlp (pip install yt-dlp  or  brew install yt-dlp)
#
# Usage:
#   ./harvest_youtube.sh "URL or search" [output_dir]
#
# Examples:
#   ./harvest_youtube.sh "https://www.youtube.com/watch?v=..."
#   ./harvest_youtube.sh "ytsearch5:VHS compilation" ~/tv/content/main
#   ./harvest_youtube.sh "ytsearch3:analog glitch art" ~/tv/content/glitch

set -euo pipefail

URL="${1:?Usage: $0 <url_or_ytsearch> [output_dir]}"
OUTDIR="${2:-$(dirname "$0")/../content/main}"

mkdir -p "$OUTDIR"

echo "==> Downloading: $URL"
echo "==> Output dir: $OUTDIR"
echo ""

yt-dlp \
  -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]" \
  --merge-output-format mp4 \
  -o "$OUTDIR/%(title)s.%(ext)s" \
  --restrict-filenames \
  --no-playlist \
  "$URL"

echo ""
echo "==> Done."
