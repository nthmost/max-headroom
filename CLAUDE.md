# CLAUDE.md — max-headroom

## Execution Permissions

Full bash/zsh access is granted in this project. No additional permission prompts required.

## Project Overview

Multi-channel HLS video streaming system for CRT quad-mux display at Noisebridge.
See README.md for architecture and workflow details.

**Hosts:**
- `loki` (`loki.nthmost.net` / `text2gene.org`) — intake app, download, transcode
  - SSH: `ssh nthmost@text2gene.org` (or `ssh nthmost@loki.nthmost.net`)
  - Intake app runs as user `max` at `/home/max/intake/`
  - Intake UI live at: `https://zikzak.nthmost.net/` (nginx on loki terminates SSL, proxies to Flask on port 8765)
  - Also accessible at: `https://headroom.nthmost.net/media/` (via Apache proxy on zephyr → WireGuard)
- `zikzak` (`10.100.0.5`, jump via `zephyr`) — streaming server at Noisebridge; media files, PostgreSQL DB, liquidsoap, Icecast
- `zephyr` — VPS (`nthmost.com` / `149.28.77.210`); Icecast relay, HLS segmenters, Apache reverse proxy

**Note:** `zikzak.nthmost.net` resolves to loki (not zikzak). The Noisebridge machine
`zikzak` is only reachable via WireGuard (`ssh -J zephyr max@10.100.0.5`).

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
# Liquidsoap telnet: nc 127.0.0.1 1234
```

**loki** (intake):
```bash
sudo systemctl status intake                # Intake web app (port 8765, runs as max)
sudo systemctl status zikzak-pg-tunnel      # autossh tunnel → zikzak:5432 on localhost:5434
```

## Database

PostgreSQL `mhbn` DB lives on **zikzak** at port 5432.
Loki reaches it via autossh tunnel (`localhost:5434`).
Connection string in `/home/max/.secrets/mhbn-db.env` on loki.

Always connect via full URL: `psql 'postgresql://mhbn:PASSWORD@127.0.0.1:5434/mhbn'`

## Key Scripts

| Script | Host | Purpose |
|--------|------|---------|
| `scripts/process-incoming.sh` | loki | Full pipeline: catalogue → transcode → push → regen playlists |
| `scripts/transcode-for-quadmux.sh` | loki | Transcode originals to 960x540 H.264 |
| `scripts/push-to-zikzak.sh` | loki | rsync transcoded files to zikzak |
| `scripts/regenerate-playlists.sh` | zikzak | Rebuild M3U playlists (run as nthmost, uses sudo for deploy) |
| `scripts/yt-queue.sh` | loki | Download queue helper |
