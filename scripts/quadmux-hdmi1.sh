#!/bin/bash
# Quad-mux output to HDMI-1
# Combines ch1-ch4 into a 2x2 grid at 1920x1080
# Each quadrant is 960x540, cropped to fill (no black bars)
# Uses VAAPI hardware decoding to offload H264 decode from CPU

export DISPLAY=:0
export XAUTHORITY=/home/max/.Xauthority
export XDG_RUNTIME_DIR=/run/user/1001

exec ffmpeg -hide_banner -loglevel error 2> >(grep -Ev 'non-existing PPS|decode_slice_header error|no frame!' >&2) \
  -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi \
  -thread_queue_size 4096 -i "http://localhost:8000/ch1.ts" \
  -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi \
  -thread_queue_size 4096 -i "http://localhost:8000/ch2.ts" \
  -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi \
  -thread_queue_size 4096 -i "http://localhost:8000/ch3.ts" \
  -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi \
  -thread_queue_size 4096 -i "http://localhost:8000/ch4.ts" \
  -filter_complex "
    [0:v]hwdownload,format=yuv420p,scale=960:540:force_original_aspect_ratio=increase,crop=960:540,setpts=PTS-STARTPTS[v0];
    [1:v]hwdownload,format=yuv420p,scale=960:540:force_original_aspect_ratio=increase,crop=960:540,setpts=PTS-STARTPTS[v1];
    [2:v]hwdownload,format=yuv420p,scale=960:540:force_original_aspect_ratio=increase,crop=960:540,setpts=PTS-STARTPTS[v2];
    [3:v]hwdownload,format=yuv420p,scale=960:540:force_original_aspect_ratio=increase,crop=960:540,setpts=PTS-STARTPTS[v3];
    [v0][v1][v2][v3]xstack=inputs=4:layout=0_0|960_0|0_540|960_540:fill=black[vout];
    [0:a]aresample=async=1[a0];
    [1:a]aresample=async=1[a1];
    [2:a]aresample=async=1[a2];
    [3:a]aresample=async=1[a3];
    [a0][a1][a2][a3]amix=inputs=4:duration=longest[aout]
  " \
  -map "[vout]" -map "[aout]" \
  -f nut -c:v rawvideo -pix_fmt yuv420p -c:a pcm_s16le - | \
  mpv --fs --no-terminal --vo=x11 --ao=null --no-cache -
