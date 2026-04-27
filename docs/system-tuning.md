# System Tuning

## loki.local Performance Tuning

### Applied Tunings

A systemd service applies these settings on boot:

**Service:** `/etc/systemd/system/loki-perf-tuning.service`

| Setting | Value | Purpose |
|---------|-------|---------|
| CPU Governor | `performance` | Prevents frequency scaling latency |
| GPU Min Freq | 700 MHz | Prevents GPU downclocking during encode |
| GPU Power Profile | `base` | Better sustained performance |
| Swappiness | 10 | Prefer keeping media buffers in RAM |

### Manual Verification

```bash
# Check CPU governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# Expected: performance

# Check GPU frequency
cat /sys/class/drm/card1/gt_min_freq_mhz
# Expected: 700

# Check GPU power profile
cat /sys/class/drm/card1/gt/gt0/slpc_power_profile
# Expected: [base]

# Check swappiness
cat /proc/sys/vm/swappiness
# Expected: 10
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

## VAAPI Hardware Encoding (loki.local)

loki.local uses Intel VAAPI for H.264 encoding of IA downloads:

```bash
# Check VAAPI support
vainfo

# Check available encoders
ffmpeg -encoders | grep vaapi
```

### Supported Profiles
- H.264 (Main, High, Constrained Baseline)
- HEVC (Main, Main10)
- VP9 (Profile 0-3)
- AV1 (Profile 0)

## NVENC Hardware Encoding (zikzak)

zikzak uses NVIDIA NVENC for the live streaming encode:

```bash
# Check GPU
nvidia-smi

# Check NVENC encoders
ffmpeg -encoders | grep nvenc
```

### NVENC Presets
- `p1` - Fastest, lowest quality
- `p4` - Balanced (used for transcoding)
- `p7` - Slowest, highest quality

## Resource Usage (zikzak)

### Expected Normal State
| Process | CPU |
|---------|-----|
| Liquidsoap (zikzak-liquidsoap) | ~30% |
| FFmpeg × 4 (NVENC encoders) | ~8% each |
| mpv (quadmux display) | ~70% |
| **Total** | ~130% |

If liquidsoap is significantly above 30%, see [Liquidsoap High CPU](troubleshooting.md#liquidsoap-high-cpu-80-100) in the troubleshooting guide.

### Services on zikzak

| Service | Purpose | Should be running? |
|---------|---------|-------------------|
| `zikzak-liquidsoap` | 4-channel video streams → Icecast | Yes |
| `quadmux-display` (user) | mpv quad-mux to HDMI display | Yes |
| `icecast2` | Local Icecast server | Yes |
| `zikzak-hls-ch{1-4}` | Local HLS segmenters | Yes |
| `mhbn-relay-ch{1-4}` | Relay to zephyr/nthmost.com | Yes |
| `maxheadroom` | **Removed** — old audio-only liquidsoap instance | No (deleted) |
| `maxheadroom-stream` | Old stream-to-icecast script | No (legacy) |

**Note:** `quadmux-display` is managed exclusively by the systemd user service at `~/.config/systemd/user/quadmux-display.service`. The XFCE autostart entry (`~/.config/autostart/quadmux-display.desktop`) was removed to prevent duplicate instances.

## Monitoring

```bash
# loki: real-time CPU/GPU usage
htop
sudo intel_gpu_top
cat /sys/class/drm/card1/gt_cur_freq_mhz

# zikzak: GPU + Liquidsoap
nvidia-smi
sudo tail -f /home/max/liquidsoap/channels.log
```
