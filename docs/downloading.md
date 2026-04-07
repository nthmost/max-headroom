# Downloading Videos

Guide for acquiring new content from YouTube and other sources.

## Overview

```
┌──────────────┐     ┌─────────────────────────┐     ┌─────────────────────┐
│   YouTube    │────▶│       loki.local        │────▶│   headroom.local    │
│   (source)   │     │  /mnt/incoming/<cat>/   │     │    /mnt/media/      │
└──────────────┘     └─────────────────────────┘     └─────────────────────┘
                              ↓ (cron every 5 min)
                     ┌─────────────────────────┐
                     │ process-incoming.sh     │
                     │ 1. Move to /mnt/media/  │
                     │ 2. Transcode (NVENC)    │
                     │ 3. Push to headroom     │
                     │ 4. Regenerate playlists │
                     └─────────────────────────┘
```

**Drop downloads into `/mnt/incoming/<category>/<length>/` on loki.local.**  
The pipeline automatically catalogues, transcodes, and deploys to headroom.

## Requirements

### yt-dlp Installation (loki.local)

The system `yt-dlp` may be outdated. Use the pipx-installed version:

```bash
# Check version
~/.local/bin/yt-dlp --version

# Update if needed
pipx upgrade yt-dlp
```

**Current path:** `~/.local/bin/yt-dlp`

## Directory Structure

Downloads go to the **incoming** directory, respecting the aesthetic categorization:

```
/mnt/incoming/                    <-- DROP DOWNLOADS HERE
├── british_surreal_comedy/
│   ├── short/      # < 5 minutes
│   ├── medium/     # 5-30 minutes
│   └── long/       # > 30 minutes
├── cyberpunk_anime/
├── darkwave_postpunk/
├── gaming_memes/
├── house_music/
├── neon_synthpop/
├── retro_anime/
├── retro_mashups/
└── ... (see full list below)

/mnt/media/                       <-- Catalogued originals (auto-populated)
/mnt/media_transcoded/            <-- 960x540 H.264 (auto-populated)
```

### Length Classification

| Category | Duration |
|----------|----------|
| `short/` | Under 5 minutes |
| `medium/` | 5-30 minutes |
| `long/` | Over 30 minutes |

## Downloading from YouTube

### Step 1: Get Video Info

First, check the video details to determine category and length:

```bash
~/.local/bin/yt-dlp --get-title --get-duration 'URL'
```

### Step 2: Download to Incoming

Download to the **incoming** folder — the pipeline handles the rest automatically:

```bash
~/.local/bin/yt-dlp \
    -f 'bestvideo+bestaudio/best' \
    -o '/mnt/incoming/<category>/<length>/%(title)s.%(ext)s' \
    'URL'
```

### Step 3: Wait (Automatic)

The `process-incoming.sh` cron job runs every 5 minutes and will:
1. Move the file to `/mnt/media/<category>/<length>/`
2. Transcode to 960x540 H.264 using NVENC
3. Push transcoded file to headroom.local
4. Regenerate playlists on headroom

**Check progress:** `tail -f /var/log/transcode/cron.log`

### Manual Pipeline (if needed)

To process immediately without waiting for cron:

```bash
~/bin/process-incoming.sh
```

## Download Examples

### Single Video

```bash
# 1. Check duration
~/.local/bin/yt-dlp --get-title --get-duration 'https://youtube.com/watch?v=XXXXX'
# Output: "Cool Video Title" / "1:47:38"  (long video)

# 2. Download to incoming
~/.local/bin/yt-dlp \
    -f 'bestvideo+bestaudio/best' \
    -o '/mnt/incoming/darkwave_postpunk/long/%(title)s.%(ext)s' \
    'https://youtube.com/watch?v=XXXXX'

# 3. Done! Pipeline handles the rest automatically.
```

### Playlist Download

```bash
~/.local/bin/yt-dlp \
    -f 'bestvideo+bestaudio/best' \
    --yes-playlist \
    -o '/mnt/incoming/<category>/%(duration>1800|long|%(duration>300|medium|short))s/%(title)s.%(ext)s' \
    'PLAYLIST_URL'
```

### Channel Download (with date filter)

```bash
~/.local/bin/yt-dlp \
    -f 'bestvideo+bestaudio/best' \
    --dateafter 20240101 \
    -o '/mnt/incoming/<category>/medium/%(title)s.%(ext)s' \
    'https://youtube.com/@channel'
```

## Quality Options

| Option | Format String | Typical Size (1hr) |
|--------|---------------|-------------------|
| Best available | `bestvideo+bestaudio/best` | 2-8 GB |
| 4K AV1 | `bestvideo[vcodec^=av01]+bestaudio` | ~2 GB |
| 1080p AV1 | `bestvideo[height<=1080][vcodec^=av01]+bestaudio` | ~500 MB |
| 1080p H.264 | `bestvideo[height<=1080][vcodec^=avc1]+bestaudio` | ~1.5 GB |
| 720p | `bestvideo[height<=720]+bestaudio` | ~300 MB |

**Recommendation:** Use "best available" — storage is cheap, and the transcoder normalizes everything anyway.

## Current Categories

| Category | Description |
|----------|-------------|
| `british_surreal_comedy` | Monty Python, IT Crowd, etc. |
| `comic_memes` | Comic/meme video content |
| `cyberpunk_anime` | Cyberpunk aesthetic anime, AMVs |
| `cyberpunk_memes` | Cyberpunk meme content |
| `darkwave_postpunk` | Cold wave, post-punk, darkwave, goth music |
| `fantasy_memes` | Fantasy-themed meme content |
| `gaelic_resistance` | Irish/Scottish cultural content |
| `gaming_memes` | Gaming culture memes |
| `house_music` | House music tracks and sets |
| `joke_commercials` | Parody/fake commercials |
| `joke_documentaries` | Parody documentaries |
| `neon_synthpop` | Synthwave, retrowave music |
| `philosophy_audio` | Philosophy lectures/discussions |
| `prelinger` | Prelinger Archive content |
| `retro_anime` | Classic anime clips |
| `retro_flash` | Classic Flash animations |
| `retro_mashups` | Mashups with retro aesthetic |
| `retro_sketch_comedy` | Classic sketch comedy |
| `surreal_talkshows` | Surreal/weird talk shows |
| `vintage_talkshows` | Classic talk show clips |

### Adding New Categories

If content doesn't fit existing categories:

1. Create directory in **incoming** on loki (media/transcoded dirs are auto-created):
   ```bash
   mkdir -p /mnt/incoming/new_category/{short,medium,long}
   ```

2. Create directory on headroom:
   ```bash
   ssh headroom.local "mkdir -p /mnt/media/new_category/{short,medium,long}"
   ```

3. Download content to `/mnt/incoming/new_category/<length>/`
4. Pipeline handles the rest automatically

## Troubleshooting

### "No supported JavaScript runtime" Warning

This warning appears but downloads usually still work. To eliminate it:

```bash
# Install deno
curl -fsSL https://deno.land/install.sh | sh
```

### 403/400 Errors

Update yt-dlp:
```bash
pipx upgrade yt-dlp
```

### Geo-restricted Content

Use a VPN or proxy:
```bash
~/.local/bin/yt-dlp --proxy socks5://127.0.0.1:1080 'URL'
```

### Age-restricted Content

May require cookies:
```bash
~/.local/bin/yt-dlp --cookies-from-browser firefox 'URL'
```

## Important Paths

| Path | Host | Purpose |
|------|------|---------|
| `/mnt/incoming/` | loki.local | **Drop downloads here** |
| `/mnt/media/` | loki.local | Catalogued originals (auto-populated) |
| `/mnt/media_transcoded/` | loki.local | Transcoded 960x540 H.264 (auto-populated) |
| `/mnt/media/` | headroom.local | Deployed transcoded media |
| `~/.local/bin/yt-dlp` | loki.local | yt-dlp binary |
| `~/bin/process-incoming.sh` | loki.local | Pipeline script (cron every 5 min) |
| `/var/log/transcode/` | loki.local | Pipeline logs |

## Pipeline Details

The `process-incoming.sh` script runs via cron every 5 minutes:

```
*/5 * * * * /home/nthmost/bin/process-incoming.sh >> /var/log/transcode/cron.log 2>&1
```

### What it does:

1. **Scans** `/mnt/incoming/` for new media files
2. **Moves** files to `/mnt/media/<category>/<length>/` (cataloguing)
3. **Transcodes** to 960x540 H.264 using NVENC GPU acceleration
4. **Pushes** transcoded files to `headroom.local:/mnt/media/`
5. **Regenerates** playlists on headroom

### Logs

- `/var/log/transcode/cron.log` - Main pipeline output
- `/var/log/transcode/transcode_errors.log` - FFmpeg errors
- `/var/log/transcode/rsync.log` - Transfer logs
