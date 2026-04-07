# Scripts

These scripts are deployed to `~/bin/` on their respective hosts.

## loki.local Scripts

### process-incoming.sh (Primary - runs via cron)
Automated pipeline that processes new downloads:
1. Moves files from `/mnt/incoming/` to `/mnt/media/` (cataloguing)
2. Transcodes to 960x540 H.264 using NVENC
3. Pushes to headroom.local
4. Regenerates playlists on headroom

**Cron:** `*/5 * * * *` (every 5 minutes)
**Logs:** `/var/log/transcode/cron.log`

### transcode-for-quadmux.sh
Transcodes all media in `/mnt/media/` to 960x540 H.264 using NVENC.
- Output: `/mnt/media_transcoded/`
- Logs: `/var/log/transcode/`
- Handles files without audio by adding silent tracks
- Skips already-transcoded files (resumable)

### sync-from-headroom.sh
Backs up headroom originals and copies non-prelinger content for transcoding.
- Backup: `/mnt/media_originals_backup/`

### push-to-headroom.sh
Rsyncs transcoded media to headroom.local.

## headroom.local Scripts

### regenerate-playlists.sh
Regenerates M3U playlists from actual files on disk.
- Scans `/mnt/media/`
- Outputs to `/home/max/playlists/`
- Creates category playlists + all.m3u, all-short.m3u, all-long.m3u

## Deployment

To deploy updated scripts:

```bash
# On loki
scp scripts/process-incoming.sh loki.local:~/bin/
scp scripts/transcode-for-quadmux.sh loki.local:~/bin/
scp scripts/sync-from-headroom.sh loki.local:~/bin/
scp scripts/push-to-headroom.sh loki.local:~/bin/
ssh loki.local "chmod +x ~/bin/*.sh"

# On headroom
scp scripts/regenerate-playlists.sh headroom.local:~/bin/
ssh headroom.local "chmod +x ~/bin/*.sh"
```

## Cron Setup (loki.local)

The process-incoming.sh script runs automatically via cron:

```bash
# Add to crontab
crontab -e
*/5 * * * * /home/nthmost/bin/process-incoming.sh >> /var/log/transcode/cron.log 2>&1
```
