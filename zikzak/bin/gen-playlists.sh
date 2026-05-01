#!/bin/bash
# Regenerates reference playlists from /mnt/media directory structure.
#
# NOTE: liquidsoap does NOT use these playlists for channel programming.
# channels.liq uses dir_src() with reload_mode="watch" to read media
# directories directly. New files are picked up automatically by inotify.
#
# These playlists exist for diagnostics, external players, and auditing:
#   music-long.m3u    — long-form music files (reference)
#   short-medium.m3u  — short + medium content, all categories (reference)
#   all-short.m3u, all-long.m3u, all.m3u — duration buckets
#   <category>.m3u — one per top-level category
#
# Run manually or via watch-media.sh on inotify events.

set -euo pipefail

MEDIA_ROOT="/mnt/media"
PLAYLIST_DIR="/home/max/playlists"
INTERLEAVE="/home/max/bin/interleave-playlist.py"
VIDEO_EXTS="mp4|mkv|avi|mov|webm|mpg|mpeg|m4v|ts|ogv|flv"

# Categories that belong on the music channel.
# Long files from these go to music-long.m3u.
# Short/medium files from these still appear in short-medium.m3u.
MUSIC_CATEGORIES="house_music darkwave_postpunk deep_techno neon_synthpop gaelic_resistance aphex_twin metal punk vintage_music music_videos"

mkdir -p "$PLAYLIST_DIR"

echo "Regenerating playlists from $MEDIA_ROOT..."

find_videos() {
    find "$MEDIA_ROOT" -type f -regextype posix-extended \
        -iregex ".*\.($VIDEO_EXTS)$" "$@"
}

# ── Per-category playlists ─────────────────────────────────────────────────────

for catdir in "$MEDIA_ROOT"/*/; do
    cat=$(basename "$catdir")
    playlist="$PLAYLIST_DIR/${cat}.m3u"
    find_videos -path "$catdir*" | shuf > "$playlist"
    count=$(wc -l < "$playlist")
    echo "  $cat: $count files -> $playlist"
done

# ── Liquidsoap channel playlists ───────────────────────────────────────────────

# music-long.m3u: long-form music for ch1 (uninterrupted music channel)
# Includes:
#   - files in <music_category>/long/ subdirs
#   - files directly in <music_category>/ with no length subdir (assumed long sets)
music_long_tmp=$(mktemp)
trap 'rm -f "$music_long_tmp"' EXIT

for cat in $MUSIC_CATEGORIES; do
    catdir="$MEDIA_ROOT/$cat"
    [[ -d "$catdir" ]] || continue
    # Files in the long/ subdir
    find "$catdir/long" -type f -regextype posix-extended \
        -iregex ".*\.($VIDEO_EXTS)$" 2>/dev/null >> "$music_long_tmp" || true
    # Files directly in the category root (no length subdir) — these are long DJ sets
    find "$catdir" -maxdepth 1 -type f -regextype posix-extended \
        -iregex ".*\.($VIDEO_EXTS)$" 2>/dev/null >> "$music_long_tmp" || true
done

python3 "$INTERLEAVE" < "$music_long_tmp" > "$PLAYLIST_DIR/music-long.m3u.tmp"
mv "$PLAYLIST_DIR/music-long.m3u.tmp" "$PLAYLIST_DIR/music-long.m3u"
echo "  music-long: $(wc -l < "$PLAYLIST_DIR/music-long.m3u") files -> $PLAYLIST_DIR/music-long.m3u"

# short-medium.m3u: short + medium content for ch2/3/4 (programmed channels)
# Includes all categories (music short/medium clips are included here too).
# Excludes: interstitials, joke_commercials (those are injected by liquidsoap).
short_medium_tmp=$(mktemp)
trap 'rm -f "$music_long_tmp" "$short_medium_tmp"' EXIT

find_videos -ipath "*/short/*" \
    ! -ipath "*/interstitials/*" \
    ! -ipath "*/joke_commercials/*" \
    > "$short_medium_tmp"
find_videos -ipath "*/medium/*" \
    ! -ipath "*/interstitials/*" \
    ! -ipath "*/joke_commercials/*" \
    >> "$short_medium_tmp"

python3 "$INTERLEAVE" < "$short_medium_tmp" > "$PLAYLIST_DIR/short-medium.m3u.tmp"
mv "$PLAYLIST_DIR/short-medium.m3u.tmp" "$PLAYLIST_DIR/short-medium.m3u"
echo "  short-medium: $(wc -l < "$PLAYLIST_DIR/short-medium.m3u") files -> $PLAYLIST_DIR/short-medium.m3u"

# ── Reference playlists (duration buckets) ─────────────────────────────────────

short_tmp=$(mktemp)
long_tmp=$(mktemp)
other_tmp=$(mktemp)
trap 'rm -f "$music_long_tmp" "$short_medium_tmp" "$short_tmp" "$long_tmp" "$other_tmp"' EXIT

find_videos -ipath "*/short/*" > "$short_tmp"
find_videos -ipath "*/long/*" > "$long_tmp"
find_videos ! -ipath "*/short/*" ! -ipath "*/medium/*" ! -ipath "*/long/*" > "$other_tmp"

python3 "$INTERLEAVE" < "$short_tmp" > "$PLAYLIST_DIR/all-short.m3u"
cat "$long_tmp" "$other_tmp" | python3 "$INTERLEAVE" > "$PLAYLIST_DIR/all-long.m3u"
find_videos | python3 "$INTERLEAVE" > "$PLAYLIST_DIR/all.m3u"

echo "  all-short: $(wc -l < "$PLAYLIST_DIR/all-short.m3u") files"
echo "  all-long: $(wc -l < "$PLAYLIST_DIR/all-long.m3u") files"
echo "  all: $(wc -l < "$PLAYLIST_DIR/all.m3u") files"

echo "Done."
