#!/bin/bash
# encode-ch.sh — external NVENC encoder for one quadmux channel.
# Reads raw AVI (rawvideo + pcm_s16le) from liquidsoap on stdin, H.264-encodes
# via NVENC, publishes mpegts to the local icecast mount given as $1 (e.g. /ch1.ts).
# Invoked by liquidsoap `output.external`, which in 2.4.x execs argv directly
# (no shell) — so all shell quoting lives here, not in channels.liq.
set -u
mount="$1"
exec ffmpeg -hide_banner -loglevel warning \
  -f avi -vcodec rawvideo -r 25 -acodec pcm_s16le -i pipe:0 \
  -r 25 -vf "format=yuv420p" \
  -c:v h264_nvenc -preset p4 -profile:v high \
  -b:v 1400k -maxrate 1400k -bufsize 2800k -g 60 \
  -c:a aac -b:a 128k -ac 2 -ar 44100 \
  -af "aresample=async=1" -max_muxing_queue_size 1024 \
  -f mpegts "icecast://source:noisebridge@localhost:8000${mount}"
