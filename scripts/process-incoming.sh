#!/bin/bash
#
# Process incoming media files: catalogue, transcode, and push to zikzak
# Designed to run as a cron job every 5 minutes
#
# Flow:
#   /mnt/incoming/<category>/<length>/*.{mp4,webm,mkv,...}
#       ↓ move to catalogue
#   /mnt/media/<category>/<length>/
#       ↓ transcode
#   /mnt/media_transcoded/<category>/<length>/
#       ↓ rsync
#   zikzak.local:/mnt/media/
#

set -euo pipefail

# Paths
INCOMING="/mnt/incoming"
MEDIA="/mnt/media"
TRANSCODED="/mnt/media_transcoded"
ZIKZAK="zikzak.local"
ZIKZAK_MEDIA="/mnt/media"
LOG_DIR="/var/log/transcode"
LOCKFILE="/tmp/process-incoming.lock"
VAAPI_DEVICE="/dev/dri/renderD128"
CLEANUP_AFTER_DAYS=7  # Keep transcoded files for 7 days before cleanup

# Transcode settings
WIDTH=960
HEIGHT=540
VIDEO_BITRATE="1200k"
AUDIO_BITRATE="128k"
AUDIO_RATE="44100"

# Logging
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Check for VAAPI device
if [[ ! -e "$VAAPI_DEVICE" ]]; then
    log "ERROR: VAAPI device not found: $VAAPI_DEVICE"
    log "Make sure Intel GPU drivers are installed. Check: ls -la /dev/dri/"
    exit 1
fi

# Prevent concurrent runs
if [[ -f "$LOCKFILE" ]]; then
    pid=$(cat "$LOCKFILE")
    if kill -0 "$pid" 2>/dev/null; then
        log "Another instance is running (PID $pid). Exiting."
        exit 0
    else
        log "Stale lockfile found. Removing."
        rm -f "$LOCKFILE"
    fi
fi
echo $$ > "$LOCKFILE"
trap "rm -f $LOCKFILE" EXIT

# Ensure directories exist
mkdir -p "$LOG_DIR"

# Find all incoming media files
mapfile -t INCOMING_FILES < <(find "$INCOMING" -type f \( \
    -name "*.mp4" -o -name "*.webm" -o -name "*.mkv" \
    -o -name "*.ogv" -o -name "*.avi" -o -name "*.mov" \
    \) 2>/dev/null | sort)

if [[ ${#INCOMING_FILES[@]} -eq 0 ]]; then
    exit 0  # Nothing to process
fi

log "Found ${#INCOMING_FILES[@]} incoming file(s)"

# Track what we process for the push phase
PROCESSED=()

for src in "${INCOMING_FILES[@]}"; do
    # Extract category/length from path: /mnt/incoming/darkwave_postpunk/long/file.mp4
    rel_path="${src#$INCOMING/}"
    category=$(echo "$rel_path" | cut -d'/' -f1)
    length=$(echo "$rel_path" | cut -d'/' -f2)
    filename=$(basename "$rel_path")
    
    # Validate structure
    if [[ -z "$category" || -z "$length" || ! "$length" =~ ^(short|medium|long)$ ]]; then
        log "SKIP: Invalid path structure: $rel_path"
        continue
    fi
    
    # Destination paths
    media_dir="$MEDIA/$category/$length"
    transcode_dir="$TRANSCODED/$category/$length"
    media_dst="$media_dir/$filename"
    transcode_dst="$transcode_dir/${filename%.*}.mp4"

    # Check for per-directory crop marker (written by intake when crop_sides=True)
    crop_sides=0
    if [[ -f "$INCOMING/$category/$length/.crop" ]]; then
        crop_sides=1
    fi

    # Create directories
    mkdir -p "$media_dir" "$transcode_dir"
    
    log "Processing: $rel_path"
    
    # Step 1: Move to catalogue (media)
    if [[ -f "$media_dst" ]]; then
        log "  File already exists in media, removing incoming copy"
        rm -f "$src"
        continue
    fi
    
    mv "$src" "$media_dst"
    log "  Catalogued: $category/$length/$filename"
    
    # Step 2: Transcode
    if [[ -f "$transcode_dst" ]]; then
        log "  Already transcoded, skipping"
        PROCESSED+=("$transcode_dst")
        continue
    fi
    
    # Check if file has audio
    has_audio=$(ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$media_dst" 2>/dev/null | head -1)

    # Build video filter: crop-to-fill for square videos when requested,
    # otherwise letterbox to preserve aspect ratio.
    if [[ $crop_sides -eq 1 ]]; then
        # Center-crop to 16:9 slice (fills the 960x540 frame, trims top/bottom)
        VF_FILTER="crop=in_w:in_w*9/16:0:(in_h-in_w*9/16)/2,format=nv12,hwupload,scale_vaapi=${WIDTH}:${HEIGHT}"
        log "  Transcoding to ${WIDTH}x${HEIGHT} H.264 (crop sides)..."
    else
        VF_FILTER="scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=nv12,hwupload"
        log "  Transcoding to ${WIDTH}x${HEIGHT} H.264..."
    fi

    if [[ -z "$has_audio" ]]; then
        # No audio - add silent track
        ffmpeg -hide_banner -loglevel error -nostdin -y \
            -vaapi_device "$VAAPI_DEVICE" \
            -i "$media_dst" \
            -f lavfi -i anullsrc=r=${AUDIO_RATE}:cl=stereo \
            -vf "$VF_FILTER" \
            -c:v h264_vaapi -b:v "$VIDEO_BITRATE" -profile:v main -level 4.1 \
            -map 0:v -map 1:a -c:a aac -b:a ${AUDIO_BITRATE} -ar ${AUDIO_RATE} -shortest \
            -movflags +faststart \
            "$transcode_dst" 2>> "$LOG_DIR/transcode_errors.log"
    else
        ffmpeg -hide_banner -loglevel error -nostdin -y \
            -vaapi_device "$VAAPI_DEVICE" \
            -i "$media_dst" \
            -vf "$VF_FILTER" \
            -c:v h264_vaapi -b:v "$VIDEO_BITRATE" -profile:v main -level 4.1 \
            -map 0:v -map 0:a -c:a aac -b:a ${AUDIO_BITRATE} -ar ${AUDIO_RATE} -ac 2 \
            -movflags +faststart \
            "$transcode_dst" 2>> "$LOG_DIR/transcode_errors.log"
    fi
    
    if [[ -f "$transcode_dst" && -s "$transcode_dst" ]]; then
        log "  Transcode OK"
        PROCESSED+=("$transcode_dst")
    else
        log "  Transcode FAILED"
        rm -f "$transcode_dst"
    fi
done

# Step 3: Push to zikzak if we processed anything
if [[ ${#PROCESSED[@]} -gt 0 ]]; then
    log "Pushing ${#PROCESSED[@]} transcoded file(s) to zikzak..."
    
    # Limit bandwidth to avoid interrupting zikzak's icecast2 stream
    rsync -avh --progress --bwlimit=20000 "$TRANSCODED/" "${ZIKZAK}:${ZIKZAK_MEDIA}/" \
        >> "$LOG_DIR/rsync.log" 2>&1
    
    if [[ $? -eq 0 ]]; then
        log "Push complete"
        
        # Regenerate playlists on zikzak
        log "Regenerating playlists on zikzak..."
        ssh "$ZIKZAK" "sudo -u max /home/max/bin/regenerate-playlists.sh" \
            >> "$LOG_DIR/playlist.log" 2>&1 || true
        
        log "Pipeline complete!"
        
        # Mark transcoded files for cleanup
        for file in "${PROCESSED[@]}"; do
            touch "$file"  # Update timestamp for cleanup script
        done
    else
        log "Push FAILED - check $LOG_DIR/rsync.log"
    fi
fi

log "Done"
