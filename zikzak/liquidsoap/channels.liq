# Zikzak — 4-channel video stream
# Managed by Ansible — local edits will be overwritten
#
# Media structure: /mnt/media/<category>/<subdir>/
# Categories: action anime cartoons comedy commercials documentaries
#             gaming interstitials music philosophy prelinger tv_shows
# Prelinger uses era/topic subdirs (1940s, 1950s, ...) not short/medium/long.

# Canvas resolution: source files are 960x540, letterboxed to 960x720.
# Height MUST be 720 (multiple of 16) for correct NVENC stride alignment.
# Do NOT change to 540 — causes green overlay on all channels.
settings.frame.video.width.set(960)
settings.frame.video.height.set(720)

settings.server.telnet.set(true)
settings.server.telnet.bind_addr.set("127.0.0.1")
settings.server.telnet.port.set(1234)

settings.log.file.set(true)
settings.log.file.path.set("/home/max/liquidsoap/channels.log")

# NVENC: canvas is already 960x720, no scale filter needed
let nvenc_cmd_base =
  "-r 25 " ^                                      # Explicit constant 25fps output
  "-vf \"format=yuv420p\" " ^
  "-c:v h264_nvenc -preset p4 -profile:v high " ^
  "-b:v 1400k -maxrate 1400k -bufsize 2800k -g 60 " ^
  "-c:a aac -b:a 128k -ac 2 -ar 44100 " ^
  "-af \"aresample=async=1\" " ^                  # Audio resample to sync with video
  "-max_muxing_queue_size 1024 " ^                # Prevent muxing queue overflows
  "-f mpegts "

def encoder_cmd(mount) =
  "/home/max/liquidsoap/encode-ch.sh " ^ mount
end

let media = "/mnt/media"

# ── Source helper ──────────────────────────────────────────────────────────────
# Each call creates an independent playlist reader; safe to call once per channel.

def dir_src(d) =
  playlist(mode="randomize", reload_mode="watch", d)
end

# ── Insert detection ───────────────────────────────────────────────────────────
# Detect interstitials and commercials by path to suppress now-playing updates.

def is_insert(meta) =
  f = meta["filename"]
  string.contains(prefix="#{media}/interstitials", f) or
  string.contains(prefix="#{media}/commercials", f)
end

# ── Now-playing metadata → Icecast ─────────────────────────────────────────────
# On each main-content track change, push "Title [category]" to both the local
# icecast (zikzak) and the relay icecast (nthmost.com). The webapp reads
# http://nthmost.com:8000/status-json.xsl to display now-playing info.

def push_nowplaying(local_mount, relay_mount, meta) =
  filename = meta["filename"]
  if filename != "" and not is_insert(meta) then
    # Build "Title [category]" label from the file path.
    # Path format: /mnt/media/<category>/.../<title>.mp4
    # Uses python3 to transliterate fancy Unicode down to plain ASCII.
    label = string.trim(
      (process.run(
        "f=" ^ string.quote(filename) ^ "; " ^
        "title=$(basename \"$f\" | sed 's/\\.[^.]*$//'); " ^
        "cat=$(echo \"$f\" | cut -d/ -f4); " ^
        "if [ -n \"$cat\" ]; then raw=\"$title [$cat]\"; else raw=\"$title\"; fi; " ^
        "echo \"$raw\" | python3 -c \"" ^
        "import sys, unicodedata; " ^
        "s = sys.stdin.read().strip(); " ^
        "s = unicodedata.normalize('NFKD', s); " ^
        "print(''.join(c for c in s if ord(c) < 128))" ^
        "\""
      )).stdout
    )
    curl_meta = "curl -sf --get --data-urlencode " ^ string.quote("song=" ^ label) ^ " --data mode=updinfo "
    ignore(process.run(curl_meta ^ string.quote("http://admin:noisebridge@localhost:8000/admin/metadata?mount=" ^ local_mount)))
    ignore(process.run(curl_meta ^ string.quote("http://admin:k0l9j8@nthmost.com:8000/admin/metadata?mount=" ^ relay_mount)))
  end
end

# ── ch1: Long-form music, interstitial between every set ──────────────────────
# rotate strictly alternates: one music track, one interstitial, repeat.

def make_music_channel(id) =
  music_long    = dir_src("#{media}/music/long")
  music_short   = dir_src("#{media}/music/short")
  interstitials = dir_src("#{media}/interstitials")
  # Mix long and short music (weight 2:3), with interstitials after each
  music_mix = random([music_long.{weight=2}, music_short.{weight=3}])
  s = rotate([music_mix, interstitials])
  s.on_track(synchronous=false, fun(meta) -> push_nowplaying("/#{id}.ts", "/mhbn-#{id}.ts", meta))
  mksafe(s)
end

# ── ch2/3/4: Programmed channels ───────────────────────────────────────────────
# Weights: 1 medium-other, 3 short-other, 5 prelinger, 1 interstitial, 1 commercial
# Total weight 11 → ~9 content tracks per 2 inserts ≈ one break every 4-5 programs.
# Prelinger gets weight 5 (combined short+medium) using era/topic subdirs.
#
# To add a new category: append dir_src entries to short_cats / medium_cats.

def make_programmed_channel(id) =
  short_cats = random([
    dir_src("#{media}/anime/short"),
    dir_src("#{media}/cartoons/short"),
    dir_src("#{media}/comedy/short"),
    dir_src("#{media}/documentaries/short"),
    dir_src("#{media}/gaming/short"),
    dir_src("#{media}/philosophy/short"),
    dir_src("#{media}/tv_shows/short"),
  ])
  medium_cats = random([
    dir_src("#{media}/cartoons/medium"),
    dir_src("#{media}/gaming/medium"),
    dir_src("#{media}/philosophy/medium"),
    dir_src("#{media}/tv_shows/medium"),
  ])
  prelinger     = dir_src("#{media}/prelinger")
  interstitials = dir_src("#{media}/interstitials")
  commercials   = dir_src("#{media}/commercials/short")

  s = random([medium_cats.{weight=1}, short_cats.{weight=3}, prelinger.{weight=5}, interstitials.{weight=1}, commercials.{weight=1}])
  s.on_track(synchronous=false, fun(meta) -> push_nowplaying("/#{id}.ts", "/mhbn-#{id}.ts", meta))
  mksafe(s)
end

# ── Channel assignments ────────────────────────────────────────────────────────

ch1 = make_music_channel("ch1")
ch2 = make_programmed_channel("ch2")
ch3 = make_programmed_channel("ch3")
ch4 = make_programmed_channel("ch4")

output.external(id="enc_ch1", reopen_on_error=fun (_)->5., %ffmpeg(format="avi", %video(codec="rawvideo"), %audio(codec="pcm_s16le")), encoder_cmd("/ch1.ts"), ch1)
output.external(id="enc_ch2", reopen_on_error=fun (_)->5., %ffmpeg(format="avi", %video(codec="rawvideo"), %audio(codec="pcm_s16le")), encoder_cmd("/ch2.ts"), ch2)
output.external(id="enc_ch3", reopen_on_error=fun (_)->5., %ffmpeg(format="avi", %video(codec="rawvideo"), %audio(codec="pcm_s16le")), encoder_cmd("/ch3.ts"), ch3)
output.external(id="enc_ch4", reopen_on_error=fun (_)->5., %ffmpeg(format="avi", %video(codec="rawvideo"), %audio(codec="pcm_s16le")), encoder_cmd("/ch4.ts"), ch4)
