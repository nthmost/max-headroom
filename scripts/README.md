# Scripts

These scripts are deployed to `~/bin/` on their respective hosts.

## loki.nthmost.net Scripts (Transcoding + Intake)

### process-incoming.sh (Primary - runs via cron)
Automated pipeline that processes new downloads:
1. Moves files from `/mnt/incoming/` to `/mnt/media/` (cataloguing)
2. Transcodes to 960x540 H.264 using NVENC (RTX 4080); falls back to VAAPI
   if `HW_ACCEL=vaapi` is set in the env.
3. Pushes each transcoded file to `zikzak:/mnt/dropbox/` (bandwidth-limited
   to 20MB/s). The dropbox-watchdog on zikzak validates and files into
   `/mnt/media/<category>/<length>/` and updates `pipeline_status` in mhbn.

**Cron:** `*/5 * * * *` (every 5 minutes)
**Logs:** `/var/log/transcode/cron.log`

### transcode-for-quadmux.sh
Transcodes all media in `/mnt/media/` to 960x540 H.264.
- Output: `/mnt/media_transcoded/`
- Logs: `/var/log/transcode/`
- Handles files without audio by adding silent tracks
- Skips already-transcoded files (resumable)
- Validates GPU encoder availability on startup

### push-to-zikzak.sh
Rsyncs transcoded media to `zikzak:/mnt/dropbox/` with bandwidth limiting.
- Bandwidth: Limited to 20MB/s to avoid interrupting icecast2 stream
- The dropbox-watchdog on zikzak handles validation + filing automatically;
  liquidsoap picks up new files via inotify, no playlist regen needed.

### cleanup-transcoded.sh (runs weekly via cron)
Cleans up old transcoded files on loki to save disk space.
- Deletes files older than 7 days from `/mnt/media_transcoded/`
- Removes empty directories
- Logs freed space

**Cron:** `0 3 * * 0` (Sunday 3am)


## zikzak Scripts (Streaming Server)

zikzak's scripts are deployed by ansible (see `ansible/roles/`). The
historical `regenerate-playlists.sh` flow is no longer used — liquidsoap
watches the media directories via inotify (`reload_mode="watch"`), so new
files appear in source rotation without any external trigger.

The dropbox-watchdog service (`/etc/systemd/system/dropbox-watchdog.service`,
managed by the `dropbox-watchdog` ansible role) handles incoming files from
loki and updates the mhbn `pipeline_status` column accordingly.

## Deployment

To deploy updated scripts:

```bash
# On loki (transcoding + intake)
scp scripts/process-incoming.sh loki.nthmost.net:~/bin/
scp scripts/transcode-for-quadmux.sh loki.nthmost.net:~/bin/
scp scripts/push-to-zikzak.sh loki.nthmost.net:~/bin/
scp scripts/cleanup-transcoded.sh loki.nthmost.net:~/bin/
ssh loki.nthmost.net "chmod +x ~/bin/*.sh"
```

zikzak services are deployed via ansible: `ansible-playbook playbooks/zikzak.yml`.

## Cron Setup

### loki.nthmost.net

```bash
# Add to crontab
crontab -e

# Process incoming files every 5 minutes
*/5 * * * * /home/nthmost/bin/process-incoming.sh >> /var/log/transcode/cron.log 2>&1

# Cleanup old transcoded files weekly (Sunday 3am)
0 3 * * 0 /home/nthmost/bin/cleanup-transcoded.sh >> /var/log/transcode/cleanup.log 2>&1
```
