# Transcoding Workflow

## Directory Structure

### The Directories on loki.nthmost.net

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

/mnt/incoming/                   # INCOMING: New downloads (auto-processed)
├── <category>/
│   ├── short/
│   ├── medium/
│   └── long/
└── ...
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
- Transcoded files completely replace originals on loki

### Playlists on zikzak.local

```
/home/max/playlists/             # Generated from /mnt/media_transcoded/
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
| Codec | H.264 Main Profile (NVENC - RTX 4080 on loki) |
| Video bitrate | 1.2 Mbps |
| Audio | AAC 128kbps stereo 44.1kHz |
| Container | MP4 (faststart) |

**Note:** loki uses NVIDIA NVENC (RTX 4080), not VAAPI. The `max` user must be in the `video` and `render` groups for GPU access.

## Adding New Videos

### Step 1: Place Videos on loki.nthmost.net

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
3. Transcodes to 960x540 H.264 using NVENC (RTX 4080)
4. Adds silent audio track if source has no audio
5. Skips files already transcoded (safe to re-run)

**GPU requirements:** The `max` user needs to be in `video` and `render` groups:
```bash
sudo usermod -aG video,render max
```

**Output:**
```
[1/100] Transcoding: gaming_memes/short/New Funny Video.webm
  -> OK
[2/100] SKIP: gaming_memes/short/Old Video.webm  (already done)
...
```

**Logs:** `/var/log/transcode/success_*.log`, `fail_*.log`

### Step 3: Push to zikzak

```bash
./push-to-zikzak.sh
```

This will:
1. Rsync transcoded files to zikzak (bandwidth-limited to 20MB/s)
2. Trigger playlist regeneration on zikzak
3. New files become available for streaming

**Note:** Bandwidth is limited to avoid interrupting zikzak's icecast2 stream.

## Complete Example: Adding a YouTube Video

```bash
# On loki.nthmost.net:

# 1. Download video to incoming directory
yt-dlp -f 'bestvideo+bestaudio/best' \
    -o '/mnt/incoming/gaming_memes/short/%(title)s.%(ext)s' \
    "https://youtube.com/watch?v=xxxxx"

# 2. Process (or wait for cron)
~/bin/process-incoming.sh

# This automatically:
#   - Catalogues to /mnt/media/
#   - Transcodes with VAAPI
#   - Pushes to zikzak (bwlimit=20MB/s)
#   - Regenerates playlists on zikzak

# 3. Files are auto-cleaned up after 7 days on loki
```

### Manual workflow (if you need more control):

```bash
# On loki.nthmost.net:

# 1. Download to media directly
cd /mnt/media/gaming_memes/short/
yt-dlp "https://youtube.com/watch?v=xxxxx"

# 2. Transcode
~/bin/transcode-for-quadmux.sh

# 3. Push to zikzak
~/bin/push-to-zikzak.sh
```

## Manual Single-File Transcode

For testing or one-off files (using NVENC on loki):

```bash
ffmpeg -hwaccel cuda -hwaccel_output_format cuda \
    -i input.webm \
    -vf "scale_cuda=960:540:force_original_aspect_ratio=decrease" \
    -c:v h264_nvenc -preset p4 -b:v 1200k -profile:v main \
    -c:a aac -b:a 128k -ar 44100 -ac 2 \
    -movflags +faststart \
    output.mp4
```

For files without audio:
```bash
ffmpeg -hwaccel cuda -hwaccel_output_format cuda \
    -i input.webm \
    -f lavfi -i anullsrc=r=44100:cl=stereo \
    -vf "scale_cuda=960:540:force_original_aspect_ratio=decrease" \
    -c:v h264_nvenc -preset p4 -b:v 1200k -profile:v main \
    -map 0:v -map 1:a -c:a aac -b:a 128k -ar 44100 -shortest \
    -movflags +faststart \
    output.mp4
```

**For headroom** (which has Intel VAAPI):
```bash
ffmpeg -vaapi_device /dev/dri/renderD128 \
    -i input.webm \
    -vf "format=nv12,hwupload,scale_vaapi=960:540:force_original_aspect_ratio=decrease" \
    -c:v h264_vaapi -b:v 1200k -profile:v main \
    -c:a aac -b:a 128k -ar 44100 -ac 2 \
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
