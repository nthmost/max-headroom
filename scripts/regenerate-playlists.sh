#!/bin/bash
#
# Regenerate playlists from actual files on disk
# Uses atomic operations to avoid breaking liquidsoap during reload
#

MEDIA_DIR="/mnt/media"
PLAYLIST_DIR="/home/max/playlists"
TEMP_DIR=$(mktemp -d)

# Duration threshold for short/long (in seconds)
SHORT_MAX=300   # 5 minutes
LONG_MIN=1800   # 30 minutes

# Categories for aggregated playlists
MUSIC_CATEGORIES="house_music darkwave_postpunk deep_techno neon_synthpop gaelic_resistance"

echo "Regenerating playlists from $MEDIA_DIR..."
echo "Using temp directory: $TEMP_DIR"

# Collect all files for master playlists
ALL_FILES="$TEMP_DIR/all_files.tmp"
SHORT_FILES="$TEMP_DIR/short_files.tmp"
LONG_FILES="$TEMP_DIR/long_files.tmp"
> "$ALL_FILES"
> "$SHORT_FILES"
> "$LONG_FILES"

# Generate per-category playlists to temp dir
for dir in "$MEDIA_DIR"/*/; do
    category=$(basename "$dir")
    temp_playlist="$TEMP_DIR/${category}.m3u"
    
    find "$dir" -type f -name "*.mp4" | sort > "$temp_playlist"
    cat "$temp_playlist" >> "$ALL_FILES"
    
    # Check duration and categorize
    while IFS= read -r file; do
        duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$file" 2>/dev/null | cut -d. -f1)
        if [[ -n "$duration" ]]; then
            if [[ "$duration" -lt "$SHORT_MAX" ]]; then
                echo "$file" >> "$SHORT_FILES"
            elif [[ "$duration" -gt "$LONG_MIN" ]]; then
                echo "$file" >> "$LONG_FILES"
            fi
        fi
    done < "$temp_playlist"
    
    count=$(wc -l < "$temp_playlist")
    echo "  $category: $count files"
done

# Generate master playlists in temp dir
sort "$ALL_FILES" > "$TEMP_DIR/all.m3u"
sort "$SHORT_FILES" > "$TEMP_DIR/all-short.m3u"
sort "$LONG_FILES" > "$TEMP_DIR/all-long.m3u"

# Generate aggregated playlists for liquidsoap channels
echo ""
echo "Generating aggregated playlists for liquidsoap..."

# music.m3u - all music categories
> "$TEMP_DIR/music.m3u"
for cat in $MUSIC_CATEGORIES; do
    if [[ -f "$TEMP_DIR/${cat}.m3u" ]]; then
        cat "$TEMP_DIR/${cat}.m3u" >> "$TEMP_DIR/music.m3u"
    fi
done

# mixed.m3u - everything except music and prelinger
> "$TEMP_DIR/mixed.m3u"
for playlist in "$TEMP_DIR"/*.m3u; do
    basename=$(basename "$playlist" .m3u)
    
    # Skip aggregated playlists and temp files
    [[ "$basename" == "all" || "$basename" == "all-short" || "$basename" == "all-long" ]] && continue
    [[ "$basename" == "music" || "$basename" == "mixed" || "$basename" == "prelinger" ]] && continue
    [[ "$basename" == *"_files"* ]] && continue
    
    # Skip music categories
    is_music=false
    for cat in $MUSIC_CATEGORIES; do
        [[ "$basename" == "$cat" ]] && is_music=true && break
    done
    $is_music && continue
    
    # Add to mixed
    cat "$playlist" >> "$TEMP_DIR/mixed.m3u"
done

# Atomic move: copy all playlists from temp to final location
echo ""
echo "Moving playlists atomically..."
for playlist in "$TEMP_DIR"/*.m3u; do
    basename=$(basename "$playlist")
    # Skip temp files
    [[ "$basename" == *"_files"* ]] && continue
    mv "$playlist" "$PLAYLIST_DIR/$basename"
done

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "Summary:"
echo "  all.m3u: $(wc -l < "$PLAYLIST_DIR/all.m3u") files"
echo "  all-short.m3u: $(wc -l < "$PLAYLIST_DIR/all-short.m3u") files"
echo "  all-long.m3u: $(wc -l < "$PLAYLIST_DIR/all-long.m3u") files"
echo ""
echo "Liquidsoap playlists:"
echo "  music.m3u: $(wc -l < "$PLAYLIST_DIR/music.m3u") files"
echo "  mixed.m3u: $(wc -l < "$PLAYLIST_DIR/mixed.m3u") files"
echo "  prelinger.m3u: $(wc -l < "$PLAYLIST_DIR/prelinger.m3u") files"
