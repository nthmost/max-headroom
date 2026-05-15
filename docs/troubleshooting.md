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

### GPU Hardware Issues (zikzak)

**Symptom:** X server crashes with "Display engine timeout" errors, system becomes unresponsive, or GPU randomly disappears from `nvidia-smi`.

**Diagnosis:** Check dmesg for GPU errors:
```bash
sudo dmesg | grep -i "nvidia\|gpu\|drm" | tail -20
```

**Fix (2026-05-02):** The GTX 1060 6GB was physically removed due to repeated display engine timeout errors. The system now runs stably on a single GTX 1080 (8GB VRAM) with massive headroom:
- GPU utilization: ~11% (4x NVENC encoders + mpv NVDEC decode)
- VRAM usage: 1.9 GB / 8 GB (23%)
- Temperature: ~50°C
- Power draw: 41W / 180W TDP

**Why not GPU decode in liquidsoap?** Attempted to enable NVDEC via `settings.decoder.ffmpeg.hwaccel.set("cuda")` in `channels.liq`, but liquidsoap crashed on startup. Would require a different liquidsoap version or major pipeline redesign. CPU decode is not a bottleneck (72% of one core), so there's no meaningful benefit to pursuing this further.

**Update (2026-05-14 rebuild):** The original system drive failed and zikzak was rebuilt from scratch on Linux Mint 22.3. The GTX 1060 was reinstalled alongside the GTX 1080 and is now the **dedicated kiosk display GPU** — it drives HDMI-A-2 to the quad splitter via direct DRM/KMS (no X), while the GTX 1080 handles all 4 liquidsoap NVENC encoders and the optional admin desktop. See [Zikzak Architecture](zikzak-architecture.md) for the split rationale.

The "display engine timeout" errors that caused the May 2 removal have not recurred so far on the new install (different kernel, different driver path: kiosk uses direct DRM rather than Xorg). **Watch `dmesg | grep -i nvidia` if the kiosk freezes or `mpv` repeatedly restarts** — if the same class of error returns we'll need to fall back to single-GPU operation and rework the kiosk to share the 1080.

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

### Disk Space Issues

**Check disk usage:**
```bash
df -h /mnt/media
du -sh /tmp/*transcode* /tmp/staging-* 2>/dev/null
```

**Common causes:**
- Old transcode temp directories on headroom or zikzak (can be 20-30GB each)
- Media files not cleaned up after failed transcodes
- Large incoming files not processed

**Cleanup on headroom:**
Temp directories are automatically cleaned daily at 4 AM by `cleanup-transcode-tmp.timer`:
- Removes `/tmp/staging-*` and `/tmp/*transcode*` directories older than 1 day
- Removes `*.log` files older than 7 days

To manually clean up now:
```bash
# On headroom:
rm -rf /tmp/staging-* /tmp/*transcode*

# On loki:
rm -rf /tmp/*transcode*
find /mnt/incoming -type f -mtime +7 -delete  # Old downloads
```

**Check systemd timer status (headroom):**
```bash
sudo systemctl status cleanup-transcode-tmp.timer
sudo systemctl list-timers cleanup-transcode-tmp.timer
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

**How it works:**
- Systemd unit: `/etc/systemd/system/ch1-audio.service` (system service, enabled)
- Runs as user `nthmost`, group `audio`
- mpv with `--no-video --ao=alsa --audio-device=alsa/plughw:0,0 --volume=100`
- Source: `http://localhost:8000/ch1.ts` (local Icecast, CH1 transport stream)
- Reconnects automatically on stream drops (up to 30s retry)
- Waits 15 seconds before starting (`ExecStartPre=/bin/sleep 15`) to let
  Icecast and liquidsoap come up first
- **Automatically restarts when liquidsoap restarts** (`PartOf=zikzak-liquidsoap.service`)

**ALSA mixer chain (all must be unmuted for audio output):**

The ALC892 codec on the Intel PCH has multiple mixer stages in series.
All three of these must be unmuted and at nonzero volume:

| Control   | Purpose                        | Default after reboot |
|-----------|--------------------------------|----------------------|
| `Master`  | Global hardware master volume  | Usually on           |
| `PCM`     | Software PCM mix level         | Usually on           |
| `Front`   | Front (3.5mm line-out) switch  | **Often OFF**        |

The `Front` channel controls the physical 3.5mm analog output and **resets to
muted on reboot**. This is the most common cause of "service running but no
sound."

**Quick fix — unmute everything:**
```bash
amixer -c 0 sset Master unmute
amixer -c 0 sset Front unmute
amixer -c 0 sset Master 64%
amixer -c 0 sset Front 100%
amixer -c 0 sset PCM 98%
```

**Persist mixer state across reboots:**
```bash
# Save current ALSA state
sudo alsactl store
# Verify it will restore on boot
sudo systemctl enable alsa-restore
```

**No audio from the 3.5mm jack — checklist:**
1. Check the service is running:
   ```bash
   sudo systemctl status ch1-audio
   # If failed, restart:
   sudo systemctl restart ch1-audio
   ```
2. Check ALSA mixer — especially `Front`:
   ```bash
   amixer -c 0 sget Front
   # If [off], unmute:
   amixer -c 0 sset Front unmute
   ```
3. Check the physical 3.5mm cable is in the **green** jack on zikzak's
   rear I/O panel (ALC892 line-out, not the orange/black surround jacks)
4. Verify the audio hardware is detected:
   ```bash
   aplay -l | grep PCH
   ```

**ALSA device not found:** Ensure the `audio` group has access and the service
has `Group=audio`. Verify hardware with `sudo aplay -l`.

### Audio/Video Sync in Browser (1-2 Second Audio Delay)

**Investigated and fixed: 2026-05-07.** Root causes, analysis method, and applied fixes documented below.

#### Normal baseline

The encoded MPEG-TS stream has ~100-120ms of audio PTS ahead of video PTS per
HLS segment. This is expected and imperceptible — it comes from H.264 B-frame
reordering: NVENC outputs B-frames with PTS values that are slightly higher than
the first decodable frame, so each segment starts with a small audio pre-roll.

```bash
# Measure A/V offset in a live HLS segment on zephyr (should be 80-130ms):
seg=$(ls -t /var/www/hls/mhbn-ch1/*.ts | head -2 | tail -1)
ffprobe -v quiet -print_format json -show_packets -read_intervals '%+#20' $seg \
  | python3 -c "
import json,sys; d=json.load(sys.stdin)
v=[p for p in d['packets'] if p['codec_type']=='video']
a=[p for p in d['packets'] if p['codec_type']=='audio']
diff = float(v[0].get('pts_time',0)) - float(a[0].get('pts_time',0))
print(f'A/V offset: {diff*1000:.1f}ms (audio leads video; normal if 80-130ms)')
"
```

#### What was causing the 1-2 second delay

Three compounding issues were found and fixed (commit `c7bb122`):

**1. GOP size mismatch (primary cause)**

The NVENC encoder used `-g 60` (60 frames = **2.4s** GOP at 25fps), but the HLS
segmenter targets `-hls_time 2`. The segmenter must cut at keyframe boundaries,
so every segment was exactly 2.4s. However, the playlist declared:

```
#EXT-X-TARGETDURATION:2
#EXTINF:2.400000,
```

This violates the intent of the HLS spec (EXTINF should be ≤ TARGETDURATION
when rounded, which passes numerically but is 20% longer than declared). Some
hls.js live-sync calculations use TARGETDURATION × liveSyncDurationCount to
estimate the live edge; a 20% mismatch means the player's estimated latency
is 20% wrong, and its catchup/nudge logic fires incorrectly.

**Fix:** Changed `-g 60` → `-g 50` (50 frames = exactly **2.0s** GOP at 25fps).
Segments now report `2.000000` and match `TARGETDURATION:2` exactly.

**2. aresample correction rate too low (secondary cause)**

The ffmpeg encoding chain included `-af "aresample=async=1"`. The `async`
parameter is in **samples per second** of correction capacity — `async=1` means
correcting 1/44100 second ≈ 0.023ms/sec of drift. In practice this does nothing.

The actual measured audio/video clock drift is ~1.55ms per 2-second segment
(~0.78ms/sec), driven by the non-integer ratio between audio frames (1024
samples @ 44100Hz = 23.22ms each) and video frames (40ms each). `async=1`
could never catch up to this drift.

**Fix:** Changed to `aresample=async=1000`, which corrects up to 22.7ms/sec —
well above the measured drift rate. After the fix, the A/V offset oscillates in
a ±10ms band around the B-frame baseline rather than slowly accumulating.

**3. hls.js live sync settings too aggressive (browser-side)**

The webapp configured `liveSyncDurationCount: 3` (stay 3 segments = 7.2s behind
the live edge). With the TARGETDURATION mismatch above, this window was wider
than intended, giving audio and video SourceBuffers more time to diverge. No
`nudge` or `maxBufferHole` settings were configured, so the player had no
self-correction mechanism.

**Fix:** Updated `webapp/index.html` hls.js config:
```js
liveSyncDurationCount: 2,       // 4s behind live edge (was 7.2s)
liveMaxLatencyDurationCount: 4,
maxAudioFramesDrift: 1,         // correct audio drift after 1-frame deviation
nudgeOffset: 0.1,               // seek 100ms forward to resync when drifting
nudgeMaxRetry: 5,
maxBufferHole: 0.5,             // tolerate small gaps at segment boundaries
```

#### Diagnostic workflow

If the delay reappears, work through these steps in order:

```bash
# 1. Confirm segment durations are 2.0s (not 2.4s)
cat /var/www/hls/mhbn-ch1/index.m3u8 | grep EXTINF
# Should show: #EXTINF:2.000000,

# 2. Confirm GOP size in running ffmpeg
ps aux | grep ffmpeg | grep -v grep | grep -o '\-g [0-9]*'
# Should show: -g 50

# 3. Confirm aresample correction rate
ps aux | grep ffmpeg | grep -v grep | grep -o 'aresample=[^ ]*'
# Should show: aresample=async=1000

# 4. Measure live A/V offset (repeat across 4+ segments to check for drift)
for seg in $(ls -t /var/www/hls/mhbn-ch1/*.ts | head -6 | tac); do
  ffprobe -v quiet -print_format json -show_packets -read_intervals '%+#10' $seg \
    | python3 -c "
import json,sys; d=json.load(sys.stdin)
v=[p for p in d['packets'] if p['codec_type']=='video']
a=[p for p in d['packets'] if p['codec_type']=='audio']
print(f'{\"$(basename $seg)\"}: {(float(v[0].get(\"pts_time\",0))-float(a[0].get(\"pts_time\",0)))*1000:.1f}ms')
" 2>/dev/null
done
# Healthy: values in 80-130ms range, varying by <20ms between segments
# Sick:    values steadily increasing segment-to-segment (drift not corrected)
```

If the offset is steadily increasing, check that Liquidsoap was restarted after
the `channels.liq` change — verify the running ffmpeg process has `-g 50` and
`aresample=async=1000` as above.

If segments are 2.4s again, Liquidsoap config was reverted or the live file on
zikzak was overwritten. Re-deploy `zikzak/liquidsoap/channels.liq` from the
repo and restart:

```bash
# From this repo:
scp zikzak/liquidsoap/channels.liq zephyr:/tmp/channels.liq
ssh zephyr "scp /tmp/channels.liq nthmost@10.100.0.5:/tmp/ && \
  ssh nthmost@10.100.0.5 'sudo cp /tmp/channels.liq /home/max/liquidsoap/channels.liq && \
  sudo chown max:max /home/max/liquidsoap/channels.liq && \
  sudo systemctl restart zikzak-liquidsoap'"
```

**If all the above checks out and the delay persists**, try reloading the browser
page — hls.js occasionally latches onto a bad A/V offset at startup that a
reload clears. If the delay is consistent across reloads but only happens at
track transitions (not mid-video), see the "Liquidsoap clock drift at transitions"
note in `docs/system-tuning.md`.

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
