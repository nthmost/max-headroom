"""
Download logic for YouTube (via yt-dlp) and Internet Archive (via ia CLI).
"""

import json
import os
import re
import shlex
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


def _yt_common_args():
    """Common yt-dlp args: cookies + JS challenge solver."""
    args = ["--remote-components", "ejs:github"]
    if YT_COOKIES and os.path.exists(YT_COOKIES):
        args += ["--cookies", YT_COOKIES]
    return args


def resolve_youtube_metadata(url):
    """
    Return (title, duration_seconds) for a single YouTube URL.
    Raises subprocess.CalledProcessError on failure.
    """
    result = subprocess.run(
        [YT_DLP, "--no-playlist", "--print", "%(title)s\t%(duration)s", *_yt_common_args(), url],
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
        [YT_DLP, "--flat-playlist", "--print", "%(webpage_url)s\t%(title)s\t%(duration)s", *_yt_common_args(), url],
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
        [YT_DLP, "--no-playlist", "--skip-download", "--dump-json", *_yt_common_args(), url],
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
        "width": data.get("width"),
        "height": data.get("height"),
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


def list_zikzak_media(category=None, length=None):
    """
    List media files from the postgres media_files table.
    Returns list of dicts: {category, length, filename, size, mtime}.
    """
    return db.list_media_files(category, length)


def probe_zikzak_file(category, length, filename):
    """
    Run ffprobe on a zikzak file. Returns dict or {} on failure.
    """
    path = f"{ZIKZAK_MEDIA}/{category}/{length}/{filename}"
    cmd = (
        f"ffprobe -v error "
        f"-show_entries stream=width,height,duration,codec_name,r_frame_rate "
        f"-show_entries format=duration,size,bit_rate "
        f"-of json {shlex.quote(path)} 2>/dev/null"
    )
    rc, stdout, _ = _ssh_zikzak(cmd, timeout=15)
    if not stdout.strip():
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


def delete_media_file(category, length, filename):
    """
    Delete a single file from zikzak and remove from DB.
    Liquidsoap uses inotify (reload_mode="watch") so no playlist regen needed.
    Raises RuntimeError on SSH failure.
    """
    path = f"{ZIKZAK_MEDIA}/{category}/{length}/{filename}"
    rc, _, err = _ssh_zikzak(f"rm -f {shlex.quote(path)}")
    if rc != 0:
        raise RuntimeError(err.strip() or "rm failed")
    db.remove_media_file(category, length, filename)


def move_media_file(from_cat, from_len, filename, to_cat, to_len):
    """
    Move a file to a different category/length on zikzak and update DB.
    Liquidsoap uses inotify (reload_mode="watch") so no playlist regen needed.
    Raises RuntimeError on SSH failure.
    """
    src = f"{ZIKZAK_MEDIA}/{from_cat}/{from_len}/{filename}"
    dst_dir = f"{ZIKZAK_MEDIA}/{to_cat}/{to_len}"
    dst = f"{dst_dir}/{filename}"
    cmd = f"mkdir -p {shlex.quote(dst_dir)} && mv {shlex.quote(src)} {shlex.quote(dst)}"
    rc, _, err = _ssh_zikzak(cmd)
    if rc != 0:
        raise RuntimeError(err.strip() or "mv failed")
    db.move_media_file_db(from_cat, from_len, filename, to_cat, to_len)


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


def _parse_log_for_filename(log_path):
    """
    Scan a yt-dlp or ia-cli log and return the downloaded filename (basename only).
    Priority: [Merger] line (final merged file) > last non-fragment [download] Destination line.
    """
    merger_name = None
    download_name = None
    try:
        with open(log_path) as f:
            for line in f:
                line = line.rstrip()
                # yt-dlp merge: [Merger] Merging formats into "/tmp/intake_N/FILENAME"
                m = re.search(r'\[(?:Merger|ffmpeg)\] Merging formats into ["\']?(.+?)["\']?\s*$', line)
                if m:
                    merger_name = os.path.basename(m.group(1).strip('"\''))
                    continue
                # yt-dlp single format: [download] Destination: /tmp/intake_N/FILENAME
                m = re.search(r'\[download\] Destination: (.+)$', line)
                if m:
                    candidate = os.path.basename(m.group(1).strip())
                    # skip fragment files like video.f137.webm
                    if not re.search(r'\.\w+\.\w+$', candidate):
                        download_name = candidate
                # ia cli: "identifier/filename" or "downloading: identifier/filename"
                m = re.search(r'(?:downloading:\s+)?\S+/([^\s/]+\.\w+)\s*$', line)
                if m and '/' in line:
                    download_name = m.group(1)
    except OSError:
        pass
    return merger_name or download_name


def _yt_restrict(title):
    """Approximate yt-dlp --restrict-filenames sanitisation for glob matching."""
    return re.sub(r'[^\w\-.]', '_', title)


def _ssh_zikzak(cmd_str, timeout=30):
    """Run a command on zikzak via jump host. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        [
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-J", ZIKZAK_JUMP,
            f"{ZIKZAK_USER}@{ZIKZAK_HOST}",
            cmd_str,
        ],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def purge_job_files(job):
    """
    Delete all on-disk/remote files for a job and regenerate zikzak playlists.
    Returns {'deleted': [...], 'errors': [...], 'not_found': [...]}.
    """
    deleted, errors, not_found = [], [], []
    category = job["category"]
    length = job["length"]
    filename = job.get("filename")

    # If we have an exact filename, use it; otherwise build a glob from the title.
    if filename:
        glob_pat = filename
    else:
        stem = _yt_restrict(job.get("title") or "")
        glob_pat = stem + ".*" if stem else None

    remote_dir = f"{ZIKZAK_MEDIA}/{category}/{length}"

    def _delete_remote(path):
        rc, _, err = _ssh_zikzak(f"rm -f {shlex.quote(path)}")
        if rc == 0:
            deleted.append(f"zikzak:{path}")
        else:
            errors.append(f"zikzak rm {path}: {err.strip()}")

    def _delete_remote_glob(directory, pattern):
        """Find files matching pattern in directory on zikzak, delete them."""
        find_cmd = f"find {shlex.quote(directory)} -maxdepth 1 -type f -name {shlex.quote(pattern)}"
        rc, stdout, _ = _ssh_zikzak(find_cmd)
        if rc != 0 or not stdout.strip():
            not_found.append(f"zikzak:{directory}/{pattern}")
            return
        for path in stdout.strip().splitlines():
            _delete_remote(path.strip())

    def _delete_local(path):
        try:
            if os.path.exists(path):
                os.remove(path)
                deleted.append(f"local:{path}")
            else:
                not_found.append(f"local:{path}")
        except OSError as e:
            errors.append(f"local rm {path}: {e}")

    if job["source"] == "ia":
        # IA: raw lives locally on loki at INCOMING_DIR (may also be in /mnt/incoming if
        # process-incoming.sh has not run yet), transcoded locally then rsynced to zikzak.
        incoming_dir = os.path.join(INCOMING_DIR, category, length)
        transcoded_dir = os.path.join(
            os.environ.get("TRANSCODED_DIR", "/mnt/media_transcoded"), category, length
        )

        if filename:
            _delete_local(os.path.join(incoming_dir, filename))
            stem = os.path.splitext(filename)[0]
            _delete_local(os.path.join(transcoded_dir, stem + ".mp4"))
            if glob_pat:
                _delete_remote_glob(remote_dir, stem + ".mp4")
        elif glob_pat:
            # Best-effort: glob in each local dir
            for d in [incoming_dir, transcoded_dir]:
                try:
                    for entry in os.scandir(d):
                        if entry.is_file() and re.match(
                            re.escape(_yt_restrict(job.get("title") or "")), entry.name
                        ):
                            _delete_local(entry.path)
                except OSError:
                    pass
            _delete_remote_glob(remote_dir, glob_pat)
    else:
        # YouTube: file lives only on zikzak (rsync'd from loki staging, now gone)
        if filename:
            _delete_remote(f"{remote_dir}/{filename}")
        elif glob_pat:
            _delete_remote_glob(remote_dir, glob_pat)

    # Regenerate playlists on zikzak regardless
    try:
        _ssh_zikzak("sudo -u max /home/max/bin/regenerate-playlists.sh", timeout=60)
        deleted.append("zikzak:playlists regenerated")
    except Exception as e:
        errors.append(f"playlist regen: {e}")

    return {"deleted": deleted, "errors": errors, "not_found": not_found}


def run_job(job):
    """
    Execute a download job. Blocks until complete.
    YouTube jobs run on loki and rsync directly to zikzak.
    IA jobs run locally.
    """
    job_id = job["id"]
    log_path = _log_path(job_id)

    crop_sides = bool(job.get("crop_sides", 0))

    if job["source"] == "ia":
        dest_dir = os.path.join(INCOMING_DIR, job["category"], job["length"])
        os.makedirs(dest_dir, exist_ok=True)
        if crop_sides:
            # Drop a marker file; process-incoming.sh will use crop filter for
            # files it finds in this category/length directory.
            open(os.path.join(dest_dir, ".crop"), "w").close()
        cmd = _build_ia_cmd(job["url"], dest_dir)
    else:
        cmd = _build_loki_yt_cmd(job["url"], job["category"], job["length"], job_id,
                                  crop_sides=crop_sides)

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
        filename = _parse_log_for_filename(log_path)
        if filename and crop_sides and job["source"] != "ia":
            # crop step renames to stem.mp4
            stem = os.path.splitext(filename)[0]
            filename = stem + ".mp4"
        if filename:
            db.set_filename(job_id, filename)
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


def _build_loki_yt_cmd(url, category, length, job_id, crop_sides=False):
    """
    SSH to loki, download via yt-dlp to a staging dir,
    rsync directly to zikzak:/mnt/media/CATEGORY/LENGTH/, then clean up.
    If crop_sides is True, runs an ffmpeg center-crop pass after download to
    strip pillarbox bars from square/near-square videos before rsyncing.
    """
    staging = f"/tmp/intake_{job_id}"
    dest = f"{ZIKZAK_MEDIA}/{category}/{length}"
    ssh_to_zikzak = f"ssh -o StrictHostKeyChecking=no -J {ZIKZAK_JUMP}"

    if crop_sides:
        # After download: find the file, crop to 16:9 center slice, replace it.
        # --restrict-filenames ensures no spaces. ${_f%.*} strips the extension.
        crop_step = (
            f" && _f=$(ls {staging}/ | head -1)"
            f" && ffmpeg -hide_banner -loglevel error -nostdin -y"
            f" -i {staging}/\"$_f\""
            f" -vf 'crop=in_w:in_w*9/16:0:(in_h-in_w*9/16)/2,scale=960:540'"
            f" -c:v libx264 -b:v 1200k -profile:v main"
            f" -c:a aac -b:a 128k -ar 44100 -ac 2"
            f" -movflags +faststart {staging}/_crop.mp4"
            f" && rm {staging}/\"$_f\""
            f" && mv {staging}/_crop.mp4 {staging}/\"${{_f%.*}}.mp4\""
        )
    else:
        crop_step = ""

    script = (
        f"set -e && "
        f"export PATH=$PATH:$HOME/.deno/bin && "
        f"mkdir -p {staging} && "
        f"{LOKI_YT_DLP} -f bestvideo+bestaudio/best --no-playlist "
        f"--restrict-filenames --cookies {LOKI_COOKIES} "
        f"--remote-components ejs:github "
        f"-o '{staging}/%(title)s.%(ext)s' '{url}'"
        f"{crop_step} && "
        f"ssh -o StrictHostKeyChecking=no -J {ZIKZAK_JUMP} "
        f"{ZIKZAK_USER}@{ZIKZAK_HOST} 'mkdir -p {dest}' && "
        f"set +e; rsync -av --no-group -e '{ssh_to_zikzak}' "
        f"{staging}/ {ZIKZAK_USER}@{ZIKZAK_HOST}:{dest}/; "
        f"_rc=$?; set -e; [ $_rc -eq 0 ] || [ $_rc -eq 23 ] || exit $_rc && "
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
