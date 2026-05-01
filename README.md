# Max Headroom Video System

Multi-channel video streaming system for CRT quad-mux display.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          loki.nthmost.net                                  │
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

### loki.nthmost.net (Intake + Transcode)

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
| ch1 | `music-long.m3u` | Music — long + medium tracks only |
| ch2 | `short-medium.m3u` | Mixed general content (short + medium) |
| ch3 | `short-medium.m3u` | Mixed general content (short + medium) |
| ch4 | `short-medium.m3u` | Mixed general content (short + medium) |

ch2/3/4 inject an interstitial after every clip and a commercial every 10th clip via liquidsoap request.queue.

**Workflow (Internet Archive):**
```
loki:/mnt/incoming/<category>/<length>/Video.webm
     ↓ catalogue + transcode (NVENC, 960x540 H.264)
loki:/mnt/media_transcoded/<category>/<length>/Video.mp4
     ↓ rsync (bwlimit=20MB/s)
zikzak:/mnt/media/<category>/<length>/Video.mp4  +  DB record in mhbn
     ↓ liquidsoap streams from here to icecast2
```

**Workflow (YouTube):**
```
loki: yt-dlp download to staging (via intake web app)
     ↓ rsync directly to zikzak
zikzak:/mnt/media/<category>/<length>/Video.mp4  +  DB record in mhbn
     ↓ liquidsoap streams from here to icecast2
```

## Quick Start: Adding New Videos

Use the **intake web app** at `https://zikzak.nthmost.net/` — paste a YouTube URL or Internet Archive identifier, pick a category and length, and queue it. The app handles download, transcode, push to zikzak, and playlist regeneration automatically.

After adding new content, regenerate playlists on zikzak:
```bash
ssh -J zephyr nthmost@10.100.0.5 "bash /home/nthmost/regenerate-playlists.sh"
```

## Category Structure

Media lives on zikzak at `/mnt/media/`. All folders use `short/medium/long/` subdirs except prelinger which retains its original topic-based subdirs.

```
/mnt/media/
├── action/          short medium long
├── anime/           short medium long
├── cartoons/        short medium long
├── comedy/          short medium long
├── commercials/     short medium long   ← injected every 10th clip on ch2/3/4
├── documentaries/   short medium long
├── gaming/          short medium long
├── interstitials/   short medium long   ← injected between every clip on ch2/3/4
├── music/           short medium long   ← ch1 plays long+medium only
├── philosophy/      short medium long
├── prelinger/       1970s/ automobiles/ animation/ atomic/ ...  (804 files, topic subdirs)
└── tv_shows/        short medium long
```

**Category tags** (DB only, no physical folder) track sub-genres and provenance:
`adult_swim`, `rick_and_morty`, `space_ghost`, `talkshow`, `surreal`, `vintage`, `cyberpunk`, `retro`, `flash`, `homestar_runner`, `gaming` sub-genres, prelinger collection names, etc.

### Adding New Media

Use the **intake web app** at `http://loki.nthmost.net:8765/` — paste a YouTube URL or Internet Archive identifier, pick a category, and queue it. The app handles download, transcode (if needed), push to zikzak, and playlist regeneration automatically.

### Manual Pipeline (if needed)

```bash
# On loki.nthmost.net:
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

### loki.nthmost.net (Intake + Transcode)
```bash
sudo systemctl status intake                # Intake web app (port 8765)
sudo systemctl status zikzak-pg-tunnel      # autossh tunnel → zikzak postgres
```

### zikzak (Streaming + DB)
```bash
sudo systemctl status zikzak-liquidsoap    # Liquidsoap 4-channel video
sudo systemctl status max-hls-ch{1,2,3,4} # HLS segmenters (local display)
sudo systemctl status icecast2             # Local Icecast

# Liquidsoap telnet (127.0.0.1:1234)
echo -e "ch2.skip\nquit" | nc -q1 127.0.0.1 1234        # skip current ch2 track
echo -e "request.on_air\nquit" | nc -q1 127.0.0.1 1234  # show now-playing
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
| loki.nthmost.net | Ryzen 9 5950X | RTX 4080 (NVENC) | Intake app, IA transcode, YouTube download |
| zikzak | i7 | GTX 1060 (NVENC) | Streaming server — Liquidsoap + 4-ch encode → Icecast, PostgreSQL DB |
| zephyr | — | — | VPS (nthmost.com) — Icecast relay + HLS segmenters + nginx |
