#!/usr/bin/liquidsoap
# station.liq — Cursed TV Station
# Requires liquidsoap >= 2.2
#
# Run: liquidsoap station.liq
# (from this directory, so %include resolves correctly)

%include "config.liq"

# ─── Frame settings ────────────────────────────────────────────────────────
settings.frame.video.width    := video_width
settings.frame.video.height   := video_height
settings.frame.video.framerate := video_fps
settings.frame.audio.samplerate := audio_samplerate

log.level := 3

# ─── Content sources ───────────────────────────────────────────────────────

main = playlist(
  id="main",
  mode="randomize",
  reload_mode="watch",
  content_dir ^ "/main"
)

glitch = playlist(
  id="glitch",
  mode="randomize",
  reload_mode="watch",
  content_dir ^ "/glitch"
)

dead_air = playlist(
  id="dead_air",
  mode="randomize",
  reload_mode="watch",
  content_dir ^ "/dead_air"
)

idents = playlist(
  id="idents",
  mode="randomize",
  reload_mode="watch",
  content_dir ^ "/idents"
)

# ─── Rotation ──────────────────────────────────────────────────────────────

rotation = random(
  id="rotation",
  weights=rotation_weights,
  [main, glitch, dead_air]
)

# ─── Ident injection ───────────────────────────────────────────────────────
# Every ident_every tracks, push a station ident to a priority queue
# that interrupts the rotation between clips.

idents_q = request.queue(id="idents_queue")
track_counter = ref(0)

rotation = source.on_track(
  rotation,
  fun(meta) -> begin
    track_counter := !track_counter + 1;
    if !track_counter mod ident_every == 0 then begin
      ident_files = file.ls(absolute=true, content_dir ^ "/idents");
      if list.length(ident_files) > 0 then begin
        idx = random.int(min=0, max=list.length(ident_files));
        f = list.nth(default="", ident_files, idx);
        if string.length(f) > 0 then
          idents_q.push(request.create(f))
        end
      end
    end
  end
)

# Idents queue has priority; falls back to rotation when empty
station = fallback(
  id="station",
  track_sensitive=true,
  [idents_q, rotation]
)

# Emergency safety net: if rotation is somehow dry, hold on black
station = fallback(
  id="safe",
  track_sensitive=false,
  [station, blank(id="emergency_blank")]
)

# ─── Outputs ───────────────────────────────────────────────────────────────

# Local SDL window — for testing or direct HDMI display with an X session
if enable_sdl then
  output.sdl(
    id="local_display",
    fallible=true,
    station
  )
end

# Icecast2 — enable in config.liq for network/streaming distribution
# Connect mpv/VLC to http://host:8000/cursed to drive HDMI displays
if enable_icecast then
  output.icecast(
    id="icecast_out",
    %vorbis(quality=0.6),
    host=icecast_host,
    port=icecast_port,
    password=icecast_password,
    mount=icecast_mount,
    name=icecast_name,
    description=icecast_description,
    station
  )
end
