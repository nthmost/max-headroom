#!/usr/bin/env bash
# harvest_archive.sh — Download content from the Internet Archive
#
# Requires: pip install internetarchive
#
# Usage:
#   ./harvest_archive.sh "public access television" 10
#   ./harvest_archive.sh "vhs rip" 5 ~/tv/content/main
#
# Args:
#   $1  Search query (required)
#   $2  Max items to download (default: 5)
#   $3  Output directory (default: ../content/main)

set -euo pipefail

QUERY="${1:?Usage: $0 <search_query> [max_items] [output_dir]}"
MAX_ITEMS="${2:-5}"
OUTDIR="${3:-$(dirname "$0")/../content/main}"

mkdir -p "$OUTDIR"

echo "==> Searching Internet Archive for: $QUERY"
echo "==> Max items: $MAX_ITEMS"
echo "==> Output dir: $OUTDIR"
echo ""

# Good search terms for cursed content:
#   "public access television"
#   "vhs rip"
#   "educational film 1980"
#   "training video"
#   "local news 1990"
#   "instructional film"
#   "home video 1980s"
#   "beta max recording"

IDENTIFIERS=$(ia search "$QUERY" \
  --field identifier \
  --field mediatype \
  --parameters "mediatype:movies" \
  --itemlist \
  | head -n "$MAX_ITEMS")

if [[ -z "$IDENTIFIERS" ]]; then
  echo "ERROR: No results found for: $QUERY"
  exit 1
fi

echo "==> Found items:"
echo "$IDENTIFIERS"
echo ""

for ITEM in $IDENTIFIERS; do
  echo "==> Downloading: $ITEM"
  ia download "$ITEM" \
    --glob="*.mp4" \
    --glob="*.avi" \
    --glob="*.mkv" \
    --no-directories \
    --destdir="$OUTDIR" \
    --ignore-existing \
    || echo "WARN: partial/failed download for $ITEM, continuing..."
  echo ""
done

echo "==> Done. Files in $OUTDIR:"
ls -lh "$OUTDIR"
