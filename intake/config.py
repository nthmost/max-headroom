import os

LOG_DIR = "/var/log/transcode/intake"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# YouTube downloads run on loki, then rsync directly to zikzak
LOKI_HOST      = os.environ.get("LOKI_HOST",       "loki")
LOKI_YT_DLP    = os.environ.get("LOKI_YT_DLP",     "/home/nthmost/.local/bin/yt-dlp")
LOKI_COOKIES   = os.environ.get("LOKI_COOKIES",    "/home/nthmost/yt-cookies.txt")

ZIKZAK_USER    = os.environ.get("ZIKZAK_USER",     "nthmost")
ZIKZAK_HOST    = os.environ.get("ZIKZAK_HOST",     "10.100.0.5")
ZIKZAK_JUMP    = os.environ.get("ZIKZAK_JUMP",     "zephyr")
ZIKZAK_MEDIA   = os.environ.get("ZIKZAK_MEDIA",    "/mnt/media")
ZIKZAK_DROPBOX = os.environ.get("ZIKZAK_DROPBOX",  "/mnt/dropbox")

# IA downloads still run locally (no throttling issue)
YT_DLP         = os.environ.get("YT_DLP",          "/usr/local/bin/yt-dlp")
YT_COOKIES     = os.environ.get("YT_COOKIES",      "")
INCOMING_DIR   = os.environ.get("INCOMING_DIR",     "/mnt/incoming")

# Transcode settings (used on loki before push to zikzak)
# Loki has an RTX 4080 — use NVENC (not VAAPI)
HW_ACCEL       = os.environ.get("HW_ACCEL",        "nvenc")  # "nvenc" or "vaapi"
VAAPI_DEVICE   = os.environ.get("VAAPI_DEVICE",    "/dev/dri/renderD128")
TRANSCODE_DIR  = os.environ.get("TRANSCODE_DIR",   "/mnt/media_transcoded")
PORT = 8765

API_KEY = os.environ.get("INTAKE_API_KEY", "changeme")

CATEGORIES = [
    "action",
    "anime",
    "cartoons",
    "comedy",
    "commercials",
    "documentaries",
    "gaming",
    "interstitials",
    "music",
    "philosophy",
    "prelinger",
    "tv_shows",
]

LENGTHS = ["short", "medium", "long"]

def classify_length(seconds):
    """Classify a duration in seconds into short/medium/long."""
    if seconds is None or seconds == 0:
        return "medium"
    if seconds < 300:
        return "short"
    if seconds < 1800:
        return "medium"
    return "long"
