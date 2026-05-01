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

**Diagnosis — step 1:** Check the liquidsoap log for encoder crashes:
```bash
sudo grep -E "enc_ch|Error while streaming|reopen" /home/max/liquidsoap/channels.log | tail -20
```

**Diagnosis — step 2:** Check the mpv log for stream errors:
```bash
grep -E "\[e\]|\[w\]" /tmp/mpv-quadmux.log | tail -20
```

---

**Pattern A — encoder process crash (check log for specifics):**

Liquidsoap log shows:
```
[enc_ch4:3] Error while streaming: ..., will re-open in 5.00s
```

The `reopen_on_error` handler restarts the ffmpeg encoder after 5 seconds. During
that window the Icecast mount returns 404, which mpv sees as a stream EOF and freezes
the quadrant. The encoder should recover automatically — wait 10 seconds and watch
whether the quadrant unfreezes. If not, restart liquidsoap.

Note: the old `random_pick` off-by-one crash (`list.nth` exception) is no longer
possible — `channels.liq` was rewritten in 2026-05 to use liquidsoap's native
`random()` operator instead of a hand-rolled picker.

---

**Pattern B — Icecast 404 on reconnect (no crash, just a transient drop):**

mpv log shows:
```
[ffmpeg] http: Stream ends prematurely at XXXXXX, should be 18446744073709551615
[ffmpeg] http: Will reconnect at XXXXXX in 0 second(s)...
[ffmpeg] http: HTTP error 404 File Not Found
[lavf] EOF reached.
```

Without a crash in the liquidsoap log, this is a transient Icecast mount drop (e.g. icecast2 restart, network blip). The `--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=120` in `quadmux-display-mpv.sh` gives mpv 120 seconds to retry — enough to survive a full liquidsoap restart. If the 404 lasts longer than 120 seconds, the quadrant will freeze and the service needs a restart.

---

**Pattern C — no errors, freezes after ~20 minutes:**

Root cause: `--profile=low-latency` in the mpv command sets `stream-buffer-size=4k` and `fflags=+nobuffer`. Any PTS discontinuity hits the lavfi-complex compositor with no buffer to absorb it. Since the compositor requires all 4 inputs synchronized, one stall freezes the whole display.

**Fix:** Never use `--profile=low-latency` in `quadmux-display-mpv.sh`. The current script uses 100MiB demuxer buffer and 10s readahead instead.

---

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

Note: at ~48% CPU (nvdec-copy + lavfi composite), mpv may take several seconds to
respond to IPC queries under load. This is normal — the socket is for manual
diagnostics, not automated watchdog use.

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

### Garbled Now-Playing Text in Webapp (Mojibake)

**Symptom:** The channel description in the `headroom.nthmost.net` viewer shows garbled characters like `ð­ðµðµðµ ð ðð ð¢ð¥ð¬` instead of readable text. May also cause the video grid layout to blow out (one screen stretches to fill the entire viewport, pushing the other off-screen).

**Cause:** YouTube video titles often contain decorative Unicode characters (Mathematical Bold Sans-Serif, Fullwidth, etc. — 4-byte UTF-8 codepoints in the U+1D5xx range). When these are sent to Icecast as metadata, Icecast's ICY protocol defaults to Latin-1 encoding, causing each UTF-8 byte to be reinterpreted as a separate Latin-1 character.

**Fix applied (2026-05-01):**

1. **Liquidsoap metadata sanitization** (`channels.liq`): The `push_nowplaying` function now pipes titles through `python3 -c "unicodedata.normalize('NFKD', ...)"` to transliterate fancy Unicode to plain ASCII before sending to Icecast.

2. **Icecast charset config** (`/etc/icecast2/icecast.xml` on zephyr): Added `<charset>UTF-8</charset>` mount definitions for `/mhbn-ch1.ts` through `/mhbn-ch4.ts` so that any remaining non-ASCII characters (e.g. accented Latin) are handled correctly.

3. **Webapp grid fix** (`webapp/index.html`): Added `min-width: 0; overflow: hidden` to `.channel` grid items so that long/unbreakable metadata text can never blow out the CSS grid columns.

**If it recurs**, the most likely cause is a new source of non-NFKD-decomposable Unicode in filenames. Check the title on the local Icecast:
```bash
ssh zikzak "curl -s 'http://admin:noisebridge@localhost:8000/status-json.xsl'" | python3 -m json.tool
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

### Playlist Out of Sync (Reference Playlists Only)

Liquidsoap reads directly from media directories and does not use the M3U
playlists in `/home/max/playlists/` for programming. New files are picked up
automatically via inotify watching.

To refresh the reference playlists (for diagnostics, external players, etc.):
```bash
sudo -u max /home/max/bin/regenerate-playlists.sh
```

To force liquidsoap to re-scan its directory sources (e.g. after bulk moves):
```bash
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

### CH1 Audio Output (3.5mm Jack)

The `ch1-audio` systemd service plays CH1 audio through zikzak's analog output
(HDA Intel PCH, `plughw:0,0`) using mpv in audio-only mode. It connects to the
local Icecast stream at `http://localhost:8000/ch1.ts`.

**No audio from the 3.5mm jack:**
```bash
sudo systemctl status ch1-audio
# If failed, restart:
sudo systemctl restart ch1-audio
```

**Volume adjustment:**
```bash
# Check current levels
amixer -c 0
# Set master volume (0-100%)
amixer -c 0 set Master 80%
# Unmute if muted
amixer -c 0 set Master unmute
```

**ALSA device not found:** Ensure the `audio` group has access and the service
has `Group=audio`. Verify hardware with `sudo aplay -l`.

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

echo "=== CH1 Audio Output ==="
sudo systemctl status ch1-audio --no-pager -n 2

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
