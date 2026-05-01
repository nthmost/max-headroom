#!/bin/bash
# Quad-mux display using mpv lavfi-complex
# Composites 4 icecast channels into a 2x2 grid on HDMI display
#
# Deployed to: /home/max/bin/quadmux-display-mpv.sh on zikzak
# Managed by:  ~/.config/systemd/user/quadmux-display.service
#
# NOTE: Do NOT use --profile=low-latency here. That sets stream-buffer-size=4k
# and fflags=+nobuffer, which causes the lavfi-complex compositor to freeze when
# liquidsoap crosses a track boundary (brief PTS discontinuity). This display
# does not need low latency — it needs stability.

export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1002

echo "Waiting for streams..."
for i in {1..60}; do
    if curl -s -o /dev/null -m 2 -w "%{http_code}" http://localhost:8000/ch1.ts 2>/dev/null | grep -q 200; then
        echo "Streams ready after $i seconds"
        break
    fi
    sleep 1
done

sleep 3

exec mpv \
    --no-terminal \
    --fs \
    --vo=gpu \
    --ao=null \
    --video-sync=display-resample \
    --video-aspect-override=16:9 \
    --cache=yes \
    --demuxer-max-bytes=100MiB \
    --demuxer-readahead-secs=10 \
    --cache-pause=yes \
    --demuxer-lavf-o-add=fflags=+discardcorrupt \
    --input-ipc-server=/tmp/mpv-quadmux.sock \
    --log-file=/tmp/mpv-quadmux.log \
    --lavfi-complex="[vid1]scale=960:540[v0];[vid2]scale=960:540[v1];[vid3]scale=960:540[v2];[vid4]scale=960:540[v3];[v0][v1]hstack[top];[v2][v3]hstack[bottom];[top][bottom]vstack[vo]" \
    --external-file=http://localhost:8000/ch2.ts \
    --external-file=http://localhost:8000/ch3.ts \
    --external-file=http://localhost:8000/ch4.ts \
    http://localhost:8000/ch1.ts
