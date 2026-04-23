"""
Download logic for YouTube (via yt-dlp) and Internet Archive (via ia CLI).
"""

import json
import os
import re
import subprocess
import shutil
import time
import db
from config import (
    INCOMING_DIR, LOG_DIR,
    YT_DLP, YT_COOKIES,
    LOKI_HOST, LOKI_YT_DLP, LOKI_COOKIES,
    ZIKZAK_USER, ZIKZAK_HOST, ZIKZAK_JUMP, ZIKZAK_MEDIA,
    classify_length,
)


def _log_path(job_id):
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"job_{job_id}.log")


def resolve_youtube_oembed(url):
    """
    Return (title, None) using YouTube's oEmbed endpoint — instant, no API key.
    Duration is not available via oEmbed; returns None.
    """
    import urllib.request
    import urllib.parse
    api = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe="")
    with urllib.request.urlopen(api, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get("title", url), None


def _yt_cookies_args():
    if YT_COOKIES and os.path.exists(YT_COOKIES):
        return ["--cookies", YT_COOKIES]
    return []


def resolve_youtube_metadata(url):
    """
    Return (title, duration_seconds) for a single YouTube URL.
    Raises subprocess.CalledProcessError on failure.
    """
    result = subprocess.run(
        [YT_DLP, "--no-playlist", "--print", "%(title)s\t%(duration)s", *_yt_cookies_args(), url],
        capture_output=True, text=True, timeout=60,
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
        [YT_DLP, "--flat-playlist", "--print", "%(webpage_url)s\t%(title)s\t%(duration)s", *_yt_cookies_args(), url],
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


def resolve_youtube_rich_metadata(url):
    """
    Return a rich metadata dict for a single YouTube URL using yt-dlp --dump-json.
    Raises RuntimeError on failure.
    """
    result = subprocess.run(
        [YT_DLP, "--no-playlist", "--skip-download", "--dump-json", *_yt_cookies_args(), url],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300] or "yt-dlp failed")
    data = json.loads(result.stdout.strip().split("\n")[0])
    return {
        "title": data.get("title", ""),
        "duration_seconds": data.get("duration"),
        "description": (data.get("description") or "")[:500],
        "tags": data.get("tags") or [],
        "channel": data.get("channel") or data.get("uploader") or "",
        "uploader": data.get("uploader") or "",
    }


def resolve_ia_rich_metadata(identifier):
    """
    Return a rich metadata dict for an Internet Archive identifier.
    Never raises; returns partial data on error.
    """
    try:
        import internetarchive as ia_lib
        item = ia_lib.get_item(identifier)
        meta = item.metadata
        title = meta.get("title", identifier)
        description = meta.get("description", "")
        if isinstance(description, list):
            description = " ".join(description)
        subject = meta.get("subject", [])
        if isinstance(subject, str):
            subject = [subject]
        duration = None
        for f in item.files:
            if "length" in f:
                try:
                    duration = int(float(f["length"]))
                    break
                except (ValueError, TypeError):
                    pass
        return {
            "title": title,
            "duration_seconds": duration,
            "description": str(description)[:500],
            "tags": list(subject)[:10],
            "channel": meta.get("creator", ""),
            "uploader": meta.get("uploader", ""),
        }
    except Exception:
        return {
            "title": identifier,
            "duration_seconds": None,
            "description": "",
            "tags": [],
            "channel": "",
            "uploader": "",
        }


def parse_ia_identifier(url_or_id):
    """Extract IA identifier from a URL like archive.org/details/IDENTIFIER or bare identifier."""
    m = re.search(r"archive\.org/details/([^/?#]+)", url_or_id)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9_.\-]+$", url_or_id.strip()):
        return url_or_id.strip()
    return None


def _check_pipeline(job):
    """
    Check whether a completed job's file has landed on zikzak and entered a playlist.
    Called by the pipeline poller loop — no sleep, safe to retry.
    """
    job_id = job["id"]
    category = job["category"]
    length = job["length"]

    try:
        dest = f"{ZIKZAK_MEDIA}/{category}/{length}/"
        ls_result = subprocess.run(
            [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-J", ZIKZAK_JUMP,
                f"{ZIKZAK_USER}@{ZIKZAK_HOST}",
                f"ls {dest} 2>/dev/null",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if ls_result.returncode != 0 or not ls_result.stdout.strip():
            return  # not there yet — poller will retry

        db.mark_pipeline_status(job_id, "on_zikzak")

        playlist_result = subprocess.run(
            [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-J", ZIKZAK_JUMP,
                f"{ZIKZAK_USER}@{ZIKZAK_HOST}",
                f"grep -rl '{category}' /home/max/playlists/*.m3u 2>/dev/null | wc -l",
            ],
            capture_output=True, text=True, timeout=30,
        )
        count = playlist_result.stdout.strip()
        if playlist_result.returncode == 0 and count.isdigit() and int(count) > 0:
            db.mark_pipeline_status(job_id, "live")

    except Exception:
        pass  # will retry on next poll


def pipeline_poller_loop():
    """
    Runs forever in a background thread.
    Every 30s, checks all done jobs that haven't reached 'live' yet.
    Catches jobs missed by restarts or timing issues.
    """
    while True:
        time.sleep(30)
        try:
            for job in db.get_pipeline_pending():
                _check_pipeline(job)
        except Exception:
            pass


def run_job(job):
    """
    Execute a download job. Blocks until complete.
    YouTube jobs run on loki and rsync directly to zikzak.
    IA jobs run locally.
    """
    job_id = job["id"]
    log_path = _log_path(job_id)

    if job["source"] == "ia":
        dest_dir = os.path.join(INCOMING_DIR, job["category"], job["length"])
        os.makedirs(dest_dir, exist_ok=True)
        cmd = _build_ia_cmd(job["url"], dest_dir)
    else:
        cmd = _build_loki_yt_cmd(job["url"], job["category"], job["length"], job_id)

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
        error_msg = ""
        try:
            with open(log_path) as f:
                lines = [l.strip() for l in f if l.strip()]
                error_msg = lines[-1] if lines else ""
        except OSError:
            pass
        db.mark_failed(job_id, error_msg)


def _build_loki_yt_cmd(url, category, length, job_id):
    """
    SSH to loki, download via yt-dlp to a staging dir,
    rsync directly to zikzak:/mnt/media/CATEGORY/LENGTH/, then clean up.
    """
    staging = f"/tmp/intake_{job_id}"
    dest = f"{ZIKZAK_MEDIA}/{category}/{length}"
    ssh_to_zikzak = f"ssh -o StrictHostKeyChecking=no -J {ZIKZAK_JUMP}"
    script = (
        f"set -e && "
        f"mkdir -p {staging} && "
        f"{LOKI_YT_DLP} -f bestvideo+bestaudio/best --no-playlist "
        f"--restrict-filenames --cookies {LOKI_COOKIES} "
        f"-o '{staging}/%(title)s.%(ext)s' '{url}' && "
        f"ssh -o StrictHostKeyChecking=no -J {ZIKZAK_JUMP} "
        f"{ZIKZAK_USER}@{ZIKZAK_HOST} 'mkdir -p {dest}' && "
        f"rsync -av -e '{ssh_to_zikzak}' "
        f"{staging}/ {ZIKZAK_USER}@{ZIKZAK_HOST}:{dest}/ && "
        f"rm -rf {staging}"
    )
    return ["ssh", "-o", "StrictHostKeyChecking=no", LOKI_HOST, script]


def _build_ia_cmd(identifier, dest_dir):
    ia_bin = shutil.which("ia") or "ia"
    return [
        ia_bin, "download", identifier,
        "--glob=*.mp4", "--glob=*.avi", "--glob=*.mkv",
        "--no-directories",
        f"--destdir={dest_dir}",
        "--ignore-existing",
    ]
