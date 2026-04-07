#!/bin/bash
#
# Process incoming media files: catalogue, transcode, and push to headroom
# Designed to run as a cron job every 5 minutes
#
# Flow:
#   /mnt/incoming/<category>/<length>/*.{mp4,webm,mkv,...}
#       ↓ move to catalogue
#   /mnt/media/<category>/<length>/
#       ↓ transcode
#   /mnt/media_transcoded/<category>/<length>/
#       ↓ rsync
#   headroom.local:/mnt/media/
#

set -euo pipefail

# Paths
INCOMING="/mnt/incoming"
MEDIA="/mnt/media"
TRANSCODED="/mnt/media_transcoded"
HEADROOM="headroom.local"
LOG_DIR="/var/log/transcode"
LOCKFILE="/tmp/process-incoming.lock"

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
    
    log "  Transcoding to 960x540 H.264..."
    
    if [[ -z "$has_audio" ]]; then
        # No audio - add silent track
        ffmpeg -hide_banner -loglevel error -nostdin -y \
            -i "$media_dst" \
            -f lavfi -i anullsrc=r=${AUDIO_RATE}:cl=stereo \
            -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,pad=${WIDTH}:${HEIGHT}:-1:-1:color=black,setsar=1" \
            -c:v h264_nvenc -preset p4 -b:v "$VIDEO_BITRATE" -profile:v main -level 4.1 \
            -map 0:v -map 1:a -c:a aac -b:a ${AUDIO_BITRATE} -ar ${AUDIO_RATE} -shortest \
            -movflags +faststart \
            "$transcode_dst" 2>> "$LOG_DIR/transcode_errors.log"
    else
        ffmpeg -hide_banner -loglevel error -nostdin -y \
            -i "$media_dst" \
            -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,pad=${WIDTH}:${HEIGHT}:-1:-1:color=black,setsar=1" \
            -c:v h264_nvenc -preset p4 -b:v "$VIDEO_BITRATE" -profile:v main -level 4.1 \
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

# Step 3: Push to headroom if we processed anything
if [[ ${#PROCESSED[@]} -gt 0 ]]; then
    log "Pushing ${#PROCESSED[@]} transcoded file(s) to headroom..."
    
    rsync -avh --progress "$TRANSCODED/" "${HEADROOM}:${TRANSCODED/transcoded/}/" \
        >> "$LOG_DIR/rsync.log" 2>&1
    
    if [[ $? -eq 0 ]]; then
        log "Push complete"
        
        # Regenerate playlists on headroom
        log "Regenerating playlists on headroom..."
        ssh "$HEADROOM" "sudo -u max /home/max/bin/regenerate-playlists.sh" \
            >> "$LOG_DIR/playlist.log" 2>&1 || true
        
        log "Pipeline complete!"
    else
        log "Push FAILED - check $LOG_DIR/rsync.log"
    fi
fi

log "Done"
