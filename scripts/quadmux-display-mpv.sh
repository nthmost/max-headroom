#!/bin/bash
# Quad-mux display using mpv lavfi-complex.
# Composites 4 icecast channels into a 2x2 grid on the secondary GPU's HDMI
# output via direct DRM/KMS (no X server). Requires nvidia_drm.modeset=1.
#
# Deployed to: /opt/max-headroom/bin/quadmux-display-mpv.sh
# Managed by:  /etc/systemd/system/quadmux-display.service (Restart=always)
#
# Environment (set by the systemd unit):
#   CUDA_VISIBLE_DEVICES — GPU index for NVDEC (pin decode to the kiosk GPU)
#   QM_DRM_DEVICE        — /dev/dri/cardN of the kiosk GPU
#   QM_DRM_CONNECTOR     — DRM connector name (e.g. HDMI-A-2)
#   QM_DRM_MODE          — output mode (e.g. 1920x1080)
#
# Robustness notes:
# - reconnect_delay_max=120: survives full liquidsoap restarts (30-60s).
# - Do NOT use --profile=low-latency: sets stream-buffer-size=4k which causes
#   lavfi-complex to freeze at track boundaries (PTS discontinuities).

set -u
QM_DRM_DEVICE="${QM_DRM_DEVICE:-/dev/dri/card2}"
QM_DRM_CONNECTOR="${QM_DRM_CONNECTOR:-HDMI-A-2}"
QM_DRM_MODE="${QM_DRM_MODE:-1920x1080}"

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

exec mpv \
    --no-terminal \
    --vo=gpu \
    --gpu-context=drm \
    --drm-device="${QM_DRM_DEVICE}" \
    --drm-connector="${QM_DRM_CONNECTOR}" \
    --drm-mode="${QM_DRM_MODE}" \
    --hwdec=nvdec-copy \
    --ao=null \
    --video-sync=desync \
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
    http://localhost:8000/ch1.ts
