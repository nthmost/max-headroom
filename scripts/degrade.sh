#!/usr/bin/env bash
# degrade.sh — Apply VHS-style analog degradation to a video file
#
# Requires: ffmpeg
#
# Usage:
#   ./degrade.sh input.mp4 [output.mp4] [intensity: 1-5]
#
#   intensity 1 = subtle (light noise, slight color shift)
#   intensity 2 = moderate (default — clear VHS feel)
#   intensity 3 = heavy (tracking artifacts, color bleed)
#   intensity 4 = brutal (multi-pass re-encode, heavy noise)
#   intensity 5 = destroyed (barely watchable, extremely cursed)

set -euo pipefail

INPUT="${1:?Usage: $0 <input.mp4> [output.mp4] [intensity 1-5]}"
OUTPUT="${2:-${INPUT%.*}_degraded.mp4}"
INTENSITY="${3:-2}"

echo "==> Degrading: $INPUT"
echo "==> Output:    $OUTPUT"
echo "==> Intensity: $INTENSITY"
echo ""

case "$INTENSITY" in

  1)
    # Subtle: light grain, slight warmth
    ffmpeg -i "$INPUT" \
      -vf "scale=640:480,
           noise=alls=5:allf=t,
           eq=saturation=0.9:contrast=1.05" \
      -c:v libx264 -crf 22 -preset medium \
      -c:a aac -b:a 128k \
      "$OUTPUT"
    ;;

  2)
    # Moderate: clear VHS feel, color bleed approximation
    ffmpeg -i "$INPUT" \
      -vf "scale=640:480,
           noise=alls=15:allf=t,
           hue=h=3:s=1.1,
           eq=saturation=1.2:contrast=1.1:brightness=-0.05,
           unsharp=5:5:0.8:3:3:0.0" \
      -c:v libx264 -crf 26 -preset medium \
      -c:a aac -b:a 96k \
      "$OUTPUT"
    ;;

  3)
    # Heavy: drop frames, phase shift, tracking feel
    ffmpeg -i "$INPUT" \
      -vf "scale=640:480,
           noise=alls=25:allf=t,
           hue=h=8:s=1.3,
           eq=saturation=1.4:contrast=1.2:brightness=-0.1,
           framestep=2,
           unsharp=7:7:1.5:5:5:0.0" \
      -r 15 \
      -c:v libx264 -crf 30 -preset fast \
      -c:a aac -b:a 64k \
      "$OUTPUT"
    ;;

  4)
    # Brutal: multi-pass re-encode through MPEG2 then back
    TMP1=$(mktemp /tmp/degrade_pass1_XXXX.mpg)
    TMP2=$(mktemp /tmp/degrade_pass2_XXXX.mp4)

    echo "==> Pass 1: downscale to MPEG2..."
    ffmpeg -i "$INPUT" \
      -vf "scale=320:240" \
      -c:v mpeg2video -q:v 20 \
      -c:a mp2 -b:a 64k \
      "$TMP1"

    echo "==> Pass 2: upscale and destroy..."
    ffmpeg -i "$TMP1" \
      -vf "scale=640:480,
           noise=alls=40:allf=t,
           hue=h=15:s=1.5,
           eq=saturation=1.6:contrast=1.3:brightness=-0.15,
           unsharp=9:9:2.0:5:5:0.5" \
      -c:v libx264 -crf 34 -preset fast \
      -c:a aac -b:a 48k \
      "$TMP2"

    echo "==> Pass 3: final noise pass..."
    ffmpeg -i "$TMP2" \
      -vf "noise=alls=20:allf=t" \
      -c:v libx264 -crf 28 \
      -c:a copy \
      "$OUTPUT"

    rm -f "$TMP1" "$TMP2"
    ;;

  5)
    # Destroyed: three MPEG2 passes + extreme noise + frame duplication hell
    TMP1=$(mktemp /tmp/degrade_p1_XXXX.mpg)
    TMP2=$(mktemp /tmp/degrade_p2_XXXX.mpg)
    TMP3=$(mktemp /tmp/degrade_p3_XXXX.mpg)

    echo "==> Pass 1 of 3 (MPEG2 encode)..."
    ffmpeg -i "$INPUT" -vf "scale=320:240" -c:v mpeg2video -q:v 25 -c:a mp2 -b:a 32k "$TMP1"

    echo "==> Pass 2 of 3 (MPEG2 re-encode)..."
    ffmpeg -i "$TMP1" -vf "scale=160:120,noise=alls=30:allf=t" -c:v mpeg2video -q:v 31 -c:a mp2 -b:a 32k "$TMP2"

    echo "==> Pass 3 of 3 (MPEG2 re-encode)..."
    ffmpeg -i "$TMP2" -vf "scale=320:240,noise=alls=20:allf=t" -c:v mpeg2video -q:v 28 -c:a mp2 -b:a 32k "$TMP3"

    echo "==> Final assembly..."
    ffmpeg -i "$TMP3" \
      -vf "scale=640:480,
           noise=alls=50:allf=t,
           hue=h=20:s=2.0,
           eq=saturation=2.0:contrast=1.5:brightness=-0.2,
           unsharp=11:11:3.0:5:5:1.0,
           framestep=3" \
      -r 10 \
      -c:v libx264 -crf 38 -preset ultrafast \
      -c:a aac -b:a 32k \
      "$OUTPUT"

    rm -f "$TMP1" "$TMP2" "$TMP3"
    ;;

  *)
    echo "ERROR: intensity must be 1-5, got: $INTENSITY"
    exit 1
    ;;
esac

echo ""
echo "==> Done: $OUTPUT"
ls -lh "$OUTPUT"
