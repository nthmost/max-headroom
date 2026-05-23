# Hardware Manifest

Reference for all machines in the Max Headroom Broadcast Network, their roles,
connectivity, and separation of concerns.

Last verified: 2026-05-20

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
       ┌────────────────┘         └──────────────────┐
       │  SONIC HOME CONNECTION      NOISEBRIDGE LAN │
       │                               10.21.1.0/23  │
  ┌────┴─────┐                     ┌──────────┐
  │   loki   │                     │  zikzak  │
  │ WG .0.6  │                     │ WG .0.5  │
  │          │    (via zephyr)     │          │
  │ INTAKE   │ ──────────────────► │ PLAYBACK │
  │ DOWNLOAD │   transcoded files  │ OUTPUT   │
  │TRANSCODE │   to /mnt/dropbox/  │          │
  └──────────┘                     └──────────┘
```

**Note:** "headroom" is the project/viewer brand (`headroom.nthmost.net`), not a
host. The viewer is static HTML/JS served by Apache on zephyr, with the intake
API proxied from loki via WireGuard.

## Network Paths

| From | To | Path | Latency | Bandwidth |
|------|----|------|---------|-----------|
| loki → zikzak | SSH jump via zephyr | ~30ms | ~30 MB/s |
| loki → zephyr | Direct WireGuard | ~15ms | ~50 MB/s |
| zephyr → loki | WireGuard (10.100.0.6) | ~15ms | ~50 MB/s |

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
| WireGuard | `10.100.0.6` — peer of zephyr |

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
- `intake.service` — Flask web app (port 8765, runs as `max`, binds `0.0.0.0`)
- `loki-pg-to-zikzak` — autossh reverse tunnel exposing loki:5432 as zikzak:127.0.0.1:5435
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
| GPU 0 | NVIDIA GTX 1080 — 8 GB VRAM (NVENC encode + admin desktop) |
| GPU 1 | NVIDIA GTX 1060 6GB — 6 GB VRAM (NVDEC decode + quadmux display) |
| Storage | 1 TB SSD (rebuilt May 2026) |
| SSH | `ssh -J zephyr nthmost@10.100.0.5` or `ssh nthmost@zikzak.local` (from NB LAN) |
| WireGuard | `10.100.0.5` |
| LAN IP | `10.21.0.7` (wired, static — set 2026-05-22) |
| Audio | ALC892 analog out (3.5mm jack) → amplifier/speakers |
| Video | GTX 1060 DRM/KMS → quad splitter → 4x CRT displays |

**Dual GPU architecture (May 2026 rebuild):**
- **GTX 1080 (GPU 0):** liquidsoap 4x NVENC encode + admin desktop (Xorg)
- **GTX 1060 (GPU 1):** quadmux kiosk with NVDEC decode + direct DRM output

**Separation of concern:** zikzak is the output stage. It should NOT be used
for transcoding, downloading, or any burst CPU/GPU work. The dual GPUs run:
- GTX 1080: 4x NVENC encoders (liquidsoap) — ~5% encoder utilization + Xorg
- GTX 1060: mpv quadmux display (NVDEC decode) — dedicated to CRT output

The GTX 1060 is dedicated solely to the quad CRT display, keeping video decode
off the primary card and ensuring smooth 4-channel output.

**Services:**
- `zikzak-liquidsoap` — 4-channel video streaming engine
- `icecast2` — local Icecast server
- `zikzak-audio` — MQTT-controlled audio output to 3.5mm jack (ALSA `plughw:0,0`)
- `quadmux-display` — mpv 2x2 compositor (user service, `max`)
- `dropbox-watchdog` — validates and files incoming media from `/mnt/dropbox/`
- `loki-pg-tunnel` — autossh tunnel; exposes loki's postgres as `127.0.0.1:5435`
- `mhbn-relay-ch{1,2,3,4}` — ffmpeg relay: zikzak icecast → zephyr icecast

**Key directories:**
- `/mnt/media/` — active media library (read by liquidsoap)
- `/mnt/dropbox/` — incoming transcoded files (watchdog picks up and files)
- `/mnt/dropbox/rejected/` — files that failed validation
- `/home/max/liquidsoap/` — liquidsoap config and logs
- `/home/max/playlists/` — reference M3U playlists

**Database:** PostgreSQL `mhbn` lives on **loki**. Zikzak accesses it via
`loki-pg-tunnel` at `127.0.0.1:5435` (tunneled through zephyr to loki:5432).

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
- WireGuard — connects loki (`10.100.0.6`), zikzak (`10.100.0.5`), and other peers
- Icecast relay — re-streams from zikzak to the internet
- HLS segmenters (`mhbn-hls-ch{1,2,3,4}`)
- Apache — serves `headroom.nthmost.net` (viewer + HLS + intake proxy → loki)
- nginx — SSL termination for `zikzak.nthmost.net` → loki intake app

**Do NOT run compute tasks on zephyr.** It has 2 vCPUs and 4 GB RAM.
It exists to bridge networks and serve HTTP.

---

## Separation of Concerns

```
┌─────────────┬───────────────────────────────────────────────┐
│   Machine   │  Responsibility                              │
├─────────────┼───────────────────────────────────────────────┤
│   loki      │  Download, transcode, intake web app, DB     │
│   zikzak    │  Playback, streaming, display output         │
│   zephyr    │  Network relay, public HTTP endpoints        │
└─────────────┴───────────────────────────────────────────────┘
```

**The pipeline flows one direction:**

```
loki (download + transcode) ──► zikzak (validate + play) ──► zephyr (relay to internet)
```

**Rules of thumb:**

1. **All transcoding happens before files reach zikzak.** The dropbox watchdog
   on zikzak only accepts 960x540 H.264 MP4. Anything else gets rejected.

2. **zikzak should be idle except for playback.** If `nvidia-smi` shows GPU
   utilization above 15% outside of liquidsoap+mpv, something is wrong.

3. **Use loki for all compute tasks.** Downloads, transcoding, cookie-gated
   scraping, anything that needs a residential IP or heavy GPU power.

4. **zephyr is a bridge, not a worker.** It has no GPU, minimal CPU/RAM.
   Its disk is 87% full. Only relay/proxy traffic should flow through it.

## SSH Quick Reference

```bash
# loki (from anywhere)
ssh nthmost@text2gene.org

# zikzak (from internet, via zephyr jump)
ssh -J zephyr nthmost@10.100.0.5

# zikzak (from Noisebridge LAN)
ssh nthmost@zikzak.local

# zephyr
ssh nthmost@nthmost.com
```

## Admin Users

| Machine | Admin user | Service user | Notes |
|---------|-----------|-------------|-------|
| loki | `nthmost` | `max` (intake app) | `max` in `video`, `render` groups |
| zikzak | `nthmost` | `max` (liquidsoap, quadmux) | UID 1002 |
| zephyr | `nthmost` | — | Root via sudo |
