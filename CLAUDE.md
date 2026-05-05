# CLAUDE.md — max-headroom

## Execution Permissions

Full bash/zsh access is granted in this project. No additional permission prompts required.

## Project Overview

Multi-channel HLS video streaming system for CRT quad-mux display at Noisebridge.
See README.md for architecture and workflow details.

**Hosts:** (see `docs/hardware-manifest.md` for full specs, roles, and network paths)
- `loki` (`loki.nthmost.net` / `text2gene.org`) — intake app, download, transcode
  - SSH: `ssh nthmost@text2gene.org` (or `ssh nthmost@loki.nthmost.net`)
  - Hardware: Ryzen 9 5950X, 64GB RAM, RTX 4080 (NVENC), home Sonic fiber
  - Intake app runs as user `max` at `/home/max/intake/`
  - Intake UI live at: `https://zikzak.nthmost.net/` (nginx on loki terminates SSL, proxies to Flask on port 8765)
  - Also accessible at: `https://headroom.nthmost.net/media/` (via Apache proxy on zephyr → WireGuard)
- `zikzak` (`10.100.0.5`, jump via `zephyr`) — streaming server at Noisebridge; media files, liquidsoap, Icecast
  - Hardware: i7-3770K, 16GB RAM, GTX 1080 (NVENC/NVDEC)
  - **Playback only** — do not run transcoding or heavy tasks here
- `headroom` (`10.100.0.4` / `headroom.local`) — spare resource at Noisebridge
  - Hardware: i5-14450HX, 32GB RAM, Intel UHD iGPU (VAAPI)
  - Same LAN as zikzak (<1ms). Use for batch processing that would be wasteful to route through loki.
- `zephyr` — VPS (`nthmost.com` / `149.28.77.210`); Icecast relay, HLS segmenters, Apache reverse proxy
  - **Network bridge only** — 2 vCPU, 4GB RAM, no GPU

**Note:** `zikzak.nthmost.net` resolves to loki (not zikzak). The Noisebridge machine
`zikzak` is only reachable via WireGuard (`ssh -J zephyr nthmost@10.100.0.5`) or
`zikzak.local` from the Noisebridge LAN.

## Server & DNS Information

For server infrastructure details and DNS registrar information, read:

```
~/projects/nthmost-systems/inventory.md
```

Key facts (verify against inventory.md for current state):
- Primary server IP: `149.28.77.210` (Debian Linux, Apache 2.4)
- DNS registrar: **Gandi** (nameservers: ns-*.gandi.net)
- Domains: `nthmost.com`, `nthmost.net` and subdomains
- Icecast streaming on port 8443 (no subdomain DNS yet)

The `~/projects/nthmost-systems/` repo also contains:
- `CLAUDE.md` — tracked external projects and commit/push policy
- `llm-infrastructure.md` — LLM/AI infrastructure notes
- `site-structure.md` — site layout reference
- `dotfiles/` — synced config files (deployed to all hosts via `sync.sh`)

## Monitoring with claude-monitor

The `~/projects/git/claude-monitor` project provides monitoring tooling for this system.

When investigating streaming issues, service health, or system performance, check
`~/projects/git/claude-monitor` for available monitoring scripts and dashboards.

## Services

**zikzak** (streaming):
```bash
sudo systemctl status zikzak-liquidsoap     # Liquidsoap 4-channel video
sudo systemctl status max-hls-ch{1,2,3,4}  # HLS segmenters
sudo systemctl status icecast2              # Local Icecast
sudo systemctl status ch1-audio             # CH1 audio → 3.5mm jack (ALSA plughw:0,0)
# Quadmux display (user service, runs as max):
sudo -u max XDG_RUNTIME_DIR=/run/user/1002 systemctl --user status quadmux-display
# Liquidsoap telnet: nc 127.0.0.1 1234
```

**loki** (intake):
```bash
sudo systemctl status intake                # Intake web app (port 8765, runs as max)
sudo systemctl status loki-pg-to-zikzak    # reverse autossh tunnel → exposes loki:5432 as zikzak:127.0.0.1:5435
```

## Database

PostgreSQL `mhbn` DB lives on **loki** at port 5432. This is the source of truth.

- Loki connects directly: `postgresql://mhbn:PASSWORD@127.0.0.1:5432/mhbn`
- Zikzak connects via reverse tunnel on port 5435: `postgresql://mhbn:PASSWORD@127.0.0.1:5435/mhbn`
- Connection string in `/home/max/.secrets/mhbn-db.env` on each host (different port)
- Schema changes: run on **loki** as postgres superuser — `sudo -u postgres psql mhbn`

## Key Scripts

| Script | Host | Purpose |
|--------|------|---------|
| `scripts/process-incoming.sh` | loki | Full pipeline: catalogue → transcode → push → regen playlists |
| `scripts/transcode-for-quadmux.sh` | loki | Transcode originals to 960x540 H.264 |
| `scripts/push-to-zikzak.sh` | loki | rsync transcoded files to zikzak |
| `scripts/regenerate-playlists.sh` | zikzak | Rebuild M3U playlists (run as nthmost, uses sudo for deploy) |
| `scripts/yt-queue.sh` | loki | Download queue helper |
