#!/bin/bash
#
# Queue a YouTube download to run in the background
#
# Usage:
#   Single video:
#     yt-queue.sh <category> <length> <url>
#
#   Playlist (all to same length folder):
#     yt-queue.sh --playlist <category> <length> <url>
#
#   Playlist (auto-sort by duration):
#     yt-queue.sh --playlist --auto-length <category> <url>
#
# Examples:
#   yt-queue.sh deep_techno long "https://youtube.com/watch?v=..."
#   yt-queue.sh --playlist surreal_talkshows short "https://youtube.com/playlist?list=..."
#   yt-queue.sh --playlist --auto-length sketch_comedy "https://youtube.com/playlist?list=..."
#

set -euo pipefail

INCOMING="/mnt/incoming"
LOG_DIR="/var/log/transcode"
YT_DLP="$HOME/.local/bin/yt-dlp"

# Parse flags
PLAYLIST=false
AUTO_LENGTH=false

while [[ $# -gt 0 && "$1" == --* ]]; do
    case "$1" in
        --playlist)
            PLAYLIST=true
            shift
            ;;
        --auto-length)
            AUTO_LENGTH=true
            shift
            ;;
        *)
            echo "Unknown flag: $1"
            exit 1
            ;;
    esac
done

# Validate arguments
if $AUTO_LENGTH; then
    # --auto-length mode: category + url only
    if [[ $# -lt 2 ]]; then
        echo "Usage: $0 --playlist --auto-length <category> <url>"
        exit 1
    fi
    CATEGORY="$1"
    LENGTH=""
    URL="$2"
else
    # Standard mode: category + length + url
    if [[ $# -lt 3 ]]; then
        echo "Usage: $0 [--playlist] <category> <length> <url>"
        echo "       $0 --playlist --auto-length <category> <url>"
        echo ""
        echo "  category: e.g., deep_techno, gaming_moody, sketch_comedy"
        echo "  length:   short (<5min), medium (5-30min), long (>30min)"
        echo "  url:      YouTube URL or playlist URL"
        exit 1
    fi
    CATEGORY="$1"
    LENGTH="$2"
    URL="$3"
    
    # Validate length
    if [[ ! "$LENGTH" =~ ^(short|medium|long)$ ]]; then
        echo "Error: length must be short, medium, or long"
        exit 1
    fi
fi

# Create directories
mkdir -p "$INCOMING/$CATEGORY/short" "$INCOMING/$CATEGORY/medium" "$INCOMING/$CATEGORY/long" 2>/dev/null || true
mkdir -p "$LOG_DIR"

# Generate log filename from timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOG_DIR/yt-download_${TIMESTAMP}.log"

# Get video/playlist info for confirmation
echo "Fetching info..."

if $PLAYLIST; then
    # Playlist mode - get playlist title and count
    TITLE=$($YT_DLP --flat-playlist --print "%(playlist_title)s" "$URL" 2>/dev/null | head -1 || echo "Unknown Playlist")
    COUNT=$($YT_DLP --flat-playlist --print "%(title)s" "$URL" 2>/dev/null | wc -l || echo "?")
    
    echo ""
    echo "Queueing playlist download:"
    echo "  Playlist: $TITLE"
    echo "  Videos:   $COUNT"
    echo "  Category: $CATEGORY"
    if $AUTO_LENGTH; then
        echo "  Length:   auto-sorted by duration"
    else
        echo "  Length:   $LENGTH (all videos)"
    fi
    echo "  Log:      $LOGFILE"
    echo ""
else
    # Single video mode
    TITLE=$($YT_DLP --get-title "$URL" 2>/dev/null || echo "Unknown")
    DURATION=$($YT_DLP --get-duration "$URL" 2>/dev/null || echo "Unknown")
    
    echo ""
    echo "Queueing download:"
    echo "  Title:    $TITLE"
    echo "  Duration: $DURATION"
    echo "  Category: $CATEGORY/$LENGTH"
    echo "  Log:      $LOGFILE"
    echo ""
fi

# Build output template
if $AUTO_LENGTH; then
    # Auto-sort by duration: >30min=long, >5min=medium, else=short
    OUTPUT_TEMPLATE="$INCOMING/$CATEGORY/%(duration>1800|long|%(duration>300|medium|short))s/%(title)s.%(ext)s"
else
    OUTPUT_TEMPLATE="$INCOMING/$CATEGORY/$LENGTH/%(title)s.%(ext)s"
fi

# Build yt-dlp command
YT_CMD="$YT_DLP -f 'bestvideo+bestaudio/best' -o '$OUTPUT_TEMPLATE'"

if $PLAYLIST; then
    YT_CMD="$YT_CMD --yes-playlist"
fi

YT_CMD="$YT_CMD '$URL'"

# Start background download
nohup bash -c "$YT_CMD" >> "$LOGFILE" 2>&1 &

PID=$!
echo "$PID" > "/tmp/yt-download-$TIMESTAMP.pid"

echo "Download started (PID $PID)"
echo "Monitor with: tail -f $LOGFILE"
echo "Check status: ps -p $PID"
