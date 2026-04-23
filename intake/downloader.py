"""
Download logic for YouTube (via yt-dlp) and Internet Archive (via ia CLI).
"""

import os
import re
import subprocess
import shutil
import db
from config import INCOMING_DIR, LOG_DIR, YT_DLP, classify_length


def _log_path(job_id):
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"job_{job_id}.log")


def resolve_youtube_metadata(url):
    """
    Return (title, duration_seconds) for a single YouTube URL.
    Raises subprocess.CalledProcessError on failure.
    """
    result = subprocess.run(
        [YT_DLP, "--no-playlist", "--print", "%(title)s\t%(duration)s", url],
        capture_output=True, text=True, timeout=30,
    )
    line = result.stdout.strip().split("\n")[0]
    parts = line.split("\t")
    title = parts[0] if parts else url
    try:
        duration = int(parts[1]) if len(parts) > 1 else None
    except (ValueError, IndexError):
        duration = None
    return title, duration


def expand_youtube_playlist(url):
    """
    Return list of (url, title, duration_seconds) for each video in a playlist.
    """
    result = subprocess.run(
        [YT_DLP, "--flat-playlist", "--print", "%(webpage_url)s\t%(title)s\t%(duration)s", url],
        capture_output=True, text=True, timeout=60,
    )
    entries = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if not parts[0]:
            continue
        video_url = parts[0]
        title = parts[1] if len(parts) > 1 else video_url
        try:
            duration = int(parts[2]) if len(parts) > 2 else None
        except (ValueError, IndexError):
            duration = None
        entries.append((video_url, title, duration))
    return entries


def resolve_ia_metadata(identifier):
    """
    Return (title, duration_seconds) for an Internet Archive identifier.
    """
    try:
        import internetarchive as ia_lib
        item = ia_lib.get_item(identifier)
        meta = item.metadata
        title = meta.get("title", identifier)
        duration = None
        for f in item.files:
            if "length" in f:
                try:
                    duration = int(float(f["length"]))
                    break
                except (ValueError, TypeError):
                    pass
        return title, duration
    except Exception:
        return identifier, None


def parse_ia_identifier(url_or_id):
    """Extract IA identifier from a URL like archive.org/details/IDENTIFIER or bare identifier."""
    m = re.search(r"archive\.org/details/([^/?#]+)", url_or_id)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9_.\-]+$", url_or_id.strip()):
        return url_or_id.strip()
    return None


def run_job(job):
    """
    Execute a download job. Blocks until complete.
    Updates DB with pid, then marks done/failed.
    """
    job_id = job["id"]
    log_path = _log_path(job_id)
    dest_dir = os.path.join(INCOMING_DIR, job["category"], job["length"])
    os.makedirs(dest_dir, exist_ok=True)

    if job["source"] == "ia":
        cmd = _build_ia_cmd(job["url"], dest_dir)
    else:
        cmd = _build_yt_cmd(job["url"], dest_dir)

    with open(log_path, "w") as logfh:
        logfh.write(f"# Job {job_id}: {job['url']}\n")
        logfh.write(f"# cmd: {' '.join(cmd)}\n\n")
        logfh.flush()

        proc = subprocess.Popen(
            cmd, stdout=logfh, stderr=subprocess.STDOUT, text=True
        )
        db.set_pid(job_id, proc.pid, log_path)
        returncode = proc.wait()

    if returncode == 0:
        db.mark_done(job_id)
    else:
        # Grab last non-empty line from log as error summary
        error_msg = ""
        try:
            with open(log_path) as f:
                lines = [l.strip() for l in f if l.strip()]
                error_msg = lines[-1] if lines else ""
        except OSError:
            pass
        db.mark_failed(job_id, error_msg)


def _build_yt_cmd(url, dest_dir):
    output_template = os.path.join(dest_dir, "%(title)s.%(ext)s")
    return [
        YT_DLP,
        "-f", "bestvideo+bestaudio/best",
        "--no-playlist",
        "-o", output_template,
        url,
    ]


def _build_ia_cmd(identifier, dest_dir):
    ia_bin = shutil.which("ia") or "ia"
    return [
        ia_bin, "download", identifier,
        "--glob=*.mp4", "--glob=*.avi", "--glob=*.mkv",
        "--no-directories",
        f"--destdir={dest_dir}",
        "--ignore-existing",
    ]
