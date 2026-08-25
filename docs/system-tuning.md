# System Tuning

## loki.nthmost.net Performance Tuning

### Applied Tunings

A systemd service applies these settings on boot:

**Service:** `/etc/systemd/system/loki-perf-tuning.service`

| Setting | Value | Purpose |
|---------|-------|---------|
| CPU Governor | `performance` | Prevents frequency scaling latency |
| Swappiness | 10 | Prefer keeping media buffers in RAM |

**Note:** GPU power management for NVIDIA RTX 4080 is handled by the driver. NVIDIA GPUs boost automatically under load and don't require manual frequency tuning.

### Manual Verification

```bash
# Check CPU governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# Expected: performance

# Check swappiness
cat /proc/sys/vm/swappiness
# Expected: 10

# Check GPU state
nvidia-smi
```

### Service Management

```bash
# Check status
sudo systemctl status loki-perf-tuning

# Restart (reapply settings)
sudo systemctl restart loki-perf-tuning

# Disable (revert to defaults on next boot)
sudo systemctl disable loki-perf-tuning
```

## NVENC Hardware Encoding (loki.nthmost.net)

loki.nthmost.net uses NVIDIA NVENC (RTX 4080) for H.264 encoding:

```bash
# Check GPU
nvidia-smi

# Check NVENC encoders
ffmpeg -encoders | grep nvenc
```

### NVENC Presets
- `p1` - Fastest, lowest quality
- `p4` - Balanced (default for transcoding)
- `p7` - Slowest, highest quality

### User Permissions
The `max` user (which runs the intake service) must be in the `video` and `render` groups for GPU access:
```bash
sudo usermod -aG video,render max
```

## NVENC Hardware Encoding (zikzak)

zikzak uses NVIDIA NVENC (GTX 1080) for the live streaming encode:

```bash
# Check GPU
nvidia-smi

# Check NVENC encoders
ffmpeg -encoders | grep nvenc
```

### NVENC Presets
- `p1` - Fastest, lowest quality
- `p4` - Balanced (used for streaming)
- `p7` - Slowest, highest quality

### GPU Stability (2026-05-02)

> **Update (2026-05-14 rebuild):** The GTX 1060 was **reinstalled** and is now the
> dedicated kiosk-display GPU (drives HDMI-A-2 → quad splitter via direct DRM/KMS, no
> X), while the GTX 1080 still handles all 4 liquidsoap NVENC encoders. So zikzak
> currently runs **both** GPUs, not the single-1080 config described below. See
> [zikzak-architecture.md](zikzak-architecture.md) and troubleshooting.md → "GPU
> Hardware Issues" for the split rationale.

**Configuration as of 2026-05-02:** Single GTX 1080 (8GB VRAM)

**Removed (later reinstalled — see update above):** GTX 1060 6GB (was causing "Display engine timeout" errors and X server hangs)

**Performance baseline (GTX 1080 alone):**
- GPU utilization: ~11% (4x NVENC encoders + mpv NVDEC decode)
- VRAM usage: 1.9 GB / 8 GB (23%)
- Temperature: ~50°C
- Power draw: 41W / 180W TDP
- **Massive headroom available** — could support higher bitrate or better preset

**Why not GPU decode in liquidsoap?**
Attempted to enable NVDEC in liquidsoap via `settings.decoder.ffmpeg.hwaccel.set("cuda")` 
but it caused crashes on startup. Would require different liquidsoap version or major 
pipeline redesign. CPU decode is not a bottleneck (72% of one core), so freeing it up 
wouldn't meaningfully help. Reverted to CPU decode.

## Resource Usage (zikzak)

### Expected Normal State

| Process | CPU | Notes |
|---------|-----|-------|
| Liquidsoap (zikzak-liquidsoap) | ~68% | Manages ~44 directory-watched playlist sources simultaneously |
| FFmpeg × 4 (NVENC encoders) | ~8% each | GPU H.264 encode; CPU is audio mux overhead |
| mpv (quadmux display) | ~48% | NVDEC-copy decode + software lavfi composite |
| **Total** | ~148% of 8 threads | ~37% of physical capacity (i7-3770K, 4 cores) |
| **Load average** | ~1.8–2.2 | |

Note: on a freshly restarted liquidsoap, CPU spikes further while it scans all
directory sources and pre-buffers each one. This settles within ~2 minutes.
zikzak has 8 logical threads (4 cores + HT), so liquidsoap and mpv each running
at ~50–70% means they are each fully occupying one physical core — normal and sustainable.

### Memory Containment (zikzak-liquidsoap) — added 2026-08-25

**Why:** zikzak was periodically hard-freezing — powered with the CRT wall lit but
network-dead on every path, recoverable only by a physical power-cycle at NB. Root
cause (confirmed from `/var/log/atop` history, 2026-08-20): `zikzak-liquidsoap`
occasionally runs away from its normal ~500MB RSS to **~7.8GB** (50% of RAM) within
hours — a raw-frame buffer explosion (a stalled encoder or a pathological media file;
raw 960×720 video is ~25MB/s *per channel*). RAM + the 2GB swap fill, but the kernel
OOM-killer never fires (enough reclaimable page cache to stay under the threshold), so
instead of killing liquidsoap the box thrashes at load ~97 / `memfull 99%` and wedges.

**Fix:** a cgroup memory cap on the unit so a runaway kills *only* liquidsoap (which
`Restart=always` bounces in 5s) instead of taking down the whole machine.

| Setting | Value | Purpose |
|---------|-------|---------|
| `MemoryAccounting` | `yes` | Enable per-cgroup memory tracking |
| `MemoryHigh` | `2G` | Soft limit — kernel starts reclaiming pressure here |
| `MemoryMax` | `3G` | Hard limit — cgroup OOM-kill above this (~6× normal RSS) |

Configured in `ansible/roles/liquidsoap/templates/liquidsoap.service.j2`; values are
tunable via `liquidsoap_memory_high` / `liquidsoap_memory_max` in the role defaults.

```bash
# Verify effective limits
systemctl show zikzak-liquidsoap.service -p MemoryMax -p MemoryHigh -p MemoryAccounting
# MemoryMax=3221225472 (3.0G), MemoryHigh=2147483648 (2.0G), MemoryAccounting=yes

# Watch live cgroup memory pressure / current usage
systemctl status zikzak-liquidsoap.service | grep Memory
# Did the cap ever fire? (a breach = OOM kill scoped to the unit's cgroup)
journalctl -u zikzak-liquidsoap | grep -iE "memory|oom|killed"
```

**Not the cause (ruled out):** NVENC session contention — the 1080 runs all 4 encoders
at ~11% util. Do not offload encoders to the 1060 (reserved kiosk GPU). See
[troubleshooting.md](troubleshooting.md) → "Whole Box Frozen" for the incident detail.

### Services on zikzak

| Service | Purpose | Should be running? |
|---------|---------|-------------------|
| `zikzak-liquidsoap` | 4-channel video streams → Icecast | Yes |
| `quadmux-display` (user) | mpv quad-mux to HDMI display | Yes |
| `ch1-audio` | CH1 audio → 3.5mm jack (ALSA `plughw:0,0`) | Yes |
| `icecast2` | Local Icecast server | Yes |
| `zikzak-hls-ch{1-4}` | Local HLS segmenters | Yes |
| `mhbn-relay-ch{1-4}` | Relay to zephyr/nthmost.com | Yes |

**Note:** `quadmux-display` is managed exclusively by the systemd user service at `~/.config/systemd/user/quadmux-display.service`. The XFCE autostart entry (`~/.config/autostart/quadmux-display.desktop`) was removed to prevent duplicate instances.

## Monitoring

```bash
# loki: real-time CPU/GPU usage
htop
nvidia-smi
watch -n1 nvidia-smi

# zikzak: GPU + Liquidsoap
nvidia-smi
sudo tail -f /home/max/liquidsoap/channels.log

# Watch GPU utilization continuously
watch -n2 'nvidia-smi --query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits'
```
