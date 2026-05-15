"""
Download logic for YouTube (via yt-dlp) and Internet Archive (via ia CLI).
"""

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

import db
from config import (
    INCOMING_DIR, LOG_DIR,
    YT_DLP, YT_COOKIES,
    LOKI_HOST, LOKI_YT_DLP, LOKI_COOKIES,
    ZIKZAK_USER, ZIKZAK_HOST, ZIKZAK_JUMP, ZIKZAK_MEDIA, ZIKZAK_DROPBOX,
    HW_ACCEL, VAAPI_DEVICE, TRANSCODE_DIR,
    classify_length,
)

# Optional dep — only used when source='ia'. Guard so importing this module
# never fails on a host that hasn't installed the archive.org library.
try:
    import internetarchive as ia_lib
except ImportError:  # pragma: no cover - exercised on hosts lacking the lib
    ia_lib = None

log = logging.getLogger(__name__)


def _log_path(job_id):
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"job_{job_id}.log")


def _transcode_cmd_parts(crop_sides=False):
    """
    Return (vf_filter, encoder_args) for the configured hardware accelerator.
    Supports NVENC (RTX 4080 on loki) and VAAPI (Intel iGPU).
    """
    if HW_ACCEL == "nvenc":
        # NVENC: software scale+pad, then hardware encode
        if crop_sides:
            vf = (
                "crop=in_w:in_w*9/16:0:(in_h-in_w*9/16)/2,"
                "scale=960:540:force_original_aspect_ratio=decrease,"
                "pad=960:540:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
            )
        else:
            vf = (
                "scale=960:540:force_original_aspect_ratio=decrease,"
                "pad=960:540:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
            )
        enc = "-c:v h264_nvenc -b:v 1200k -profile:v main -level 4.1"
        hw_init = ""  # no device init needed for NVENC
    else:
        # VAAPI: upload to GPU, scale on GPU, encode on GPU
        if crop_sides:
            vf = (
                "crop=in_w:in_w*9/16:0:(in_h-in_w*9/16)/2,"
                "scale=960:540:force_original_aspect_ratio=decrease,"
                "pad=960:540:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
                "format=nv12,hwupload"
            )
        else:
            vf = (
                "scale=960:540:force_original_aspect_ratio=decrease,"
                "pad=960:540:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
                "format=nv12,hwupload"
            )
        enc = "-c:v h264_vaapi -b:v 1200k -profile:v main -level 4.1"
        hw_init = f"-vaapi_device {VAAPI_DEVICE}"
    return vf, enc, hw_init


def resolve_youtube_oembed(url):
    """
    Return (title, None) using YouTube's oEmbed endpoint — instant, no API key.
    Duration is not available via oEmbed; returns None.
    """
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
    Returns (identifier, None) if the lib is unavailable or the lookup fails.
    """
    if ia_lib is None:
        return identifier, None
    try:
        item = ia_lib.get_item(identifier)
    except Exception:
        log.exception("ia_lib.get_item failed for %s", identifier)
        return identifier, None
    title = item.metadata.get("title", identifier)
    return title, _ia_first_length(item.files)


def _ia_first_length(files):
    """Pick the first parseable 'length' field from an IA item's files list."""
    for f in files:
        raw = f.get("length")
        if raw is None:
            continue
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            continue
    return None


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


def _empty_ia_metadata(identifier):
    """Default IA metadata shape when no useful data is available."""
    return {
        "title": identifier,
        "duration_seconds": None,
        "description": "",
        "tags": [],
        "channel": "",
        "uploader": "",
    }


def resolve_ia_rich_metadata(identifier):
    """
    Return a rich metadata dict for an Internet Archive identifier.
    Never raises; returns partial data on error.
    """
    if ia_lib is None:
        return _empty_ia_metadata(identifier)
    try:
        item = ia_lib.get_item(identifier)
    except Exception:
        log.exception("ia_lib.get_item failed for %s", identifier)
        return _empty_ia_metadata(identifier)

    meta = item.metadata
    description = meta.get("description", "")
    if isinstance(description, list):
        description = " ".join(description)
    subject = meta.get("subject", [])
    if isinstance(subject, str):
        subject = [subject]
    return {
        "title": meta.get("title", identifier),
        "duration_seconds": _ia_first_length(item.files),
        "description": str(description)[:500],
        "tags": list(subject)[:10],
        "channel": meta.get("creator", ""),
        "uploader": meta.get("uploader", ""),
    }


def parse_ia_identifier(url_or_id):
    """Extract IA identifier from a URL like archive.org/details/IDENTIFIER or bare identifier."""
    m = re.search(r"archive\.org/details/([^/?#]+)", url_or_id)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9_.\-]+$", url_or_id.strip()):
        return url_or_id.strip()
    return None


def _dropbox_paths(job_id, filename):
    """Return (incoming, rejected) absolute paths for a job's dropbox file."""
    return (
        f"{ZIKZAK_DROPBOX}/{job_id}__{filename}",
        f"{ZIKZAK_DROPBOX}/rejected/{job_id}__{filename}",
    )


def _probe_dropbox_state(job_id, filename):
    """
    SSH-probe a single file in the dropbox tree.
    Returns one of: 'pending' (still in dropbox), 'rejected' (in rejected/),
    'gone' (neither — watchdog filed it, presumed live).
    """
    incoming, rejected = _dropbox_paths(job_id, filename)
    check_cmd = (
        f"if [ -f {shlex.quote(incoming)} ]; then echo 'pending'; "
        f"elif [ -f {shlex.quote(rejected)} ]; then echo 'rejected'; "
        f"else echo 'gone'; fi"
    )
    _, stdout, _ = _ssh_zikzak(check_cmd, timeout=15)
    return stdout.strip()


def _file_landed_in_media(category, length, filename):
    """Return True if the named file exists under ZIKZAK_MEDIA/<cat>/<len>/."""
    media_path = f"{ZIKZAK_MEDIA}/{category}/{length}/{filename}"
    rc, out, _ = _ssh_zikzak(f"ls {shlex.quote(media_path)} 2>/dev/null", timeout=15)
    return rc == 0 and bool(out.strip())


def _check_pipeline(job):
    """
    Reconcile a completed job with watchdog reality and update its
    pipeline_status. Idempotent + crash-safe — called repeatedly by the
    poller; any exception is swallowed so the poller keeps running.

    State machine:
      live    -> already done; no-op
      pending -> file still in /mnt/dropbox/; wait for next tick
      rejected-> watchdog rejected; record it
      gone    -> watchdog filed it; verify in /mnt/media/ and mark live
    """
    try:
        current = db.get_job(job["id"])
    except Exception:
        log.exception("DB read failed in _check_pipeline for job %s", job["id"])
        return
    if not current or current.get("pipeline_status") == "live":
        return
    filename = current.get("filename", "")
    if not filename:
        return
    try:
        status = _probe_dropbox_state(current["id"], filename)
    except Exception:
        log.exception("dropbox probe failed for job %s", current["id"])
        return
    if status == "rejected":
        db.mark_pipeline_status(current["id"], "rejected")
    elif status == "gone" and _file_landed_in_media(
        current["category"], current["length"], filename
    ):
        db.mark_pipeline_status(current["id"], "live")
    # status == "pending": still waiting; poller retries on next tick.


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
            # Loop must not die — log and try again next tick.
            log.exception("pipeline_poller_loop iteration failed")


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


class _PurgeResult:
    """Accumulator for the deleted/errors/not_found buckets of a purge run."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.errors: list[str] = []
        self.not_found: list[str] = []

    def as_dict(self) -> dict:
        return {"deleted": self.deleted, "errors": self.errors, "not_found": self.not_found}


def _purge_remote_file(result: "_PurgeResult", path: str) -> None:
    """Delete a single file on zikzak; record outcome in `result`."""
    rc, _, err = _ssh_zikzak(f"rm -f {shlex.quote(path)}")
    if rc == 0:
        result.deleted.append(f"zikzak:{path}")
    else:
        result.errors.append(f"zikzak rm {path}: {err.strip()}")


def _purge_remote_glob(result: "_PurgeResult", directory: str, pattern: str) -> None:
    """Find files matching `pattern` in `directory` on zikzak; delete each."""
    find_cmd = f"find {shlex.quote(directory)} -maxdepth 1 -type f -name {shlex.quote(pattern)}"
    rc, stdout, _ = _ssh_zikzak(find_cmd)
    if rc != 0 or not stdout.strip():
        result.not_found.append(f"zikzak:{directory}/{pattern}")
        return
    for path in stdout.strip().splitlines():
        _purge_remote_file(result, path.strip())


def _purge_local_file(result: "_PurgeResult", path: str) -> None:
    """Delete a single local file; record outcome in `result`."""
    if not os.path.exists(path):
        result.not_found.append(f"local:{path}")
        return
    try:
        os.remove(path)
    except OSError as exc:
        result.errors.append(f"local rm {path}: {exc}")
        return
    result.deleted.append(f"local:{path}")


def _purge_local_by_title_glob(result: "_PurgeResult", directory: str, title_pat: str) -> None:
    """Scan `directory` and remove files whose names start with `title_pat`."""
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return  # dir missing is fine — nothing to do
    for entry in entries:
        if entry.is_file() and re.match(title_pat, entry.name):
            _purge_local_file(result, entry.path)


def _ia_local_dirs(category: str, length: str) -> tuple[str, str]:
    """Return (incoming_dir, transcoded_dir) on loki for an IA job."""
    incoming = os.path.join(INCOMING_DIR, category, length)
    transcoded = os.path.join(
        os.environ.get("TRANSCODED_DIR", "/mnt/media_transcoded"), category, length
    )
    return incoming, transcoded


def _purge_ia_job(result: "_PurgeResult", job: dict, remote_dir: str, glob_pat: str | None) -> None:
    """Purge IA-source files: raw on incoming + transcoded locally + zikzak."""
    filename = job.get("filename")
    incoming_dir, transcoded_dir = _ia_local_dirs(job["category"], job["length"])
    if filename:
        _purge_local_file(result, os.path.join(incoming_dir, filename))
        stem = os.path.splitext(filename)[0]
        _purge_local_file(result, os.path.join(transcoded_dir, stem + ".mp4"))
        if glob_pat:
            _purge_remote_glob(result, remote_dir, stem + ".mp4")
        return
    if not glob_pat:
        return
    title_pat = re.escape(_yt_restrict(job.get("title") or ""))
    for d in (incoming_dir, transcoded_dir):
        _purge_local_by_title_glob(result, d, title_pat)
    _purge_remote_glob(result, remote_dir, glob_pat)


def _purge_yt_job(result: "_PurgeResult", remote_dir: str, filename: str | None, glob_pat: str | None) -> None:
    """Purge a YouTube job's files (only live on zikzak; staging is gone)."""
    if filename:
        _purge_remote_file(result, f"{remote_dir}/{filename}")
    elif glob_pat:
        _purge_remote_glob(result, remote_dir, glob_pat)


def _purge_glob_for(job: dict) -> str | None:
    """If filename is known, glob is the filename; else derive from title."""
    if job.get("filename"):
        return job["filename"]
    stem = _yt_restrict(job.get("title") or "")
    return stem + ".*" if stem else None


def purge_job_files(job: dict) -> dict:
    """
    Delete all on-disk/remote files for a job. Liquidsoap's inotify watcher
    picks up the removal — no playlist regen needed.
    Returns {'deleted': [...], 'errors': [...], 'not_found': [...]}.
    """
    result = _PurgeResult()
    remote_dir = f"{ZIKZAK_MEDIA}/{job['category']}/{job['length']}"
    glob_pat = _purge_glob_for(job)
    if job["source"] == "ia":
        _purge_ia_job(result, job, remote_dir, glob_pat)
    else:
        _purge_yt_job(result, remote_dir, job.get("filename"), glob_pat)
    return result.as_dict()


def _build_job_command(job: dict, crop_sides: bool) -> list[str]:
    """Dispatch a job dict to the right pipeline-command builder."""
    if job["source"] == "ia":
        return _build_ia_pipeline_cmd(
            job["id"], job["url"], job["category"], job["length"], crop_sides=crop_sides
        )
    return _build_loki_yt_cmd(
        job["url"], job["category"], job["length"], job["id"], crop_sides=crop_sides
    )


def _spawn_job_subprocess(cmd: list[str], log_path: str, job: dict) -> int:
    """Run the job command, streaming output to log_path. Returns the exit code."""
    with open(log_path, "w") as logfh:
        logfh.write(f"# Job {job['id']}: {job['url']}\n")
        logfh.write(f"# cmd: {' '.join(cmd)}\n\n")
        logfh.flush()
        proc = subprocess.Popen(cmd, stdout=logfh, stderr=subprocess.STDOUT, text=True)
        db.set_pid(job["id"], proc.pid, log_path)
        return proc.wait()


def _canonical_filename_from_log(log_path: str) -> str | None:
    """Parse the run log for the output filename and normalize to <stem>.mp4."""
    raw = _parse_log_for_filename(log_path)
    if not raw:
        return None
    # The dropbox file is prefixed with job_id; strip that for the DB.
    m = re.match(r'^\d+__(.+)$', raw)
    if m:
        raw = m.group(1)
    return os.path.splitext(raw)[0] + ".mp4"


def _record_success(job_id: int, log_path: str) -> None:
    """Mark done; persist the resolved filename if we can extract one."""
    filename = _canonical_filename_from_log(log_path)
    if filename:
        db.set_filename(job_id, filename)
    db.mark_done(job_id)


def _last_log_line(log_path: str) -> str:
    """Return the last non-blank line of log_path, or '' if unreadable."""
    try:
        with open(log_path) as f:
            lines = [l.strip() for l in f if l.strip()]
    except OSError:
        return ""
    return lines[-1] if lines else ""


def _record_failure(job_id: int, log_path: str) -> None:
    """Mark failed with the last log line as the error message."""
    db.mark_failed(job_id, _last_log_line(log_path))


def run_job(job: dict) -> None:
    """
    Execute one download job, blocking until it completes.

    Pipeline (both sources):
      1. Download raw (yt-dlp on loki via SSH, or `ia` CLI locally on loki).
      2. Transcode to 960x540 H.264 — NVENC on RTX 4080 by default;
         VAAPI fallback via HW_ACCEL env var.
      3. rsync transcoded file to zikzak:/mnt/dropbox/<job_id>__<file>.mp4.
      4. Dropbox watchdog validates, files into /mnt/media/<cat>/<len>/, and
         sets pipeline_status='live' (or 'rejected') in mhbn.
    """
    log_path = _log_path(job["id"])
    cmd = _build_job_command(job, crop_sides=bool(job.get("crop_sides", 0)))
    returncode = _spawn_job_subprocess(cmd, log_path, job)
    if returncode == 0:
        _record_success(job["id"], log_path)
    else:
        _record_failure(job["id"], log_path)


# ─── Shell-snippet helpers (shared between YT and IA pipelines) ──────────────
#
# Each helper returns a fragment of bash. They take variable-name strings
# (e.g. "$_src", "$_out") rather than Python values because the surrounding
# script defines those vars at runtime via shell expansion.

def _ssh_to_zikzak_prefix() -> str:
    """SSH command prefix used for the zikzak push leg (jumphost-aware)."""
    return f"ssh -o StrictHostKeyChecking=no -J {ZIKZAK_JUMP}"


def _ffprobe_has_audio_bash(src_var: str) -> str:
    """Bash expression that's empty when `src_var` has no audio stream."""
    return (
        f"$(ffprobe -v error -select_streams a "
        f"-show_entries stream=codec_type -of csv=p=0 \"{src_var}\" 2>/dev/null | head -1)"
    )


def _ffmpeg_transcode_bash(
    hw_init: str, vf: str, enc: str,
    src_var: str, out_var: str, has_audio_var: str,
) -> str:
    """Bash if/else: ffmpeg with silent-audio fallback when src has no audio."""
    common = f"ffmpeg -hide_banner -loglevel error -nostdin -y {hw_init} -i \"{src_var}\""
    audio_pad = "-f lavfi -i anullsrc=r=44100:cl=stereo"
    map_silent = "-map 0:v -map 1:a -c:a aac -b:a 128k -ar 44100 -shortest"
    map_native = "-map 0:v -map 0:a -c:a aac -b:a 128k -ar 44100 -ac 2"
    tail = f"-movflags +faststart \"{out_var}\""
    return (
        f"if [ -z \"{has_audio_var}\" ]; then "
        f"{common} {audio_pad} -vf '{vf}' {enc} {map_silent} {tail}; "
        f"else "
        f"{common} -vf '{vf}' {enc} {map_native} {tail}; "
        f"fi"
    )


def _rsync_to_dropbox_bash(local_path_expr: str) -> str:
    """Bash chunk that ensures dropbox exists and rsyncs the local path into it."""
    ssh = _ssh_to_zikzak_prefix()
    return (
        f"{ssh} {ZIKZAK_USER}@{ZIKZAK_HOST} 'mkdir -p {ZIKZAK_DROPBOX}' && "
        f"rsync -av --no-group -e '{ssh}' "
        f"{local_path_expr} {ZIKZAK_USER}@{ZIKZAK_HOST}:{ZIKZAK_DROPBOX}/"
    )


# ─── Per-source pipeline command builders ────────────────────────────────────

def _yt_download_bash(url: str, staging: str) -> str:
    """yt-dlp invocation that puts a single video into `staging`."""
    return (
        f"{LOKI_YT_DLP} -f bestvideo+bestaudio/best --no-playlist "
        f"--restrict-filenames --cookies {LOKI_COOKIES} "
        f"--remote-components ejs:github "
        f"-o '{staging}/%(title)s.%(ext)s' '{url}'"
    )


def _yt_resolve_paths_bash(staging: str, transcoded: str, job_id: int) -> str:
    """Bash that sets _src/_base/_stem/_out/_has_audio for the downloaded file."""
    return (
        f"_src=$(find {staging} -maxdepth 1 -type f | head -1) && "
        f"_base=$(basename \"$_src\") && "
        f"_stem=${{_base%.*}} && "
        f"_out={transcoded}/{job_id}__${{_stem}}.mp4 && "
        f"_has_audio={_ffprobe_has_audio_bash('$_src')}"
    )


def _build_loki_yt_cmd(url: str, category: str, length: str, job_id: int,
                       crop_sides: bool = False) -> list[str]:
    """
    Build the SSH-to-loki command that downloads a YT video, transcodes to
    960x540 H.264, and pushes the result to zikzak's dropbox. The dropbox
    watchdog on zikzak files it into /mnt/media/<cat>/<len>/.

    Output filename is prefixed with the job_id so the watchdog can look
    up category/length from mhbn: <job_id>__<filename>.mp4
    """
    staging = f"/tmp/intake_{job_id}"
    transcoded = f"{staging}/transcoded"
    vf, enc, hw_init = _transcode_cmd_parts(crop_sides)
    script = " && ".join([
        "set -e",
        "export PATH=$PATH:$HOME/.deno/bin",
        f"mkdir -p {staging} {transcoded}",
        _yt_download_bash(url, staging),
        _yt_resolve_paths_bash(staging, transcoded, job_id),
        _ffmpeg_transcode_bash(hw_init, vf, enc, "$_src", "$_out", "$_has_audio"),
        "test -s \"$_out\"",
        _rsync_to_dropbox_bash("\"$_out\""),
        f"rm -rf {staging}",
    ])
    return ["ssh", "-o", "StrictHostKeyChecking=no", LOKI_HOST, script]


def _build_ia_cmd(identifier: str, dest_dir: str) -> list[str]:
    """Legacy: download IA files to a local directory (no transcode)."""
    ia_bin = shutil.which("ia") or "ia"
    return [
        ia_bin, "download", identifier,
        "--glob=*.mp4", "--glob=*.avi", "--glob=*.mkv",
        "--no-directories",
        f"--destdir={dest_dir}",
        "--ignore-existing",
    ]


def _ia_download_bash(identifier: str, raw_dir: str) -> str:
    """ia CLI invocation that downloads all video files into `raw_dir`."""
    ia_bin = shutil.which("ia") or "ia"
    return (
        f"{ia_bin} download {shlex.quote(identifier)} "
        f"--glob='*.mp4' --glob='*.avi' --glob='*.mkv' "
        f"--glob='*.ogv' --glob='*.webm' "
        f"--no-directories --destdir={raw_dir} --ignore-existing"
    )


def _ia_per_file_loop_bash(raw_dir: str, transcoded: str, job_id: int,
                           hw_init: str, vf: str, enc: str) -> str:
    """Bash for-loop: transcode each downloaded file into `transcoded`."""
    transcode = _ffmpeg_transcode_bash(hw_init, vf, enc, "$_src", "$_out", "$_has_audio")
    return (
        f"for _src in {raw_dir}/*; do "
        f"  [ -f \"$_src\" ] || continue; "
        f"  _base=$(basename \"$_src\"); "
        f"  _stem=\"${{_base%.*}}\"; "
        f"  _out=\"{transcoded}/{job_id}__${{_stem}}.mp4\"; "
        f"  _has_audio={_ffprobe_has_audio_bash('$_src')}; "
        f"  {transcode}; "
        f"  test -s \"$_out\" || {{ echo \"Transcode failed: $_base\"; exit 1; }}; "
        f"done"
    )


def _build_ia_pipeline_cmd(job_id: int, identifier: str, category: str, length: str,
                           crop_sides: bool = False) -> list[str]:
    """Full IA pipeline as a single bash -c script run locally on loki."""
    staging = f"/tmp/intake_{job_id}"
    raw_dir = f"{staging}/raw"
    transcoded = f"{staging}/transcoded"
    vf, enc, hw_init = _transcode_cmd_parts(crop_sides)
    script = " && ".join([
        "set -e",
        f"mkdir -p {raw_dir} {transcoded}",
        _ia_download_bash(identifier, raw_dir),
        _ia_per_file_loop_bash(raw_dir, transcoded, job_id, hw_init, vf, enc),
        _rsync_to_dropbox_bash(f"{transcoded}/"),
        f"rm -rf {staging}",
    ])
    return ["bash", "-c", script]
