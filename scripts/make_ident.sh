#!/usr/bin/env bash
# make_ident.sh — Generate station ident bumper clips
#
# Requires: ffmpeg (with drawtext / freetype support)
#
# Usage:
#   ./make_ident.sh [output_dir]
#
# Generates a small set of 3-5 second station ident clips with variations.
# Edit STATION_NAME and TAGLINES below to customize.

set -euo pipefail

OUTDIR="${1:-$(dirname "$0")/../content/idents}"

WIDTH=640
HEIGHT=480
FPS=25
FONT_SIZE=42
FONT_COLOR="white"
BG_COLOR="black"

STATION_NAME="CURSED TV"

# Taglines — one per ident variant
TAGLINES=(
  "SIGNAL FOUND"
  "DO NOT ADJUST YOUR SET"
  "TRANSMISSION CONTINUES"
  "YOU ARE WATCHING"
  "PLEASE STAND BY"
  "CHANNEL UNKNOWN"
  "ALL IS WELL"
  "WE APOLOGIZE FOR NOTHING"
  "THIS HAS ALWAYS BEEN HERE"
  "NORMAL BROADCAST RESUMED"
)

mkdir -p "$OUTDIR"

echo "==> Generating station idents in: $OUTDIR"
echo ""

# Helper: slugify a string for filenames
slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | tr -cd '[:alnum:]_'
}

for TAGLINE in "${TAGLINES[@]}"; do
  SLUG=$(slugify "$TAGLINE")
  OUTFILE="$OUTDIR/ident_${SLUG}.mp4"

  echo "==> $STATION_NAME / $TAGLINE"

  # Duration: 3-5 seconds, slightly random
  DURATION=$(( (RANDOM % 3) + 3 ))

  ffmpeg -y -f lavfi \
    -i "color=c=${BG_COLOR}:s=${WIDTH}x${HEIGHT}:r=${FPS}:d=${DURATION}" \
    -vf "noise=alls=8:allf=t,
         drawtext=text='${STATION_NAME}':
           x=(w-text_w)/2:y=(h-text_h)/2-30:
           fontsize=${FONT_SIZE}:fontcolor=${FONT_COLOR}:
           box=1:boxcolor=black@0.5:boxborderw=8,
         drawtext=text='${TAGLINE}':
           x=(w-text_w)/2:y=(h-text_h)/2+30:
           fontsize=20:fontcolor=gray:
           box=1:boxcolor=black@0.5:boxborderw=6" \
    -c:v libx264 -crf 22 -preset medium \
    -an \
    "$OUTFILE"
done

echo ""
echo "==> Done. Idents:"
ls -lh "$OUTDIR"
