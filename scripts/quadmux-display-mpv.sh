#!/bin/bash
# Quad-mux display using mpv lavfi-complex
# Composites 4 icecast channels into a 2x2 grid on HDMI display
#
# Deployed to: /home/max/bin/quadmux-display-mpv.sh on zikzak
# Managed by:  ~/.config/systemd/user/quadmux-display.service (Restart=always)
#
# Robustness notes:
# - reconnect_delay_max=120: survives full liquidsoap restarts (which take 30-60s)
# - IPC watchdog: kills mpv if it stops responding (frozen display), so systemd
#   can restart the service cleanly rather than leaving a frozen quadrant up
# - Do NOT use --profile=low-latency: sets stream-buffer-size=4k which causes
#   lavfi-complex to freeze at track boundaries (PTS discontinuities)

export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1002

# Wait up to 2 minutes for streams to be available
echo "Waiting for streams..."
for i in {1..120}; do
    if curl -s -o /dev/null -m 2 -w "%{http_code}" http://localhost:8000/ch1.ts 2>/dev/null | grep -q 200; then
        echo "Streams ready after $i seconds"
        break
    fi
    sleep 1
done

sleep 3

# IPC watchdog: if mpv stops responding to queries, kill it so systemd restarts cleanly
ipc_watchdog() {
    local pid=$1
    sleep 45  # give mpv time to fully start up and open the IPC socket
    while kill -0 "$pid" 2>/dev/null; do
        sleep 20
        response=$(echo '{"command":["get_property","playback-time"]}' \
            | socat -t3 - UNIX-CONNECT:/tmp/mpv-quadmux.sock 2>/dev/null)
        if [ -z "$response" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$(date): mpv IPC unresponsive, killing for restart"
            kill "$pid" 2>/dev/null
            return
        fi
    done
}

mpv \
    --no-terminal \
    --fs \
    --vo=gpu \
    --hwdec=nvdec-copy \
    --ao=null \
    --video-sync=display-resample \
    --video-aspect-override=16:9 \
    --cache=yes \
    --demuxer-max-bytes=100MiB \
    --demuxer-readahead-secs=10 \
    --cache-pause=yes \
    --demuxer-lavf-o-add=fflags=+discardcorrupt \
    --stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=120 \
    --input-ipc-server=/tmp/mpv-quadmux.sock \
    --log-file=/tmp/mpv-quadmux.log \
    --lavfi-complex="[vid1]scale=960:540[v0];[vid2]scale=960:540[v1];[vid3]scale=960:540[v2];[vid4]scale=960:540[v3];[v0][v1]hstack[top];[v2][v3]hstack[bottom];[top][bottom]vstack[vo]" \
    --external-file=http://localhost:8000/ch2.ts \
    --external-file=http://localhost:8000/ch3.ts \
    --external-file=http://localhost:8000/ch4.ts \
    http://localhost:8000/ch1.ts &

MPV_PID=$!
ipc_watchdog $MPV_PID &
WATCHDOG_PID=$!

wait $MPV_PID
kill $WATCHDOG_PID 2>/dev/null
