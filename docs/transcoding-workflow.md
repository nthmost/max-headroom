# Transcoding Workflow

## Directory Structure

### The Three Directories on loki.local

```
/mnt/media/                      # SOURCE: Original media files
├── prelinger/
│   ├── 1970s/
│   ├── automobiles/
│   └── ...
├── house_music/
├── gaming_memes/
│   ├── short/
│   └── bg3/
│       └── short/
└── ...

/mnt/media_transcoded/           # OUTPUT: Transcoded files (mirrored structure)
├── prelinger/
│   ├── 1970s/
│   │   └── *.mp4               # Same filenames, .mp4 extension
│   ├── automobiles/
│   └── ...
├── house_music/
│   └── *.mp4
└── ...

/mnt/media_originals_backup/     # BACKUP: Copy of headroom's original files
└── (archived, don't modify)
```

### How Mirroring Works

The transcode script **preserves the exact directory structure**:

```
SOURCE:  /mnt/media/gaming_memes/bg3/short/Frank Reynolds.webm
OUTPUT:  /mnt/media_transcoded/gaming_memes/bg3/short/Frank Reynolds.mp4
                               └── same path ──────────┘        └── .mp4
```

**Important:** 
- Directory structure is automatically mirrored
- Only the file extension changes (→ `.mp4`)
- Original files are NOT modified or deleted
- Transcoded files completely replace originals on headroom

### On headroom.local

```
/mnt/media/                      # DEPLOYED: Transcoded files from loki
├── prelinger/                   # (mirrors /mnt/media_transcoded/ from loki)
├── house_music/
├── gaming_memes/
└── ...

/home/max/playlists/             # Generated from /mnt/media/
├── all.m3u                      # All files
├── all-short.m3u                # < 5 min
├── all-long.m3u                 # > 30 min
├── prelinger.m3u                # Per-category
├── house_music.m3u
└── ...
```

## Transcode Specs

| Parameter | Value |
|-----------|-------|
| Resolution | 960x540 |
| Codec | H.264 Main Profile (NVENC) |
| Video bitrate | 1.2 Mbps |
| Audio | AAC 128kbps stereo 44.1kHz |
| Container | MP4 (faststart) |

## Adding New Videos

### Step 1: Place Videos on loki.local

Add files to `/mnt/media/` following the category/length structure:

**See [Downloading Guide](downloading.md) for detailed instructions on acquiring content from YouTube.**

Place files in:
```bash
/mnt/media/<category>/<length>/filename.ext
```

**Categories** (create new ones as needed):
- `prelinger/` - Prelinger Archive (has its own subdirs by topic)
- `house_music/` - Music mixes
- `gaming_memes/` - Gaming content  
- `british_surreal_comedy/` - Comedy sketches
- `gaelic_resistance/` - Irish language music
- `surreal_talkshows/` - Space Ghost, etc.
- `darkwave_postpunk/` - Cold wave, post-punk, darkwave
- `cyberpunk_anime/` - Cyberpunk aesthetic anime, AMVs
- `neon_synthpop/` - Synthwave, retrowave
- etc. (see [full category list](downloading.md#current-categories))

**Length subdirectories** (used for playlist generation):
- `short/` - Under 5 minutes
- `medium/` - 5-30 minutes  
- `long/` - Over 30 minutes

**Example:**
```bash
# New YouTube download goes here:
/mnt/media/gaming_memes/short/New Funny Video.webm
```

### Step 2: Run Transcode

```bash
cd ~/bin
./transcode-for-quadmux.sh
```

**What happens:**
1. Scans `/mnt/media/` for video files (.mp4, .webm, .mkv, .ogv, .avi)
2. For each file, creates matching path in `/mnt/media_transcoded/`
3. Transcodes to 960x540 H.264 using NVENC
4. Adds silent audio track if source has no audio
5. Skips files already transcoded (safe to re-run)

**Output:**
```
[1/100] Transcoding: gaming_memes/short/New Funny Video.webm
  -> OK
[2/100] SKIP: gaming_memes/short/Old Video.webm  (already done)
...
```

**Logs:** `/var/log/transcode/success_*.log`, `fail_*.log`

### Step 3: Push to headroom

```bash
./push-to-headroom.sh
```

This runs:
```bash
rsync -avh /mnt/media_transcoded/ headroom.local:/mnt/media/
```

**Note:** This REPLACES files on headroom. The original mixed-format files should have been deleted already (we did this in initial setup).

### Step 4: Update Playlists (on headroom)

```bash
ssh headroom.local
sudo -u max /home/max/bin/regenerate-playlists.sh
sudo systemctl restart max-liquidsoap
```

## Complete Example: Adding a YouTube Video

```bash
# 1. On loki, download video to correct location
cd /mnt/media/gaming_memes/short/
yt-dlp "https://youtube.com/watch?v=xxxxx"

# 2. Transcode (only processes new files)
~/bin/transcode-for-quadmux.sh

# 3. Push to headroom
~/bin/push-to-headroom.sh

# 4. On headroom, update playlists
ssh headroom.local
sudo -u max /home/max/bin/regenerate-playlists.sh
sudo systemctl restart max-liquidsoap
```

## Manual Single-File Transcode

For testing or one-off files:

```bash
ffmpeg -i input.webm \
    -vf "scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:-1:-1:color=black" \
    -c:v h264_nvenc -preset p4 -b:v 1200k -profile:v main \
    -c:a aac -b:a 128k -ar 44100 -ac 2 \
    -movflags +faststart \
    output.mp4
```

For files without audio:
```bash
ffmpeg -i input.webm \
    -f lavfi -i anullsrc=r=44100:cl=stereo \
    -vf "scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:-1:-1:color=black" \
    -c:v h264_nvenc -preset p4 -b:v 1200k -profile:v main \
    -map 0:v -map 1:a -c:a aac -b:a 128k -ar 44100 -shortest \
    -movflags +faststart \
    output.mp4
```

## Storage Estimates

| Duration | Transcoded Size |
|----------|-----------------|
| 1 hour | ~550 MB |
| 10 hours | ~5.5 GB |
| 100 hours | ~55 GB |

(At 1.2 Mbps video + 128kbps audio ≈ 600 MB/hour)
