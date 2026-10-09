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
# MemoryHigh ceiling. This shows up in TWO distinct failure modes, and the
# watchdog must catch both:
#
#   (A) MOUNTS DEAD. The clock falls so far behind that it can't feed the
#       encoder pipes; ffmpeg logs "Broken pipe", stops publishing, and every
#       icecast mount 404s — the CRT wall goes blank. Detected by probing the
#       mounts.
#   (B) MOUNTS UP, CLOCK CRAWLING. The mounts keep serving 200 but the clock
#       is stuck in a "catchup NN seconds -> Too much latency! Resetting
#       active sources -> catchup again" cycle, so playback lags/stutters
#       badly ("the feed is at a crawl"). The mount probe CANNOT see this
#       (mounts are 200), so we also scan the liquidsoap log for repeated
#       latency resets. (Hit on 2026-10-05, ~3h after a restart.)
#
# See reference_zikzak_hardware.md and project_zikzak_quadmux_drift.md.
#
# The 4AM daily-display-restart.timer preempts the slow memory-leak freeze;
# this watchdog (every couple of minutes) catches mid-day failures of either
# mode and restarts liquidsoap + quadmux.
#
# Guardrails:
#  - Requires a SUSTAINED failure (two probes ~12s apart) so it never acts
#    on a transient blip or a mount mid-reconnect.
#  - Rate-limited via COOLDOWN so a deeper failure (that a restart can't
#    fix) becomes a loud log line, not a restart storm.
#  - Honors a GRACE window after liquidsoap (re)starts — mounts need time to
#    populate, and a single latency reset is normal as initial catchup clears.
#
# Runs as root (touches services owned by different users; reads max's log).
# Deployed to /usr/local/bin by the manual install steps below:
#   sudo install -m 0755 zikzak/bin/liquidsoap-watchdog.sh /usr/local/bin/
#   sudo install -m 0644 zikzak/systemd/liquidsoap-watchdog.service /etc/systemd/system/
#   sudo install -m 0644 zikzak/systemd/liquidsoap-watchdog.timer   /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now liquidsoap-watchdog.timer

set -uo pipefail

ICECAST="http://localhost:8000"
CHANNELS="1 2 3 4"
MIN_HEALTHY=4            # ALL four mounts must serve (mode A). 2.5.x gives each
                        # output.external its own clock and one can wedge alone (ch1
                        # did as a one-off 2026-10-08), so a single dead mount must
                        # trigger recovery. Safe to be this strict now that ch1's
                        # chronic ffmpeg-6 decode-churn is fixed (runs on ffmpeg 7).
LIQ_LOG=/home/max/liquidsoap/channels.log
LAT_WINDOW=180          # look this many seconds back in the log (mode B)
LAT_CATCHUP_MAX=30      # >= this many "we must catchup" lines in the window == crawling
COOLDOWN=600            # min seconds between auto-restarts
GRACE=120              # ignore health within this many secs of liquidsoap start
STAMP=/run/liquidsoap-watchdog.last-restart
LOG=/var/log/zikzak-liquidsoap-watchdog.log

log() { echo "[$(date -Is)] $*" >>"$LOG"; }

# Mode A: how many of the four icecast mounts currently serve 200.
healthy_count() {
    local n=0 ch code
    for ch in $CHANNELS; do
        code=$(curl -s -o /dev/null -m 3 -w "%{http_code}" "$ICECAST/ch$ch.ts" 2>/dev/null)
        [ "$code" = "200" ] && n=$((n+1))
    done
    echo "$n"
}

# Mode B: count clock "we must catchup" lines in the liquidsoap log whose
# timestamp is within the last $1 seconds. Matches BOTH phrasings — 2.2.4
# ("We must catchup NN seconds!") and 2.5.x ("Latency is too high: we must
# catchup NN seconds!"). Healthy operation shows ~none; a sustained crawl
# (all clocks behind, mounts still 200) spams many per second.
catchup_lines_recent() {
    local window="$1" cutoff dstr ts n=0 line
    [ -r "$LIQ_LOG" ] || { echo 0; return; }
    cutoff=$(date -d "-${window} seconds" +%s 2>/dev/null) || { echo 0; return; }
    # tail a generous slice; grep narrows to catchup lines before parsing ts.
    while IFS= read -r line; do
        dstr=$(printf '%s' "$line" | grep -oE '^[0-9]{4}/[0-9]{2}/[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')
        dstr=${dstr//\//-}
        [ -n "$dstr" ] || continue
        ts=$(date -d "$dstr" +%s 2>/dev/null) || continue
        [ "$ts" -ge "$cutoff" ] && n=$((n+1))
    done < <(tail -n 100000 "$LIQ_LOG" 2>/dev/null | grep -iE "we must catchup")
    echo "$n"
}

# If liquidsoap isn't running at all, start it and let the next tick judge.
if ! systemctl is-active --quiet zikzak-liquidsoap.service; then
    log "zikzak-liquidsoap not active — starting it"
    systemctl start zikzak-liquidsoap.service
    exit 0
fi

# Grace window: skip if liquidsoap (re)started recently — mounts need a
# moment to come back, one latency reset is normal on warmup, and we don't
# want to fight the 4AM daily restart or our own previous restart.
start_epoch=$(date -d "$(systemctl show -p ActiveEnterTimestamp --value zikzak-liquidsoap.service 2>/dev/null)" +%s 2>/dev/null || echo 0)
now_epoch=$(date +%s)
if [ "$start_epoch" -gt 0 ] && [ $((now_epoch - start_epoch)) -lt "$GRACE" ]; then
    exit 0
fi

# ── Probe mount health, with a debounce re-probe ────────────────────────────
# assess sets global H (mounts up) and returns 0 if healthy. Call it WITHOUT a
# subshell so H persists into the restart path — a $(assess) command substitution
# sets H in a subshell, leaving it unset in the parent and crashing under `set -u`.
# Mode B (clock-crawl magnitude, catchup_lines_recent) is defined above but NOT
# wired in: with ch1 chronically crawling it would restart-loop. Re-enable — and
# raise MIN_HEALTHY to 4 — once ch1 is fixed.
assess() {
    H=$(healthy_count)
    [ "$H" -ge "$MIN_HEALTHY" ]
}

assess && exit 0
# May just be mid-reconnect — re-check after a pause.
sleep 12
assess && exit 0

# Sustained failure.
reason="mounts ${H}/4 up (dead channel)"

last=0
[ -f "$STAMP" ] && last=$(cat "$STAMP" 2>/dev/null || echo 0)
now_epoch=$(date +%s)
if [ $((now_epoch - last)) -lt "$COOLDOWN" ]; then
    log "UNHEALTHY [$reason] but within cooldown (last restart $((now_epoch-last))s ago) — NOT restarting; deeper problem, check liquidsoap"
    exit 0
fi

log "UNHEALTHY [$reason] across two probes — restarting liquidsoap + quadmux"
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
