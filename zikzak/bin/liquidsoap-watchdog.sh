#!/bin/bash
# liquidsoap-watchdog.sh — reactive recovery for the liquidsoap livelock.
#
# The quadmux CRT wall is fed by:
#   zikzak-liquidsoap -> per-channel ffmpeg nvenc encoders -> local icecast
#   (ch1-4.ts) -> consumed by quadmux mpv (the CRTs) AND the mhbn-relay-*
#   services (public mirror to nthmost.com).
#
# Liquidsoap periodically thrashes into a clock catch-up spiral (its log
# fills with "We must catchup NN seconds!") and/or pins against its
# MemoryHigh ceiling, at which point it can no longer feed the encoder
# pipes in real time. ffmpeg then logs "Broken pipe", stops publishing,
# and every icecast mount 404s — the CRT wall goes blank while the service
# still reports active. See reference_zikzak_hardware.md and
# project_zikzak_quadmux_drift.md.
#
# The 4AM daily-display-restart.timer preempts the slow memory-leak freeze,
# but a mid-day livelock can blank the wall for hours until a human notices
# (it did on 2026-10-05, dead from ~16:15). This watchdog runs every couple
# of minutes, checks the icecast mounts end-to-end, and restarts the stack
# when they're down.
#
# Guardrails:
#  - Requires a SUSTAINED failure (two probes ~12s apart) so it never acts
#    on a transient blip or a mount mid-reconnect.
#  - Rate-limited via COOLDOWN so a deeper failure (that a restart can't
#    fix) becomes a loud log line, not a restart storm.
#  - Honors a GRACE window after liquidsoap (re)starts so the mounts have
#    time to populate before we judge them.
#
# Runs as root (touches services owned by different users).
# Deployed to /usr/local/bin by the manual install steps below:
#   sudo install -m 0755 zikzak/bin/liquidsoap-watchdog.sh /usr/local/bin/
#   sudo install -m 0644 zikzak/systemd/liquidsoap-watchdog.service /etc/systemd/system/
#   sudo install -m 0644 zikzak/systemd/liquidsoap-watchdog.timer   /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now liquidsoap-watchdog.timer

set -uo pipefail

ICECAST="http://localhost:8000"
CHANNELS="1 2 3 4"
MIN_HEALTHY=3            # fewer than this many mounts at 200 == unhealthy
COOLDOWN=600            # min seconds between auto-restarts
GRACE=120              # ignore health within this many secs of liquidsoap start
STAMP=/run/liquidsoap-watchdog.last-restart
LOG=/var/log/zikzak-liquidsoap-watchdog.log

log() { echo "[$(date -Is)] $*" >>"$LOG"; }

healthy_count() {
    local n=0 ch code
    for ch in $CHANNELS; do
        code=$(curl -s -o /dev/null -m 3 -w "%{http_code}" "$ICECAST/ch$ch.ts" 2>/dev/null)
        [ "$code" = "200" ] && n=$((n+1))
    done
    echo "$n"
}

# If liquidsoap isn't running at all, start it and let the next tick judge.
if ! systemctl is-active --quiet zikzak-liquidsoap.service; then
    log "zikzak-liquidsoap not active — starting it"
    systemctl start zikzak-liquidsoap.service
    exit 0
fi

# Grace window: skip if liquidsoap (re)started recently — mounts need a
# moment to come back, and we don't want to fight the 4AM daily restart or
# our own previous restart.
start_epoch=$(date -d "$(systemctl show -p ActiveEnterTimestamp --value zikzak-liquidsoap.service 2>/dev/null)" +%s 2>/dev/null || echo 0)
now_epoch=$(date +%s)
if [ "$start_epoch" -gt 0 ] && [ $((now_epoch - start_epoch)) -lt "$GRACE" ]; then
    exit 0
fi

# First probe. Healthy -> nothing to do.
h1=$(healthy_count)
[ "$h1" -ge "$MIN_HEALTHY" ] && exit 0

# Debounce: re-probe after a short pause; it may just be mid-reconnect.
sleep 12
h2=$(healthy_count)
[ "$h2" -ge "$MIN_HEALTHY" ] && exit 0

# Sustained failure. Enforce cooldown before kicking the stack.
last=0
[ -f "$STAMP" ] && last=$(cat "$STAMP" 2>/dev/null || echo 0)
now_epoch=$(date +%s)
if [ $((now_epoch - last)) -lt "$COOLDOWN" ]; then
    log "UNHEALTHY ($h2/4 mounts up) but within cooldown (last restart $((now_epoch-last))s ago) — NOT restarting; deeper problem, check liquidsoap"
    exit 0
fi

log "UNHEALTHY: only $h2/4 icecast mounts serving across two probes — restarting liquidsoap + quadmux (livelock recovery)"
echo "$now_epoch" >"$STAMP"

systemctl restart zikzak-liquidsoap.service
sleep 3
if ! systemctl is-active --quiet zikzak-liquidsoap.service; then
    log "ERROR: zikzak-liquidsoap did not come back active after restart — skipping mpv restart"
    exit 1
fi

# Give ffmpeg encoders time to republish the mounts before mpv reconnects.
sleep 30
systemctl restart quadmux-display.service

sleep 8
post=$(healthy_count)
log "post-restart: $post/4 mounts serving"
exit 0
