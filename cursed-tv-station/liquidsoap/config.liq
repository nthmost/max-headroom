# config.liq — Cursed TV Station configuration
# Edit this file, do not touch station.liq for basic setup.

# ─── Content paths ─────────────────────────────────────────────────────────
content_dir = "/home/user/tv/content"

# ─── Scheduling ────────────────────────────────────────────────────────────
# Insert a station ident every N clips
ident_every = 4

# Weighted rotation: [main, glitch, dead_air]
# e.g. [7, 2, 1] = 70% main, 20% glitch, 10% dead air
rotation_weights = [7, 2, 1]

# ─── Video ─────────────────────────────────────────────────────────────────
video_width    = 640
video_height   = 480
video_fps      = 25

# ─── Audio ─────────────────────────────────────────────────────────────────
audio_samplerate = 44100

# ─── Outputs ───────────────────────────────────────────────────────────────
# Local SDL window (useful for dev/testing on a machine with a display)
enable_sdl = true

# Icecast2 output
enable_icecast       = false
icecast_host         = "localhost"
icecast_port         = 8000
icecast_password     = "changeme"
icecast_mount        = "/cursed"
icecast_name         = "Cursed TV"
icecast_description  = "You weren't supposed to find this channel."
