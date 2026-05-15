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

**Current configuration:** Single GTX 1080 (8GB VRAM)

**Removed:** GTX 1060 6GB (was causing "Display engine timeout" errors and X server hangs)

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
