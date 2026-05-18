#!/bin/bash
# Quad-mux display using mpv lavfi-complex.
# Composites 4 icecast channels onto the secondary GPU's HDMI output via
# direct DRM/KMS (no X server). Requires nvidia_drm.modeset=1.
#
# Deployed to: /opt/max-headroom/bin/quadmux-display-mpv.sh
# Managed by:  /etc/systemd/system/quadmux-display.service (Restart=always)
#
# Environment (set by the systemd unit):
#   CUDA_VISIBLE_DEVICES — GPU index for NVDEC (pin decode to the kiosk GPU)
#   QM_DRM_DEVICE        — /dev/dri/cardN of the kiosk GPU
#   QM_DRM_CONNECTOR     — DRM connector name (e.g. HDMI-A-2)
#   QM_DRM_MODE          — output mode (e.g. 1920x1080)
#   QM_LAYOUT            — "hstack" for 1x4 horizontal strips (current
#                          splitter behavior at Noisebridge), "quad" for
#                          2x2 grid (legacy). Default: hstack.
#
# Layout map (downstream HDMI splitter at Noisebridge):
#   hstack: input divided into 4 vertical strips (480x1080 each).
#           ch1 -> CRT1, ch2 -> CRT2, ch3 -> CRT3, ch4 -> CRT4.
#           Each channel is squeezed to 480x1080 (4:9) with letterbox.
#   quad:   input divided into 4 quadrants (960x540 each).
#           ch1 -> TL CRT, ch2 -> TR CRT, ch3 -> BL CRT, ch4 -> BR CRT.
#
# Robustness notes:
# - reconnect_delay_max=120: survives full liquidsoap restarts (30-60s).
# - Do NOT use --profile=low-latency: sets stream-buffer-size=4k which
#   causes lavfi-complex to freeze at track boundaries (PTS discontinuities).

set -u
QM_DRM_DEVICE="${QM_DRM_DEVICE:-/dev/dri/card2}"
QM_DRM_CONNECTOR="${QM_DRM_CONNECTOR:-HDMI-A-2}"
QM_DRM_MODE="${QM_DRM_MODE:-1920x1080}"
QM_LAYOUT="${QM_LAYOUT:-hstack}"

# Per-cell scale + a 4-input combine, chosen by QM_LAYOUT.
#
# Aspect-ratio policy: 'quad' stretches to fill its quadrant (matches the
# original Noisebridge behavior — source is 4:3 and the CRTs are 4:3, so
# the apparent 16:9 stretch from mpv's quadrant gets undone by the CRT and
# black bars are wasteful). 'hstack' must letterbox because 480x1080 is a
# wildly different aspect from any plausible source.

case "$QM_LAYOUT" in
    hstack)
        # 1x4 horizontal — each channel becomes a 480x1080 vertical strip,
        # aspect-preserved with black bars top/bottom.
        scale_cell="scale=480:1080:force_original_aspect_ratio=decrease,pad=480:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        combine="[v0][v1][v2][v3]hstack=inputs=4[vo]"
        ;;
    quad)
        # 2x2 grid — each channel becomes a 960x540 quadrant, stretched to
        # fill (CRT undoes the apparent distortion).
        scale_cell="scale=960:540,setsar=1"
        combine="[v0][v1]hstack[top];[v2][v3]hstack[bottom];[top][bottom]vstack[vo]"
        ;;
    *)
        echo "Unknown QM_LAYOUT=$QM_LAYOUT (expected: hstack | quad)" >&2
        exit 2
        ;;
esac

LAVFI="[vid1]${scale_cell}[v0];[vid2]${scale_cell}[v1];[vid3]${scale_cell}[v2];[vid4]${scale_cell}[v3];${combine}"

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
    --lavfi-complex="$LAVFI" \
    --external-file=http://localhost:8000/ch2.ts \
    --external-file=http://localhost:8000/ch3.ts \
    --external-file=http://localhost:8000/ch4.ts \
    http://localhost:8000/ch1.ts
