# Troubleshooting

## Common Issues

### Liquidsoap Won't Start

```bash
# On zikzak:
sudo systemctl status zikzak-liquidsoap
sudo journalctl -u zikzak-liquidsoap -n 50
tail -50 /home/max/liquidsoap/channels.log
```

**Common causes:**
- Icecast not running: `sudo systemctl start icecast2`
- Invalid playlist paths
- Missing media files

### Quadmux Channel(s) Frozen / Stuck on One Frame

**Symptom:** One or more quadrants of the quad-mux display on zikzak are frozen while other channels (and Icecast) are running fine.

**Diagnosis:** Check the mpv log:
```bash
tail -50 /tmp/mpv-quadmux.log
```

Look for either of these patterns:

**Pattern A — stream EOF at track boundary:**
```
[ffmpeg] http: Stream ends prematurely at XXXXXX, should be 18446744073709551615
[lavf] EOF reached.
```
This happens when Icecast briefly signals HTTP EOF as liquidsoap crosses a track boundary. Without reconnect options, mpv freezes the affected quadrant permanently.

**Fix:** The current `quadmux-display-mpv.sh` includes `--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=2`. If this is missing (e.g. after manual edits), add it back. Restart the service:
```bash
sudo -u max XDG_RUNTIME_DIR=/run/user/1002 systemctl --user restart quadmux-display
```

**Pattern B — no obvious error, channel just freezes after ~20 minutes:**

Root cause: `--profile=low-latency` was in the mpv command. That profile sets `stream-buffer-size=4k` and `fflags=+nobuffer`, leaving no room to absorb the PTS discontinuity at track boundaries. The lavfi-complex compositor requires all 4 inputs to stay synchronized — one frozen input freezes the whole display.

**Fix:** Never use `--profile=low-latency` in `quadmux-display-mpv.sh`. This is a passive display; it does not need low latency. The current script uses 100MiB demuxer buffer and 10s readahead instead.

**If channels are stuck right now**, restart the quadmux service:
```bash
sudo -u max XDG_RUNTIME_DIR=/run/user/1002 systemctl --user restart quadmux-display
# Verify window appears (~15 seconds after restart):
sudo -u max DISPLAY=:0 wmctrl -l
```

**Monitoring:** The IPC socket at `/tmp/mpv-quadmux.sock` allows live queries:
```bash
echo '{"command": ["get_property", "playback-time"]}' | socat - /tmp/mpv-quadmux.sock
```

### Video Stuttering/Dropping

1. Check CPU usage: `htop`
2. Check GPU usage: `nvidia-smi` (zikzak uses NVENC)
3. Check ffmpeg processes: `ps aux | grep ffmpeg`

If CPU is high, some media may not be transcoded. Check for non-MP4 files:
```bash
find /mnt/media -type f \( -name "*.ogv" -o -name "*.webm" -o -name "*.mkv" \)
```

### Liquidsoap High CPU (~80-100%)

**Symptom:** `zikzak-liquidsoap` pegged at 80%+ CPU; log shows repeated `We must catchup X seconds!`

**Cause 1: Memory bloat after long uptime.** Liquidsoap accumulates video frame buffers over days and starts swapping. Fix: restart the service.

```bash
sudo systemctl restart zikzak-liquidsoap
```

**Cause 2: Duplicate quadmux-display process.** If two `mpv` processes appear in `ps aux`, one was launched by XFCE autostart and one by the systemd user service — they stack fullscreen on the same display and both decode all 4 channels. Check:

```bash
ps aux | grep mpv | grep -v grep
```

If two are running, the autostart entry was not removed. Remove it and kill the duplicate:

```bash
rm /home/max/.config/autostart/quadmux-display.desktop
kill <PID of the older mpv>
```

The systemd user service (`~/.config/systemd/user/quadmux-display.service`) is the correct one to keep.

### Green Overlay on All Channels

**Symptom:** All 4 output channels show a green tint/overlay immediately after a liquidsoap restart.

**Cause:** The liquidsoap canvas height must be **720**, not 540. Even though source files are 960x540, the raw video pipe to ffmpeg NVENC requires the frame height to be a multiple of 16 for correct stride alignment. 720 satisfies this; 540 does not, causing green color plane corruption.

**Do not change** `settings.frame.video.height` in `channels.liq` away from 720. The letterboxing to 960x720 is intentional.

To recover, revert the setting and restart:

```bash
# On zikzak:
grep "frame.video.height" /home/max/liquidsoap/channels.liq
# Must show: settings.frame.video.height.set(720)
sudo systemctl restart zikzak-liquidsoap
```

### Transcode Failures

Check logs on loki:
```bash
cat /var/log/transcode/fail_*.log
```

**Common causes:**
- Corrupt source file
- Unsupported codec
- Disk full

Test individual file:
```bash
ffprobe -v error input.file
ffmpeg -v error -i input.file -f null -
```

### No Audio in Stream

Check if source has audio:
```bash
ffprobe -v error -show_streams input.mp4 | grep codec_type
```

If no audio, re-transcode with silent track:
```bash
ffmpeg -i input.mp4 \
    -f lavfi -i anullsrc=r=44100:cl=stereo \
    -c:v copy -map 0:v -map 1:a \
    -c:a aac -b:a 128k -shortest \
    output.mp4
```

### Playlist Out of Sync

Regenerate playlists on zikzak:
```bash
sudo -u max /home/max/bin/regenerate-playlists.sh
sudo systemctl restart zikzak-liquidsoap
```

### HLS Not Working

```bash
# On zikzak — local HLS segmenters
sudo systemctl status zikzak-hls-ch{1,2,3,4}
ls -la /var/www/hls/ch{1,2,3,4}/

# On zephyr — public HLS segmenters (feeds headroom.nthmost.com)
sudo systemctl status mhbn-hls-ch{1,2,3,4}
ls -la /var/www/hls/mhbn-ch{1,2,3,4}/

# Check nginx (on zephyr)
sudo systemctl status nginx
```

### Audio/Video Sync in Browser

The encoded stream normally has ~100-120ms of audio behind video — this is expected and imperceptible. If the browser player shows a larger delay (1-2 seconds):

1. **Try reloading the page** — hls.js can latch onto a bad sync offset at startup
2. **Check for the known TARGETDURATION spec violation** — see [issue #1](https://github.com/nthmost/max-headroom/issues/1). HLS playlists declare `TARGETDURATION:2` but segments are 2.4s (GOP 60 @ 25fps). Safari's native HLS may behave differently than hls.js.
3. **Check relay and segmenter health** — a relay restart can cause a PTS discontinuity that confuses some players

### Skip a Track / Check What's Playing

Use the Liquidsoap telnet interface on zikzak (127.0.0.1:1234):

```bash
# What's playing right now
echo -e "request.on_air\nquit" | nc -q1 127.0.0.1 1234

# Get metadata for a request ID (use IDs from request.on_air)
echo -e "request.metadata 42\nquit" | nc -q1 127.0.0.1 1234

# Skip current track on ch2
echo -e "ch2.skip\nquit" | nc -q1 127.0.0.1 1234

# Full command list
echo -e "help\nquit" | nc -q1 127.0.0.1 1234
```

## Diagnostics

### Full System Check (zikzak)

```bash
echo "=== Liquidsoap ==="
sudo systemctl status zikzak-liquidsoap --no-pager -n 3

echo "=== HLS segmenters ==="
sudo systemctl status zikzak-hls-ch{1,2,3,4} --no-pager -n 2

echo "=== Relays ==="
sudo systemctl status mhbn-relay-ch{1,2,3,4} --no-pager -n 2

echo "=== GPU ==="
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader

echo "=== Disk ==="
df -h /mnt/media

echo "=== Media Files ==="
find /mnt/media -name "*.mp4" | wc -l

echo "=== Quadmux Display ==="
sudo -u max XDG_RUNTIME_DIR=/run/user/1002 systemctl --user status quadmux-display --no-pager -n 2
sudo -u max DISPLAY=:0 wmctrl -l 2>/dev/null | grep -v "xfce\|Desktop" || echo "(no mpv window)"

echo "=== Recent Errors ==="
tail -20 /home/max/liquidsoap/channels.log | grep -i error
tail -5 /tmp/mpv-quadmux.log 2>/dev/null | grep -E "\[e\]|\[w\]" || true
```

### Network Stream Test

```bash
# Test Icecast stream (zikzak)
curl -I http://localhost:8000/ch2.ts

# Test relay arriving at nthmost.com
curl -I http://nthmost.com:8000/mhbn-ch2.ts

# Test HLS on zephyr
curl -I https://headroom.nthmost.com/hls/mhbn-ch2/index.m3u8

# Measure A/V offset in a live HLS stream (should be ~100-120ms)
ffprobe -v quiet -show_entries packet=codec_type,pts_time -of csv=p=0 \
  -read_intervals '%+4' /var/www/hls/mhbn-ch2/index.m3u8 | head -10
```

## Recovery

### Full Restart (zikzak)

```bash
sudo systemctl restart icecast2
sudo systemctl restart zikzak-liquidsoap
# HLS segmenters and relays auto-restart via PartOf/Requires
```

### Full Restart (zephyr)

```bash
sudo systemctl restart mhbn-hls-ch{1,2,3,4}
```

### Restore from Backup

If media is corrupted, re-add via the intake app or restore from a backup:
```bash
# On loki:
rsync -avh /mnt/media_transcoded/ zikzak:/mnt/media/

# On zikzak:
sudo -u max /home/max/bin/regenerate-playlists.sh
sudo systemctl restart zikzak-liquidsoap
```
