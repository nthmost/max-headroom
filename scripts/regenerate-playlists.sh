#!/bin/bash
#
# Regenerate playlists from actual files on disk.
# Run on zikzak after any media reorganization.
#
# ch1 (music)       → music-long.m3u    (music/long + music/medium)
# ch2/3/4 (mixed)   → short-medium.m3u  (short+medium from general categories)
# prelinger         → prelinger.m3u     (standalone — all lengths)
# per-category      → <cat>.m3u         (one per active folder, for future use)

MEDIA_DIR="/mnt/media"
PLAYLIST_DIR="/home/max/playlists"
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Folders excluded from short-medium.m3u (handled separately by liquidsoap)
EXCLUDE="music prelinger interstitials commercials"

echo "Regenerating playlists from $MEDIA_DIR..."

# ── Per-category playlists ────────────────────────────────────────────────────
for dir in "$MEDIA_DIR"/*/; do
    category=$(basename "$dir")
    [[ $category == lost+* ]] && continue
    find "$dir" -type f \( -name "*.mp4" -o -name "*.webm" -o -name "*.mkv" \) | sort \
        > "$TEMP_DIR/${category}.m3u"
    count=$(wc -l < "$TEMP_DIR/${category}.m3u")
    echo "  $category: $count files"
done

# ── music-long.m3u: long + medium music tracks ────────────────────────────────
> "$TEMP_DIR/music-long.m3u"
for subdir in long medium; do
    find "$MEDIA_DIR/music/$subdir" -type f \( -name "*.mp4" -o -name "*.webm" \) 2>/dev/null | sort \
        >> "$TEMP_DIR/music-long.m3u"
done
echo ""
echo "  music-long.m3u: $(wc -l < "$TEMP_DIR/music-long.m3u") files"

# ── short-medium.m3u: short + medium from general content categories ──────────
> "$TEMP_DIR/short-medium.m3u"
for dir in "$MEDIA_DIR"/*/; do
    category=$(basename "$dir")
    [[ $category == lost+* ]] && continue
    skip=false
    for ex in $EXCLUDE; do
        [[ $category == $ex ]] && skip=true && break
    done
    $skip && continue
    for subdir in short medium; do
        find "$dir/$subdir" -type f \( -name "*.mp4" -o -name "*.webm" -o -name "*.mkv" \) 2>/dev/null | sort \
            >> "$TEMP_DIR/short-medium.m3u"
    done
done
echo "  short-medium.m3u: $(wc -l < "$TEMP_DIR/short-medium.m3u") files"

# ── Atomic deploy ─────────────────────────────────────────────────────────────
echo ""
echo "Deploying to $PLAYLIST_DIR..."
for f in "$TEMP_DIR"/*.m3u; do
    sudo mv "$f" "$PLAYLIST_DIR/$(basename "$f")"
done

echo ""
echo "Done. Key playlists:"
echo "  music-long.m3u:  $(wc -l < "$PLAYLIST_DIR/music-long.m3u") files  (ch1)"
echo "  short-medium.m3u: $(wc -l < "$PLAYLIST_DIR/short-medium.m3u") files  (ch2/3/4)"
echo "  prelinger.m3u:   $(wc -l < "$PLAYLIST_DIR/prelinger.m3u") files"
