# Cursed TV Station

A liquidsoap-based looping TV station for CRT display arrays and/or Icecast streaming. Plays public domain found footage, VHS rips, degraded video, dead air, and station idents in an endless randomized rotation.

## Requirements

- Linux (tested on Ubuntu 22.04+)
- `liquidsoap` >= 2.2 ([install guide](https://www.liquidsoap.info/doc-2.2.0/install.html))
- `ffmpeg` (with libx264, drawtext/freetype)
- `python3 -m pip install internetarchive` (for archive harvesting)
- `yt-dlp` (for YouTube harvesting)

Install liquidsoap on Debian/Ubuntu:
```bash
sudo apt install liquidsoap
# or for latest via opam:
opam install liquidsoap
```

## Quick Start

### 1. Generate dead air and idents
```bash
./scripts/make_dead_air.sh
./scripts/make_ident.sh
```

### 2. Harvest some content
```bash
# From Internet Archive
./scripts/harvest_archive.sh "public access television" 10
./scripts/harvest_archive.sh "vhs rip" 5
./scripts/harvest_archive.sh "educational film 1980" 5

# From YouTube
./scripts/harvest_youtube.sh "ytsearch5:VHS compilation"
./scripts/harvest_youtube.sh "ytsearch3:old commercials compilation" content/glitch
```

### 3. Check your library
```bash
./scripts/build_playlist.sh
```

### 4. Edit config
```bash
nano liquidsoap/config.liq
# - set content_dir to absolute path of your content/ folder
# - set enable_sdl = true for local display, or enable_icecast for streaming
```

### 5. Run
```bash
cd liquidsoap
liquidsoap station.liq
```

## Content Library Structure

```
content/
  main/       ← Internet Archive finds, long-form found footage
  glitch/     ← FFmpeg-degraded clips, analog art, glitch content
  dead_air/   ← Black screen, color bars, snow static (generated)
  idents/     ← Station ID bumpers, 3-5 seconds (generated)
  bumpers/    ← Transitions, interstitials (optional)
```

## Content Plan

### 1. Internet Archive (primary source)

The goldmine. Long runtimes, analog artifacts already baked in, weird pacing.

Use `harvest_archive.sh` with the search clusters below. Everything goes into `content/main/`.

---

**Institutional / training media** ← top tier

Authoritative tone delivering outdated content. Slow pacing. Analog artifacts. Feels like the system explaining itself incorrectly.

```
educational film 1970
training film 1980
industrial training video
corporate training VHS
instructional film
```

---

**Public access / local broadcast**

Low-budget sincerity, unpredictable structure, strange personalities. Feels like reality leaking through infrastructure.

```
public access television
community television 1990
local news broadcast VHS
access channel program
```

---

**VHS / tape culture**

Tracking errors, color bleed, time distortion. Feels like memory, but unstable.

```
VHS recording
home video VHS 1980
VHS compilation
tape transfer
```

---

**Commercials** ← surprisingly powerful

Short segments (great for idents and interstitials), high-energy contrast, weird cultural assumptions baked in. Feels like ritualized persuasion fragments.

```
commercial compilation 1980
TV ads 1990
local commercials
public service announcement PSA
```

---

**Technical / scientific media**

Visual abstractions, diagrams with narration, early CG weirdness. Feels like machines trying to describe themselves.

```
NASA educational film
computer training 1980
early computer graphics demo
signal processing demonstration
```

---

**New age / fringe / esoteric**

Slow pacing, uncanny tone, often already glitch-adjacent before you touch it. Feels like someone trying to tune the signal.

```
new age VHS
meditation video 1980
self improvement tape
hypnosis session recording
```

---

**Fitness / instruction**

Repetitive motion, bright colors, strong visual rhythm. Surprisingly hypnotic in a rotation context. Feels like bodies syncing to broadcast.

```
aerobics 1980
exercise VHS
workout tape
dance instruction video
```

---

**Government / civic media**

Authoritative but slightly off. Often unintentionally eerie. Feels like systems maintaining themselves.

```
public information film
government training video
civil defense film
safety training VHS
```

---

**High-signal weird pulls**

Less obvious but often gold. These frequently produce accidental glitch, feedback loops, and broken structure — use in `glitch/` or run through `degrade.sh` first.

```
access television call in
video feedback experiment
broadcast failure
signal interference
UHF television recording
```

### 2. YouTube harvests (process before use)

Use `harvest_youtube.sh`, then run through `degrade.sh` before moving to `content/glitch/`.

Good search targets:

```
VHS compilation
analog glitch art
CRT footage
old commercials compilation
broadcast failure
public access clip
```

### 3. Locally generated glitch content

You don't need to find glitch content — you can manufacture it infinitely.

Run anything from `main/` through `degrade.sh` at intensity 3-5:

```bash
./scripts/degrade.sh content/main/some_film.mp4 content/glitch/some_film_destroyed.mp4 4
```

Useful variants to generate deliberately:
- Drop frames (intensity 3+)
- Color channel shifts
- Multi-pass MPEG2 re-encodes (intensity 4-5)
- Crop accidents

### 4. Dead air (generated)

Underrated and important — gives the station breathing room and sells the "real channel" feel.

```bash
./scripts/make_dead_air.sh
```

Generates: black with noise, SMPTE color bars, snowstorm static, blue screen.

### 5. Station idents (generated)

2–5 second clips that make it feel like a real station. Cheap to make, high impact.

```bash
./scripts/make_ident.sh
```

Edit `STATION_NAME` and `TAGLINES` in the script to customize. Generate 10+ variants — slight timing differences make them feel organic.

## Outputs

### Local HDMI Display

Set `enable_sdl = true` in `config.liq`. Requires an active X session.

For two HDMI outputs, run two mpv instances pointed at the Icecast stream:
```bash
DISPLAY=:0 mpv --fullscreen --fs-screen=0 http://localhost:8000/cursed &
DISPLAY=:0 mpv --fullscreen --fs-screen=1 http://localhost:8000/cursed &
```

### Icecast2

Set `enable_icecast = true` and configure `icecast_*` values in `config.liq`.

Install Icecast2:
```bash
sudo apt install icecast2
sudo systemctl start icecast2
```

Connect from any display machine:
```bash
mpv --fullscreen http://station-host:8000/cursed
vlc http://station-host:8000/cursed
```

## Scripts

| Script | Purpose |
|--------|---------|
| `harvest_archive.sh` | Download from Internet Archive by search query |
| `harvest_youtube.sh` | Download via yt-dlp (YouTube and others) |
| `degrade.sh` | Apply VHS degradation (intensity 1-5) |
| `make_dead_air.sh` | Generate black/snow/bars dead air clips |
| `make_ident.sh` | Generate station ident bumpers |
| `build_playlist.sh` | Report content library stats |

## Degradation

Run harvested content through the degradation pipeline before adding to `glitch/`:
```bash
# Moderate degradation (intensity 2, default)
./scripts/degrade.sh content/main/some_video.mp4 content/glitch/some_video_vhs.mp4

# Absolutely destroyed (intensity 5)
./scripts/degrade.sh content/main/some_video.mp4 content/glitch/some_video_cursed.mp4 5
```

## Target Hardware

Initially developed for a KAMRUI mini PC (Intel Core Ultra 9 14450HX) driving 2 HDMI outputs split across a bank of CRTs via distribution amplifiers and HDMI→composite converters.
