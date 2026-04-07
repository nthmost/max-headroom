# Troubleshooting

## Common Issues

### Liquidsoap Won't Start

```bash
# Check status
sudo systemctl status max-liquidsoap

# Check logs
sudo journalctl -u max-liquidsoap -n 50

# Check liquidsoap log
sudo tail -50 /home/max/liquidsoap/channels.log
```

**Common causes:**
- Icecast not running: `sudo systemctl start icecast2`
- Invalid playlist paths
- Missing media files

### Video Stuttering/Dropping

1. Check CPU usage: `htop`
2. Check GPU usage: `cat /sys/class/drm/card1/gt_cur_freq_mhz`
3. Verify tuning service: `sudo systemctl status headroom-perf-tuning`

If CPU is high, some media may not be transcoded. Check for non-MP4 files:
```bash
find /mnt/media -type f \( -name "*.ogv" -o -name "*.webm" -o -name "*.mkv" \)
```

### Transcode Failures

Check logs on loki.local:
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

Regenerate playlists:
```bash
sudo -u max /home/max/bin/regenerate-playlists.sh
sudo systemctl restart max-liquidsoap
```

### HLS Not Working

```bash
# Check HLS services
sudo systemctl status max-hls-ch1
sudo systemctl status max-hls-ch2

# Check output directory
ls -la /var/www/hls/ch1/
ls -la /var/www/hls/ch2/

# Check nginx
sudo systemctl status nginx
```

## Diagnostics

### Full System Check

```bash
# On headroom.local:

echo "=== Services ==="
sudo systemctl status max-liquidsoap --no-pager
sudo systemctl status max-hls-ch1 --no-pager
sudo systemctl status max-hls-ch2 --no-pager

echo "=== CPU/Memory ==="
top -bn1 | head -15

echo "=== GPU ==="
cat /sys/class/drm/card1/gt_cur_freq_mhz

echo "=== Disk ==="
df -h /mnt/media

echo "=== Media Files ==="
find /mnt/media -name "*.mp4" | wc -l

echo "=== Recent Errors ==="
sudo tail -20 /home/max/liquidsoap/channels.log | grep -i error
```

### Network Stream Test

```bash
# Test Icecast stream
curl -I http://localhost:8000/ch1.ts

# Test HLS
curl -I http://localhost/hls/ch1/index.m3u8
```

## Recovery

### Full Restart

```bash
sudo systemctl restart icecast2
sudo systemctl restart max-liquidsoap
sudo systemctl restart max-hls-ch1
sudo systemctl restart max-hls-ch2
```

### Restore from Backup

If media is corrupted, restore from loki:
```bash
# On loki.local:
rsync -avh /mnt/media_originals_backup/ headroom.local:/mnt/media/

# On headroom.local:
sudo -u max /home/max/bin/regenerate-playlists.sh
sudo systemctl restart max-liquidsoap
```
