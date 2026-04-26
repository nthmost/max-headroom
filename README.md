# Max Headroom Video System

Multi-channel video streaming system for CRT quad-mux display.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          loki.local                                  │
│               Intake Web App · Download · Transcode                  │
│                                                                     │
│  YouTube: yt-dlp ──────────────────────────────────────────────┐    │
│                                                                 │    │
│  Internet Archive:                                             │    │
│  /mnt/incoming/ ──transcode (VAAPI)──▶ /mnt/media_transcoded/ │    │
│  (new downloads)   960x540 H.264           │                   │    │
│         │                                  │ rsync             │    │
│         └──catalogue──▶ /mnt/media/        │ (bwlimit=20MB/s)  │    │
└────────────────────────────────────────────┼───────────────────┘    │
                                             │                        │
                                             ▼                        │ rsync
┌─────────────────────────────────────────────────────────────────────┐
│                         zikzak (Noisebridge)                        │
│               i7 + GTX 1060 · Streaming Server                      │
│                                                                     │
│  /mnt/media/  ──▶  liquidsoap  ──▶  NVENC encode  ──▶  Icecast     │
│  (media files)      4 channels      H.264/AAC      localhost:8000   │
│                                                          │           │
│  HDMI Quad Splitter ──▶ CRTs        relay ffmpeg ───────┘           │
│  (local display)        (ch1-4)     (mhbn-relay-ch{1-4})            │
└──────────────────────────────────────────────────┼──────────────────┘
                                                   │ mpegts copy
                                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    zephyr (nthmost.com)                             │
│                                                                     │
│  Icecast nthmost.com:8000/mhbn-ch{1-4}.ts                          │
│      ──▶  HLS segmenter (mhbn-hls-ch{1-4})                         │
│      ──▶  /var/www/hls/mhbn-ch{N}/index.m3u8                       │
│      ──▶  nginx ──▶ headroom.nthmost.com (hls.js webapp)           │
└─────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

### loki.local (Intake + Transcode)

| Directory | Purpose |
|-----------|---------|
| `/mnt/incoming/` | **Incoming** - New IA downloads (auto-processed by cron) |
| `/mnt/media/` | **Originals** - Catalogued source files |
| `/mnt/media_transcoded/` | **Output** - Transcoded 960x540 H.264 (auto-cleanup after 7 days) |

### zikzak (Streaming Server)

| Directory | Purpose |
|-----------|---------|
| `/mnt/media/` | **Media files** - 960x540 H.264 (from loki) and YouTube downloads |
| `/home/max/playlists/` | M3U playlists (auto-generated) |
| `/home/max/liquidsoap/` | Liquidsoap config + log |
| `/home/max/bin/` | HLS segmenter scripts (`hls-ch{1-4}.sh`) |

**Channel playlist assignments:**

| Channel | Playlist | Content |
|---------|----------|---------|
| ch1 | `all-long.m3u` | Files > 30 min |
| ch2 | `all-short.m3u` | Files < 5 min |
| ch3 | `mixed.m3u` | Mixed lengths |
| ch4 | `mixed.m3u` | Mixed lengths |

**Workflow (Internet Archive):**
```
loki:/mnt/incoming/gaming_memes/short/Video.webm
     ↓ catalogue
loki:/mnt/media/gaming_memes/short/Video.webm
     ↓ transcode (VAAPI, 960x540 H.264)
loki:/mnt/media_transcoded/gaming_memes/short/Video.mp4
     ↓ rsync (bwlimit=20MB/s)
zikzak:/mnt/media/gaming_memes/short/Video.mp4
     ↓ liquidsoap streams from here to icecast2
```

**Workflow (YouTube):**
```
loki: yt-dlp download to staging
     ↓ rsync directly
zikzak:/mnt/media/gaming_memes/short/Video.mp4
     ↓ liquidsoap streams from here to icecast2
```

## Quick Start: Adding New Videos

```bash
# On loki.local:

# 1. Download video to incoming directory
yt-dlp -f 'bestvideo+bestaudio/best' \
    -o '/mnt/incoming/<category>/<length>/%(title)s.%(ext)s' 'URL'

# 2. Wait for cron (runs every 5 min) or manually run:
~/bin/process-incoming.sh

# This automatically:
#   - Catalogues to /mnt/media/
#   - Transcodes with VAAPI to /mnt/media_transcoded/
#   - Pushes to zikzak:/mnt/media/
#   - Regenerates playlists on zikzak
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

### Adding New Media

Use the **intake web app** at `http://loki.local:8765/` — paste a YouTube URL or Internet Archive identifier, pick a category, and queue it. The app handles download, transcode (if needed), push to zikzak, and playlist regeneration automatically.

### Manual Pipeline (if needed)

```bash
# On loki.local:
~/bin/process-incoming.sh        # Process /mnt/incoming/ now (full pipeline)

# Or individual steps:
~/bin/transcode-for-quadmux.sh   # Transcode /mnt/media/ → /mnt/media_transcoded/
~/bin/push-to-zikzak.sh          # Push to zikzak and trigger playlist regen
~/bin/cleanup-transcoded.sh      # Cleanup old transcoded files (run weekly)
```

### Transcoding Specs

| Parameter | Value |
|-----------|-------|
| Resolution | 960x540 |
| Codec | H.264 (VAAPI - Intel UHD GPU) |
| Video bitrate | 1.2 Mbps |
| Audio | AAC 128kbps stereo |
| Container | MP4 |

## Documentation

- [Downloading Guide](docs/downloading.md) - Acquiring content from YouTube
- [Transcoding Workflow](docs/transcoding-workflow.md) - Converting for CRT output
- [System Tuning](docs/system-tuning.md) - Performance optimization
- [Troubleshooting](docs/troubleshooting.md) - Common issues and fixes

## Services

### loki.local (Intake + Transcode)
```bash
# Intake web app
sudo systemctl status intake

# Cron jobs
crontab -l  # process-incoming.sh (every 5 min), cleanup-transcoded.sh (weekly)
```

### zikzak (Streaming)
```bash
# Liquidsoap (all 4 channels)
sudo systemctl status zikzak-liquidsoap

# Local HLS segmenters (feed quadmux display via mpv)
sudo systemctl status zikzak-hls-ch{1,2,3,4}

# Relay to nthmost.com Icecast
sudo systemctl status mhbn-relay-ch{1,2,3,4}

sudo systemctl status icecast2

# Liquidsoap telnet interface (127.0.0.1:1234)
echo -e "ch2.skip\nquit" | nc -q1 127.0.0.1 1234   # skip current ch2 track
echo -e "request.on_air\nquit" | nc -q1 127.0.0.1 1234  # show playing files
echo -e "help\nquit" | nc -q1 127.0.0.1 1234  # full command list
```

### zephyr (Public HLS delivery — nthmost.com)
```bash
# HLS segmenters (one per channel)
sudo systemctl status mhbn-hls-ch{1,2,3,4}

# Segments served at /var/www/hls/mhbn-ch{N}/index.m3u8
# Webapp at headroom.nthmost.com uses hls.js with liveSyncDurationCount:3
```

## Hardware

| Host | CPU | GPU | Role |
|------|-----|-----|------|
| loki.local | i5-14450HX | Intel UHD (VAAPI) | Intake app, IA transcode, YouTube download |
| zikzak | i7 | GTX 1060 (NVENC) | Streaming server — Liquidsoap + 4-ch encode → Icecast |
| zephyr | — | — | VPS (nthmost.com) — Icecast relay + HLS segmenters + nginx |
