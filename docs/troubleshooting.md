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

### Video Stuttering/Dropping

1. Check CPU usage: `htop`
2. Check GPU usage: `nvidia-smi` (zikzak uses NVENC)
3. Check ffmpeg processes: `ps aux | grep ffmpeg`

If CPU is high, some media may not be transcoded. Check for non-MP4 files:
```bash
find /mnt/media -type f \( -name "*.ogv" -o -name "*.webm" -o -name "*.mkv" \)
```

### Transcode Failures

Check logs on headroom.local:
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

echo "=== Recent Errors ==="
tail -20 /home/max/liquidsoap/channels.log | grep -i error
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

If media is corrupted, restore from headroom.local:
```bash
# On headroom.local:
rsync -avh /mnt/media_transcoded/ zikzak:/mnt/media/

# On zikzak:
sudo -u max /home/max/bin/regenerate-playlists.sh
sudo systemctl restart zikzak-liquidsoap
```
