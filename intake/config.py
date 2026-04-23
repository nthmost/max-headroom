import os

INCOMING_DIR = "/mnt/incoming"
LOG_DIR = "/var/log/transcode/intake"
DB_PATH = os.path.join(os.path.dirname(__file__), "intake.db")
YT_DLP = os.environ.get("YT_DLP", "/usr/local/bin/yt-dlp")
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
