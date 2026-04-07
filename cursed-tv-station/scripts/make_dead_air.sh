#!/usr/bin/env bash
# make_dead_air.sh — Generate dead air / filler clips
#
# Requires: ffmpeg
#
# Usage:
#   ./make_dead_air.sh [output_dir] [duration_minutes]
#
# Generates a set of dead air variants:
#   - black with subtle noise (the workhorse)
#   - color bars (SMPTE-ish)
#   - slow static (snowstorm)
#   - frozen frame noise

set -euo pipefail

OUTDIR="${1:-$(dirname "$0")/../content/dead_air}"
DURATION_MIN="${2:-60}"
DURATION_SEC=$((DURATION_MIN * 60))

WIDTH=640
HEIGHT=480
FPS=25

mkdir -p "$OUTDIR"

echo "==> Generating dead air clips in: $OUTDIR"
echo "==> Duration: ${DURATION_MIN}m each"
echo ""

# 1. Black with subtle analog noise (most useful, plays between clips)
echo "==> [1/4] Black with noise..."
ffmpeg -y -f lavfi \
  -i "color=black:s=${WIDTH}x${HEIGHT}:r=${FPS}:d=${DURATION_SEC}" \
  -vf "noise=alls=10:allf=t" \
  -c:v libx264 -crf 28 -preset medium \
  -an \
  "$OUTDIR/dead_air_black.mp4"

# 2. Color bars (good for "channel not broadcasting" feel)
echo "==> [2/4] Color bars..."
ffmpeg -y -f lavfi \
  -i "smptebars=s=${WIDTH}x${HEIGHT}:r=${FPS}:d=${DURATION_SEC}" \
  -c:v libx264 -crf 18 -preset medium \
  -an \
  "$OUTDIR/dead_air_colorbars.mp4"

# 3. Snowstorm static
echo "==> [3/4] Snow static..."
ffmpeg -y -f lavfi \
  -i "color=black:s=${WIDTH}x${HEIGHT}:r=${FPS}:d=${DURATION_SEC}" \
  -vf "noise=alls=80:allf=t,
       eq=contrast=2.0:brightness=-0.3" \
  -c:v libx264 -crf 28 -preset medium \
  -an \
  "$OUTDIR/dead_air_snow.mp4"

# 4. Blue screen of nothing (public access classic)
echo "==> [4/4] Blue screen..."
ffmpeg -y -f lavfi \
  -i "color=c=0x0000AA:s=${WIDTH}x${HEIGHT}:r=${FPS}:d=${DURATION_SEC}" \
  -vf "noise=alls=5:allf=t" \
  -c:v libx264 -crf 28 -preset medium \
  -an \
  "$OUTDIR/dead_air_blue.mp4"

echo ""
echo "==> Done. Dead air clips:"
ls -lh "$OUTDIR"
