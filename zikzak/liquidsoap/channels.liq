# Zikzak — 4-channel video stream

# Canvas resolution: source files are 960x540, letterboxed to 960x720.
# Height MUST be 720 (multiple of 16) for correct NVENC stride alignment.
# Do NOT change to 540 — causes green overlay on all channels.
settings.frame.video.width.set(960)
settings.frame.video.height.set(720)

settings.server.telnet.set(true)
settings.server.telnet.bind_addr.set("127.0.0.1")
settings.server.telnet.port.set(1234)

log.file.set(true)
log.file.path.set("/home/max/liquidsoap/channels.log")

# NVENC: canvas is already 960x720, no scale filter needed
let nvenc_cmd_base =
  "-vf \"format=yuv420p\" " ^
  "-c:v h264_nvenc -preset p4 -profile:v high " ^
  "-b:v 1400k -maxrate 1400k -bufsize 2800k -g 60 " ^
  "-c:a aac -b:a 128k -ac 2 -ar 44100 -f mpegts "

def encoder_cmd(mount) =
  nvenc_cmd_base ^ "icecast://source:noisebridge@localhost:8000" ^ mount
end

# ── Playlists ──────────────────────────────────────────────────────────────────

music_long_playlist   = "/home/max/playlists/music-long.m3u"
short_medium_playlist = "/home/max/playlists/short-medium.m3u"

# Interstitial and commercial file lists loaded at startup.
# Add files to /mnt/media/interstitials/ and /mnt/media/joke_commercials/
# then restart liquidsoap to pick them up.
interstitial_files = ref(process.read.lines(
  "find /mnt/media/interstitials -type f -name '*.mp4' 2>/dev/null"
))
commercial_files = ref(process.read.lines(
  "find /mnt/media/joke_commercials -type f -name '*.mp4' 2>/dev/null"
))

def random_pick(files) =
  n = list.length(files)
  if n == 0 then null()
  else null(list.nth(files, random.int(max=n)))
  end
end

# ── Now-playing metadata → Icecast ─────────────────────────────────────────────
# On each main-content track change, push "Title [category]" to both the local
# icecast (zikzak) and the relay icecast (nthmost.com). The webapp reads
# http://nthmost.com:8000/status-json.xsl to display now-playing info.

def push_nowplaying(local_mount, relay_mount, meta) =
  filename = meta["filename"]
  if filename != "" and meta["is_insert"] != "true" then
    # Build "Title [category]" label from the file path
    # Path format: /mnt/media/<category>/<length>/<title>.mp4
    # Uses python3 to transliterate fancy Unicode (Mathematical Bold, Fullwidth,
    # etc.) down to plain ASCII so Icecast metadata doesn't get garbled.
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

# ── ch1: Long-form music only, no interruptions ────────────────────────────────
# Feed: music-long.m3u (DJ sets, live concerts, long mixes)

def make_music_channel(id) =
  s = playlist(id="#{id}", mode="randomize", reload_mode="watch", music_long_playlist)
  s.on_track(fun(meta) -> push_nowplaying("/#{id}.ts", "/mhbn-#{id}.ts", meta))
  mksafe(s)
end

# ── ch2/3/4: Programmed channels ───────────────────────────────────────────────
# Feed: short-medium.m3u
# After every program: interstitial
# After every 10th program: commercial instead of interstitial

def make_programmed_channel(id) =
  content = playlist(id="#{id}", mode="randomize", reload_mode="watch", short_medium_playlist)
  inject  = request.queue(id="#{id}_inject")

  track_count     = ref(0)
  last_was_insert = ref(false)

  s = fallback(track_sensitive=true, [inject, content])

  s.on_track(fun(meta) ->
    if not last_was_insert() then
      # A main content track just started — push metadata and schedule an insert
      push_nowplaying("/#{id}.ts", "/mhbn-#{id}.ts", meta)
      last_was_insert := true
      track_count := track_count() + 1
      files =
        if track_count() mod 10 == 0 then commercial_files()
        else interstitial_files()
        end
      pick = random_pick(files)
      if null.defined(pick) then
        f = null.get(pick)
        r = request.create("annotate:is_insert=\"true\":" ^ f)
        ignore(inject.push(r))
      else
        # No insert files available yet — reset so next track tries again
        last_was_insert := false
      end
    else
      # An insert just started — clear the flag so next track is treated as content
      last_was_insert := false
    end
  )

  mksafe(s)
end

# ── Channel assignments ────────────────────────────────────────────────────────

ch1 = make_music_channel("ch1")
ch2 = make_programmed_channel("ch2")
ch3 = make_programmed_channel("ch3")
ch4 = make_programmed_channel("ch4")

output.external.ffmpeg(id="enc_ch1", show_command=true, reopen_on_error=fun (_)->5., encoder_cmd("/ch1.ts"), ch1)
output.external.ffmpeg(id="enc_ch2", show_command=true, reopen_on_error=fun (_)->5., encoder_cmd("/ch2.ts"), ch2)
output.external.ffmpeg(id="enc_ch3", show_command=true, reopen_on_error=fun (_)->5., encoder_cmd("/ch3.ts"), ch3)
output.external.ffmpeg(id="enc_ch4", show_command=true, reopen_on_error=fun (_)->5., encoder_cmd("/ch4.ts"), ch4)
