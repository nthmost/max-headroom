import os

LOG_DIR = "/var/log/transcode/intake"
DB_PATH = os.path.join(os.path.dirname(__file__), "intake.db")

# YouTube downloads run on loki, then rsync directly to zikzak
LOKI_HOST      = os.environ.get("LOKI_HOST",       "loki")
LOKI_YT_DLP    = os.environ.get("LOKI_YT_DLP",     "/home/nthmost/.local/bin/yt-dlp")
LOKI_COOKIES   = os.environ.get("LOKI_COOKIES",    "/home/nthmost/yt-cookies.txt")

ZIKZAK_USER    = os.environ.get("ZIKZAK_USER",     "nthmost")
ZIKZAK_HOST    = os.environ.get("ZIKZAK_HOST",     "10.100.0.5")
ZIKZAK_JUMP    = os.environ.get("ZIKZAK_JUMP",     "zephyr")
ZIKZAK_MEDIA   = os.environ.get("ZIKZAK_MEDIA",    "/mnt/media")

# IA downloads still run locally (no throttling issue)
YT_DLP         = os.environ.get("YT_DLP",          "/usr/local/bin/yt-dlp")
YT_COOKIES     = os.environ.get("YT_COOKIES",      "")
INCOMING_DIR   = os.environ.get("INCOMING_DIR",    f"/mnt/media")  # fallback for IA
PORT = 8765

API_KEY = os.environ.get("INTAKE_API_KEY", "changeme")

CATEGORIES = [
    "british_surreal_comedy",
    "comic_memes",
    "cyberpunk_anime",
    "cyberpunk_memes",
    "darkwave_postpunk",
    "deep_techno",
    "fantasy_memes",
    "gaelic_resistance",
    "gaming_memes",
    "house_music",
    "interstitials",
    "joke_commercials",
    "joke_documentaries",
    "neon_synthpop",
    "philosophy",
    "philosophy_audio",
    "prelinger",
    "retro_anime",
    "retro_flash",
    "retro_mashups",
    "retro_sketch_comedy",
    "scifi_tv",
    "sketch_comedy",
    "surreal_talkshows",
    "vintage_talkshows",
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
