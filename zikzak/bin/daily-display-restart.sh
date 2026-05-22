#!/bin/bash
# daily-display-restart.sh — preempt the quadmux freeze cycle.
#
# Liquidsoap leaks memory over uptime (observed ~5-8 GB RSS after 2-3 days
# on a 16 GB box with 2 GB swap). Once swap fills, mpv stalls on swap I/O
# and the CRT wall freezes (project_zikzak_quadmux_drift.md). Until the
# leak is fixed properly, restart the stack daily at 4AM to keep ahead of it.
#
# Sequence: restart liquidsoap, wait 30s for icecast mountpoints to come
# back, then restart quadmux mpv. The 30s pause gives ffmpeg relays time
# to reconnect (their --reconnect=1 will retry, but mpv connecting to
# dead mountpoints would fail and Restart=always would spam).
#
# Run as root (the systemd unit is User=root since it touches multiple
# services owned by different users).

set -uo pipefail

LOG="/var/log/zikzak-daily-restart.log"
log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

log "=== daily display-stack restart start ==="

log "restarting zikzak-liquidsoap"
systemctl restart zikzak-liquidsoap.service
sleep 3
systemctl is-active --quiet zikzak-liquidsoap.service || {
    log "ERROR: zikzak-liquidsoap did not come back active — aborting (no mpv restart)"
    exit 1
}

log "waiting 30s for icecast mountpoints to repopulate"
sleep 30

log "restarting quadmux-display"
systemctl restart quadmux-display.service
sleep 3
systemctl is-active --quiet quadmux-display.service || {
    log "ERROR: quadmux-display did not come back active"
    exit 1
}

log "=== done ==="
