# Max Headroom Video System

Multi-channel video streaming system for CRT quad-mux display.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           loki.local                                │
│  /mnt/media/           ──transcode──▶  /mnt/media_transcoded/      │
│  (originals)              (NVENC)       (960x540 H.264)            │
└─────────────────────────────────────────────────────────────────────┘
                                              │
                                              │ rsync
                                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         headroom.local                              │
│  /mnt/media/  ──▶  liquidsoap  ──▶  VAAPI encode  ──▶  Icecast/HLS │
│  (deployed)                                                         │
└─────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                                    HDMI Quad Splitter ──▶ CRTs
```

## Directory Structure

### loki.local (Transcoding Server)

| Directory | Purpose |
|-----------|---------|
| `/mnt/media/` | **Source** - Original downloaded videos |
| `/mnt/media_transcoded/` | **Output** - Transcoded 960x540 H.264 |
| `/mnt/media_originals_backup/` | **Backup** - Archived headroom originals |

**Structure mirrors exactly:**
```
/mnt/media/gaming_memes/short/Video.webm
     ↓ transcode
/mnt/media_transcoded/gaming_memes/short/Video.mp4
```

### headroom.local (Streaming Server)

| Directory | Purpose |
|-----------|---------|
| `/mnt/media/` | Deployed transcoded videos (from loki) |
| `/home/max/playlists/` | M3U playlists (auto-generated) |
| `/home/max/liquidsoap/` | Liquidsoap config |

## Quick Start: Adding New Videos

```bash
# On loki.local:

# 1. Download video to appropriate category
cd /mnt/media/<category>/<length>/
yt-dlp "https://youtube.com/..."

# 2. Transcode all new files
~/bin/transcode-for-quadmux.sh

# 3. Push to headroom
~/bin/push-to-headroom.sh

# On headroom.local:

# 4. Regenerate playlists & restart
sudo -u max /home/max/bin/regenerate-playlists.sh
sudo systemctl restart max-liquidsoap
```

## Category Structure

Videos are organized by category and length:

```
/mnt/media/
├── prelinger/              # Prelinger Archive (own subdirs by topic)
│   ├── 1970s/
│   ├── automobiles/
│   └── ...
├── gaming_memes/
│   ├── short/              # < 5 min (goes in all-short.m3u)
│   ├── medium/             # 5-30 min
│   └── long/               # > 30 min (goes in all-long.m3u)
├── house_music/
├── british_surreal_comedy/
├── surreal_talkshows/
└── ...
```

### Adding New Media (Automated Pipeline)

1. **Download** to `/mnt/incoming/<category>/<length>/` on loki
2. **Wait** — cron runs `process-incoming.sh` every 5 minutes
3. Pipeline automatically: catalogues → transcodes → pushes to headroom → regenerates playlists

### Downloading from YouTube (on loki.local)

```bash
# Check video info
~/.local/bin/yt-dlp --get-title --get-duration 'URL'

# Download to incoming (pipeline handles the rest)
~/.local/bin/yt-dlp -f 'bestvideo+bestaudio/best' \
    -o '/mnt/incoming/<category>/<length>/%(title)s.%(ext)s' 'URL'
```

Categories: `cyberpunk_anime`, `darkwave_postpunk`, `house_music`, `neon_synthpop`, etc.
Length: `short` (<5min), `medium` (5-30min), `long` (>30min)

Create new categories as needed - just add a directory.

### Manual Pipeline (if needed)

```bash
~/bin/process-incoming.sh        # Process incoming now
# Or individual steps:
~/bin/transcode-for-quadmux.sh   # Transcode /mnt/media/ → /mnt/media_transcoded/
~/bin/push-to-headroom.sh        # Push to headroom
```

### Transcoding Specs

| Parameter | Value |
|-----------|-------|
| Resolution | 960x540 |
| Codec | H.264 (NVENC) |
| Video bitrate | 1.2 Mbps |
| Audio | AAC 128kbps stereo |
| Container | MP4 |

## Documentation

- [Downloading Guide](docs/downloading.md) - Acquiring content from YouTube
- [Transcoding Workflow](docs/transcoding-workflow.md) - Converting for CRT output
- [System Tuning](docs/system-tuning.md) - Performance optimization
- [Troubleshooting](docs/troubleshooting.md) - Common issues and fixes

## Services (headroom.local)

```bash
sudo systemctl status max-liquidsoap    # Video channels
sudo systemctl status max-hls-ch1       # HLS segmenter ch1
sudo systemctl status max-hls-ch2       # HLS segmenter ch2
sudo systemctl status headroom-perf-tuning  # Performance settings
```

## Hardware

| Host | CPU | GPU | Role |
|------|-----|-----|------|
| loki.local | Ryzen 9 5950X | RTX 4080 (NVENC) | Transcoding |
| headroom.local | i5-14450HX | Intel UHD (VAAPI) | Streaming |
