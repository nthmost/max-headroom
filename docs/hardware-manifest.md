# Hardware Manifest

Reference for all machines in the Max Headroom Broadcast Network, their roles,
connectivity, and separation of concerns.

Last verified: 2026-05-02

## Architecture Overview

```
                          INTERNET
                             │
                    ┌────────┴────────┐
                    │     zephyr      │  VPS (Vultr)
                    │  149.28.77.210  │  Icecast relay, HLS, Apache proxy
                    │   WG 10.100.0.1 │  WireGuard hub
                    └───┬─────────┬───┘
                        │         │
              WireGuard │         │ WireGuard
                        │         │
       ┌────────────────┘         └──────────────────────┐
       │  SONIC HOME CONNECTION          NOISEBRIDGE LAN │
       │                                   10.21.1.0/23  │
  ┌────┴─────┐                     ┌──────────┐   ┌──────┴──────┐
  │   loki   │                     │  zikzak  │   │  headroom   │
  │ 192.168. │                     │10.21.1.233   │ 10.21.1.136 │
  │  0.3     │                     │ WG .0.5  │   │  WG .0.4    │
  │          │    (via zephyr)     │          │◄──►│             │
  │ INTAKE   │ ──────────────────► │ PLAYBACK │   │ SPARE       │
  │ DOWNLOAD │   transcoded files  │ OUTPUT   │   │ RESOURCE    │
  │TRANSCODE │   to /mnt/dropbox/  │          │   │             │
  └──────────┘                     └──────────┘   └─────────────┘
```

## Network Paths

| From | To | Path | Latency | Bandwidth |
|------|----|------|---------|-----------|
| loki → zikzak | SSH jump via zephyr | ~30ms | ~30 MB/s |
| loki → zephyr | Direct WireGuard | ~15ms | ~50 MB/s |
| headroom → zikzak | Direct LAN (`zikzak.local`) | <1ms | ~100+ MB/s |
| headroom → zikzak | WireGuard (`10.100.0.5`) | <1ms | ~100+ MB/s |
| headroom → loki | SSH jump via zephyr | ~30ms | ~30 MB/s |
| headroom → zephyr | WireGuard | ~15ms | ~50 MB/s |

**Key insight:** headroom and zikzak are on the same LAN at Noisebridge.
Transfers between them are fast and free. Use `zikzak.local` or the LAN
IP `10.21.1.233` for direct access — do NOT route through zephyr.

## Machines

---

### loki — Intake & Transcode Server

**Role:** Downloads, transcoding, intake web app. The workhorse.

| Spec | Detail |
|------|--------|
| Hostname | `loki`, `loki.nthmost.net`, `text2gene.org` |
| Location | Home (Sonic fiber connection) |
| OS | Linux Mint 22.1 (Xia) |
| CPU | AMD Ryzen 9 5950X — 16 cores / 32 threads |
| RAM | 64 GB |
| GPU | NVIDIA RTX 4080 — 16 GB VRAM, NVENC/NVDEC |
| Storage | 1.8 TB NVMe (system, 389 GB free) + 1 TB SSD (`/mnt/media`, 798 GB free) |
| SSH | `ssh nthmost@text2gene.org` or `ssh nthmost@loki.nthmost.net` |
| WireGuard | Not currently a WG peer (reaches zikzak via zephyr jump) |

**Why loki does downloads:**
- YouTube cookies and IP history live here — moving downloads elsewhere
  means re-authenticating, risking throttling or blocks
- Sonic fiber has symmetric upload/download — good for pulling large videos
- yt-dlp's JS challenge solver (deno) is installed and working

**Why loki does transcoding:**
- RTX 4080 NVENC encodes 960x540 H.264 nearly instantly
- 16-core Ryzen handles software decode of AV1/VP9 while NVENC encodes
- Transcoding here means only clean, validated H.264 files ever leave loki

**Services:**
- `intake.service` — Flask web app (port 8765, runs as `max`)
- `zikzak-pg-tunnel` — autossh tunnel to zikzak PostgreSQL (localhost:5434)
- Cron: `process-incoming.sh` every 5 minutes

**Key directories:**
- `/mnt/incoming/` — raw downloads awaiting transcode
- `/mnt/media/` — original media catalogue (on 1TB SSD)
- `/mnt/media_transcoded/` — transcoded output, staged for push
- `/var/log/transcode/` — transcode and intake logs
- `/home/max/intake/` — intake app code

---

### zikzak — Media Output Server

**Role:** Streaming output only. Liquidsoap, Icecast, quadmux display.
Keep this machine's workload minimal and predictable.

| Spec | Detail |
|------|--------|
| Hostname | `zikzak` |
| Location | Noisebridge, San Francisco |
| OS | Linux Mint 22.3 (Zena), kernel 6.17 |
| CPU | Intel i7-3770K — 4 cores / 8 threads @ 3.5 GHz |
| RAM | 16 GB |
| GPU | NVIDIA GTX 1080 — 8 GB VRAM, NVENC/NVDEC |
| Storage | 1 TB SSD (938 GB, 711 GB free) |
| SSH | `ssh -J zephyr nthmost@10.100.0.5` or `ssh nthmost@zikzak.local` (from NB LAN) |
| WireGuard | `10.100.0.5` |
| LAN IP | `10.21.1.233` (wired), `10.21.1.157` (wifi) |
| Audio | ALC892 analog out (3.5mm jack) → amplifier/speakers |
| Video | GTX 1080 HDMI → quad splitter → 4x CRT displays |

**Separation of concern:** zikzak is the output stage. It should NOT be used
for transcoding, downloading, or any burst CPU/GPU work. The GTX 1080 runs:
- 4x NVENC encoders (liquidsoap channels) — ~5% encoder utilization
- mpv quadmux display (NVDEC decode + lavfi composite) — ~48% CPU
- Xorg — ~130 MB VRAM

That leaves headroom, but not much. Don't pile on.

**Services:**
- `zikzak-liquidsoap` — 4-channel video streaming engine
- `icecast2` — local Icecast server
- `max-hls-ch{1,2,3,4}` — HLS segmenters
- `quadmux-display` — mpv 2x2 compositor (user service, `max`)
- `ch1-audio` — CH1 audio to 3.5mm jack (ALSA `plughw:0,0`)
- `dropbox-watchdog` — validates and files incoming media from `/mnt/dropbox/`

**Key directories:**
- `/mnt/media/` — active media library (read by liquidsoap)
- `/mnt/dropbox/` — incoming transcoded files (watchdog picks up and files)
- `/mnt/dropbox/rejected/` — files that failed validation
- `/mnt/media_hold/` — 75 GB of Prelinger archives (transcoded, not in rotation)
- `/mnt/media_staging/` — 16 webm files awaiting transcode (being processed)
- `/home/max/liquidsoap/` — liquidsoap config and logs
- `/home/max/playlists/` — reference M3U playlists

**Database:** PostgreSQL `mhbn` on localhost:5432 (user `mhbn`).

---

### headroom — Spare Resource

**Role:** Overflow / auxiliary processing. Available for tasks that would be
wasteful to route back to loki or burdensome to run on zikzak.

| Spec | Detail |
|------|--------|
| Hostname | `headroom` |
| Location | Noisebridge, San Francisco (same LAN as zikzak) |
| OS | Linux Mint 22.3 (Zena) |
| CPU | Intel i5-14450HX — 10 cores / 16 threads |
| RAM | 32 GB |
| GPU | Intel UHD (Raptor Lake iGPU) — VAAPI encode/decode |
| Storage | 1 TB NVMe (938 GB, 725 GB free) |
| SSH | `ssh nthmost@headroom.local` (from NB LAN) or `ssh -J zephyr nthmost@10.100.0.4` |
| WireGuard | `10.100.0.4` |
| LAN IP | `10.21.1.136` |

**VAAPI encoders available:** h264_vaapi, hevc_vaapi, av1_vaapi, vp9_vaapi

**When to use headroom:**
- Batch re-transcoding files already on zikzak (pull from zikzak over LAN,
  transcode, push back — no internet hop needed)
- Overflow processing when loki is busy with downloads
- Testing new transcode settings without affecting production
- Any task where routing files back to loki via zephyr would be wasteful
  (headroom ↔ zikzak is <1ms LAN, vs 30ms+ through zephyr)

**When NOT to use headroom:**
- YouTube downloads (cookies/IP are on loki)
- Anything that needs NVENC (headroom has no NVIDIA GPU)
- Persistent services (headroom is not a production server)

**Services:**
- `cleanup-transcode-tmp.timer` — Daily cleanup of `/tmp/staging-*` and `/tmp/*transcode*` directories (runs at 4 AM)

**Automatic maintenance:** Old transcode temp directories (>1 day) and logs (>7 days) are automatically cleaned up.

---

### zephyr — VPS / WireGuard Hub

**Role:** Internet-facing relay. WireGuard hub, Icecast relay, HLS endpoint,
Apache reverse proxy. NOT a compute resource.

| Spec | Detail |
|------|--------|
| Hostname | `zephyr`, `nthmost.com`, `149.28.77.210` |
| Location | Vultr VPS (likely US West) |
| OS | Debian forky/sid |
| CPU | 2x AMD EPYC (Rome) vCPUs |
| RAM | 4 GB |
| Storage | 94 GB (78 GB used — **87% full, needs attention**) |
| WireGuard | `10.100.0.1` — hub for all WG peers |

**Services:**
- WireGuard — connects loki, zikzak, headroom
- Icecast relay — re-streams from zikzak to the internet
- HLS segmenters (`mhbn-hls-ch{1,2,3,4}`)
- Apache — reverse proxy for `headroom.nthmost.net`, `headroom.nthmost.com`
- nginx — SSL termination for various subdomains

**Do NOT run compute tasks on zephyr.** It has 2 vCPUs and 4 GB RAM.
It exists to bridge networks and serve HTTP.

---

## Separation of Concerns

```
┌─────────────┬───────────────────────────────────────────────┐
│   Machine   │  Responsibility                              │
├─────────────┼───────────────────────────────────────────────┤
│   loki      │  Download, transcode, intake web app         │
│   zikzak    │  Playback, streaming, display output         │
│   headroom  │  Spare: batch transcode, overflow, testing   │
│   zephyr    │  Network relay, public HTTP endpoints        │
└─────────────┴───────────────────────────────────────────────┘
```

**The pipeline flows one direction:**

```
loki (download + transcode) ──► zikzak (validate + play)
                                   ▲
headroom (batch transcode) ────────┘  (LAN, when needed)
```

**Rules of thumb:**

1. **All transcoding happens before files reach zikzak.** The dropbox watchdog
   on zikzak only accepts 960x540 H.264 MP4. Anything else gets rejected.

2. **zikzak should be idle except for playback.** If `nvidia-smi` shows GPU
   utilization above 15% outside of liquidsoap+mpv, something is wrong.

3. **Use headroom for Noisebridge-local tasks.** If files are already on
   zikzak and need re-processing, pull them to headroom over LAN (<1ms),
   process there, push back. Don't round-trip through loki via zephyr.

4. **Use loki for internet-facing tasks.** Downloads, cookie-gated scraping,
   anything that needs a residential IP or heavy GPU power.

5. **zephyr is a bridge, not a worker.** It has no GPU, minimal CPU/RAM.
   Its disk is 87% full. Only relay/proxy traffic should flow through it.

## SSH Quick Reference

```bash
# loki (from anywhere)
ssh nthmost@text2gene.org

# zikzak (from internet, via zephyr jump)
ssh -J zephyr nthmost@10.100.0.5

# zikzak (from Noisebridge LAN)
ssh nthmost@zikzak.local

# headroom (from Noisebridge LAN)
ssh nthmost@headroom.local

# headroom (from internet, via zephyr jump)
ssh -J zephyr nthmost@10.100.0.4

# zephyr
ssh nthmost@nthmost.com
```

## Admin Users

| Machine | Admin user | Service user | Notes |
|---------|-----------|-------------|-------|
| loki | `nthmost` | `max` (intake app) | `max` in `video`, `render` groups |
| zikzak | `nthmost` | `max` (liquidsoap, quadmux) | UID 1002 |
| headroom | `nthmost` | — | No services |
| zephyr | `nthmost` | — | Root via sudo |
