#!/bin/bash
# Regenerate playlists from /mnt/media/category/length/file.mp4 structure.
# No ffprobe needed — directory name encodes length (short/medium/long).
# Prelinger uses thematic subdirs (no length classification) and is included in all channels.

MEDIA_DIR="/mnt/media"
PLAYLIST_DIR="/home/max/playlists"
TEMP_DIR=$(mktemp -d)

echo "Regenerating playlists from $MEDIA_DIR..."

# Per-category playlists
for dir in "$MEDIA_DIR"/*/; do
    category=$(basename "$dir")
    find "$dir" -type f \( -name '*.mp4' -o -name '*.webm' -o -name '*.mkv' \) | sort > "$TEMP_DIR/${category}.m3u"
    count=$(wc -l < "$TEMP_DIR/${category}.m3u")
    echo "  $category: $count files"
done

# music-long.m3u — ch1: long-form music + prelinger
find "$MEDIA_DIR/music/long" -type f -name '*.mp4' | sort > "$TEMP_DIR/music-long.m3u"
find "$MEDIA_DIR/prelinger" -type f -name '*.mp4' | sort >> "$TEMP_DIR/music-long.m3u"

# short-medium.m3u — ch2/3/4: all short+medium content (except music) + prelinger
> "$TEMP_DIR/short-medium.m3u"
for dir in "$MEDIA_DIR"/*/; do
    category=$(basename "$dir")
    [ "$category" = "music" ] && continue
    [ "$category" = "prelinger" ] && continue
    for length in short medium; do
        [ -d "${dir}${length}" ] && find "${dir}${length}" -type f -name '*.mp4' >> "$TEMP_DIR/short-medium.m3u"
    done
done
find "$MEDIA_DIR/prelinger" -type f -name '*.mp4' >> "$TEMP_DIR/short-medium.m3u"
sort -o "$TEMP_DIR/short-medium.m3u" "$TEMP_DIR/short-medium.m3u"

# Aggregate playlists
find "$MEDIA_DIR" -type f -name '*.mp4' | sort        > "$TEMP_DIR/all.m3u"
find "$MEDIA_DIR" -path '*/short/*.mp4'  | sort       > "$TEMP_DIR/all-short.m3u"
find "$MEDIA_DIR" -path '*/long/*.mp4'   | sort       > "$TEMP_DIR/all-long.m3u"
find "$MEDIA_DIR" -path '*/medium/*.mp4' | sort       > "$TEMP_DIR/all-medium.m3u"

# Atomic move to playlist dir
for f in "$TEMP_DIR"/*.m3u; do
    mv "$f" "$PLAYLIST_DIR/$(basename "$f")"
done
rm -rf "$TEMP_DIR"

echo ''
echo '=== Key playlists for liquidsoap ==='
echo "  music-long.m3u:   $(wc -l < "$PLAYLIST_DIR/music-long.m3u") files  (ch1)"
echo "  short-medium.m3u: $(wc -l < "$PLAYLIST_DIR/short-medium.m3u") files  (ch2/3/4)"
echo ''
echo '=== All playlists ==='
wc -l "$PLAYLIST_DIR"/*.m3u | sort -rn | head -20
