#!/bin/bash
#
# Transcode all media to 960x540 H.264 for quad-mux output
# Uses NVENC for hardware acceleration
#

SRC_BASE="/mnt/media"
DST_BASE="/mnt/media_transcoded"
LOG_DIR="/var/log/transcode"

WIDTH=960
HEIGHT=540
VIDEO_BITRATE="1200k"
AUDIO_BITRATE="128k"
AUDIO_RATE="44100"

# Create directories
sudo mkdir -p "$DST_BASE" "$LOG_DIR"
sudo chown $USER:$USER "$DST_BASE" "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SUCCESS_LOG="$LOG_DIR/success_$TIMESTAMP.log"
FAIL_LOG="$LOG_DIR/fail_$TIMESTAMP.log"

touch "$SUCCESS_LOG" "$FAIL_LOG"

echo "=========================================="
echo "Transcode for Quad-Mux"
echo "=========================================="
echo "Source:      $SRC_BASE"
echo "Destination: $DST_BASE"
echo "Resolution:  ${WIDTH}x${HEIGHT}"
echo "Video:       H.264 NVENC @ $VIDEO_BITRATE"
echo "Audio:       AAC @ $AUDIO_BITRATE"
echo "=========================================="

# Find all media files
echo "Scanning for media files..."
mapfile -t FILES < <(find "$SRC_BASE" -type f \( -name "*.ogv" -o -name "*.mp4" -o -name "*.webm" -o -name "*.mkv" -o -name "*.avi" \) 2>/dev/null | sort)

TOTAL=${#FILES[@]}
echo "Found $TOTAL files to process"
echo ""

for i in "${!FILES[@]}"; do
    src="${FILES[$i]}"
    COUNT=$((i + 1))
    
    rel_path="${src#$SRC_BASE/}"
    dst_dir="$DST_BASE/$(dirname "$rel_path")"
    basename=$(basename "$rel_path")
    dst="$dst_dir/${basename%.*}.mp4"
    
    # Skip if already transcoded
    if [[ -f "$dst" ]]; then
        echo "[$COUNT/$TOTAL] SKIP: $rel_path"
        continue
    fi
    
    mkdir -p "$dst_dir"
    
    # Check if file has audio
    has_audio=$(ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$src" 2>/dev/null | head -1)
    
    echo "[$COUNT/$TOTAL] Transcoding: $rel_path"
    
    if [[ -z "$has_audio" ]]; then
        # No audio - add silent track
        ffmpeg -hide_banner -loglevel error -nostdin -y \
            -i "$src" \
            -f lavfi -i anullsrc=r=${AUDIO_RATE}:cl=stereo \
            -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,pad=${WIDTH}:${HEIGHT}:-1:-1:color=black,setsar=1" \
            -c:v h264_nvenc -preset p4 -b:v "$VIDEO_BITRATE" -profile:v main -level 4.1 \
            -map 0:v -map 1:a -c:a aac -b:a ${AUDIO_BITRATE} -ar ${AUDIO_RATE} -shortest \
            -movflags +faststart \
            "$dst" 2>> "$FAIL_LOG"
    else
        ffmpeg -hide_banner -loglevel error -nostdin -y \
            -i "$src" \
            -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,pad=${WIDTH}:${HEIGHT}:-1:-1:color=black,setsar=1" \
            -c:v h264_nvenc -preset p4 -b:v "$VIDEO_BITRATE" -profile:v main -level 4.1 \
            -map 0:v -map 0:a -c:a aac -b:a ${AUDIO_BITRATE} -ar ${AUDIO_RATE} -ac 2 \
            -movflags +faststart \
            "$dst" 2>> "$FAIL_LOG"
    fi
    
    if [[ -f "$dst" && -s "$dst" ]]; then
        echo "  -> OK"
        echo "$dst" >> "$SUCCESS_LOG"
    else
        echo "  -> FAILED"
        echo "$src" >> "$FAIL_LOG"
        rm -f "$dst"
    fi
done

echo ""
echo "=========================================="
echo "Complete!"
echo "Success: $(wc -l < "$SUCCESS_LOG")"
echo "Failed:  $(grep -c "^/" "$FAIL_LOG" 2>/dev/null || echo 0)"
echo "=========================================="
