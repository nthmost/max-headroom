#!/usr/bin/env python3
"""
dropbox-watchdog.py — Watches /mnt/dropbox/ for new media files,
validates them, files them into /mnt/media/<category>/<length>/,
and updates the PostgreSQL database.

Files must be named: <job_id>__<filename>.mp4
The job_id is used to look up category/length from the DB.

Files arriving WITHOUT a job_id prefix are treated as manual drops
and filed into /mnt/media/uncategorized/medium/.

Design:
  - Only accepts 960x540 H.264 MP4 files (already transcoded on loki)
  - Rejects non-conforming files → moves to /mnt/dropbox/rejected/
  - Updates jobs.pipeline_status and media_files table on success
  - Lightweight: no transcoding happens here
"""

import json
import logging
import os
import re
import subprocess
import sys
import time

import psycopg2
import psycopg2.extras

# ── Config ───────────────────────────────────────────────────────────────────

DROPBOX_DIR = os.environ.get("DROPBOX_DIR", "/mnt/dropbox")
REJECTED_DIR = os.path.join(DROPBOX_DIR, "rejected")
MEDIA_DIR = os.environ.get("MEDIA_DIR", "/mnt/media")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))  # seconds

# Expected specs for transcoded files
EXPECTED_WIDTH = 960
EXPECTED_HEIGHT = 540
EXPECTED_CODEC = "h264"

LOG_FORMAT = "%(asctime)s [watchdog] %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
log = logging.getLogger("watchdog")

# ── Database ─────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def lookup_job(conn, job_id):
    """Look up a job by ID. Returns dict or None."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def mark_job_live(conn, job_id, filename):
    """Mark a job as live and record the final filename."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET pipeline_status = 'live', filename = %s, "
            "updated_at = NOW() WHERE id = %s",
            (filename, job_id),
        )
    conn.commit()


def mark_job_rejected(conn, job_id, reason):
    """Mark a job as rejected in the pipeline."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET pipeline_status = 'rejected', "
            "error_msg = %s, updated_at = NOW() WHERE id = %s",
            (reason[:500], job_id),
        )
    conn.commit()


def upsert_media_file(conn, category, length, filename,
                      filesize_bytes=None, duration_secs=None,
                      width=None, height=None, bitrate_kbps=None):
    """Insert or update media_files entry. Returns the media_file id."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO media_files
                (category, subdir, filename, filesize_bytes,
                 duration_secs, width, height, bitrate_kbps, ingest_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (category, subdir, filename) DO UPDATE SET
                filesize_bytes = EXCLUDED.filesize_bytes,
                duration_secs  = EXCLUDED.duration_secs,
                width          = EXCLUDED.width,
                height         = EXCLUDED.height,
                bitrate_kbps   = EXCLUDED.bitrate_kbps,
                ingest_date    = NOW()
            RETURNING id
        """, (category, length, filename, filesize_bytes,
              duration_secs, width, height, bitrate_kbps))
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def apply_job_tags(conn, media_file_id, job):
    """Write job tags to media_file_categories (non-primary)."""
    tags = job.get("tags") or []
    if not tags or not media_file_id:
        return
    with conn.cursor() as cur:
        for tag in tags:
            # Ensure the tag exists in categories table
            cur.execute(
                "INSERT INTO categories (name, is_builtin, is_tag_only) "
                "VALUES (%s, FALSE, TRUE) ON CONFLICT DO NOTHING",
                (tag,),
            )
            cur.execute(
                "INSERT INTO media_file_categories (media_file_id, category_name, is_primary) "
                "VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING",
                (media_file_id, tag),
            )
    conn.commit()
    log.info("  Applied %d tag(s): %s", len(tags), ", ".join(tags))

# ── File validation ──────────────────────────────────────────────────────────

def ffprobe_file(filepath):
    """
    Run ffprobe on a file. Returns dict with video stream info,
    or None on failure.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=codec_name,width,height,duration,bit_rate",
                "-show_entries", "format=duration,size,bit_rate",
                "-of", "json",
                filepath,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception as e:
        log.error("ffprobe failed for %s: %s", filepath, e)
        return None


def validate_file(filepath):
    """
    Validate a file is a correctly transcoded 960x540 H.264 MP4.
    Returns (ok, info_dict, error_message).
    """
    if not filepath.endswith(".mp4"):
        return False, {}, f"not an MP4 file: {os.path.basename(filepath)}"

    probe = ffprobe_file(filepath)
    if not probe:
        return False, {}, "ffprobe failed — file may be corrupt"

    streams = probe.get("streams", [])
    if not streams:
        return False, {}, "no video stream found"

    vs = streams[0]
    codec = vs.get("codec_name", "")
    width = vs.get("width", 0)
    height = vs.get("height", 0)

    # Extract metadata for DB
    fmt = probe.get("format", {})
    duration = None
    try:
        duration = float(fmt.get("duration") or vs.get("duration") or 0)
    except (ValueError, TypeError):
        pass
    bitrate = None
    try:
        bitrate = int(fmt.get("bit_rate", 0)) // 1000
    except (ValueError, TypeError):
        pass
    filesize = None
    try:
        filesize = int(fmt.get("size", 0))
    except (ValueError, TypeError):
        filesize = os.path.getsize(filepath)

    info = {
        "codec": codec,
        "width": width,
        "height": height,
        "duration_secs": duration,
        "bitrate_kbps": bitrate,
        "filesize_bytes": filesize,
    }

    if codec != EXPECTED_CODEC:
        return False, info, f"wrong codec: {codec} (expected {EXPECTED_CODEC})"
    if width != EXPECTED_WIDTH or height != EXPECTED_HEIGHT:
        return False, info, f"wrong resolution: {width}x{height} (expected {EXPECTED_WIDTH}x{EXPECTED_HEIGHT})"

    return True, info, ""


# ── Filename parsing ─────────────────────────────────────────────────────────

# Expected format: <job_id>__<original_filename>.mp4
# Examples: 42__Cool_Video.mp4, 123__My_Song.mp4
JOB_PREFIX_RE = re.compile(r"^(\d+)__(.+)$")


def parse_dropbox_filename(basename):
    """
    Parse a dropbox filename into (job_id, clean_filename).
    Returns (None, basename) if no job_id prefix.
    """
    m = JOB_PREFIX_RE.match(basename)
    if m:
        return int(m.group(1)), m.group(2)
    return None, basename


# ── File stability check ─────────────────────────────────────────────────────

def is_file_stable(filepath, settle_secs=3):
    """
    Check that a file hasn't been modified in the last settle_secs seconds.
    This ensures rsync/scp has finished writing.
    """
    try:
        mtime = os.path.getmtime(filepath)
        return (time.time() - mtime) >= settle_secs
    except OSError:
        return False


# ── Main processing ──────────────────────────────────────────────────────────

def process_file(filepath):
    """
    Process a single file from the dropbox.
    Returns True if handled (success or rejection), False to retry later.
    """
    basename = os.path.basename(filepath)

    if not is_file_stable(filepath):
        return False  # still being written, retry later

    log.info("Processing: %s", basename)

    # Parse filename for job_id
    job_id, clean_filename = parse_dropbox_filename(basename)

    # Look up job in DB
    category = "uncategorized"
    length = "medium"
    conn = None

    try:
        conn = get_conn()

        if job_id:
            job = lookup_job(conn, job_id)
            if job:
                category = job["category"]
                length = job["length"]
                log.info("  Job %d: category=%s length=%s", job_id, category, length)
            else:
                log.warning("  Job %d not found in DB, using uncategorized/medium", job_id)
        else:
            log.info("  No job_id prefix, filing as uncategorized/medium")

        # Validate the file
        ok, info, error = validate_file(filepath)

        if not ok:
            log.error("  REJECTED: %s", error)
            os.makedirs(REJECTED_DIR, exist_ok=True)
            rejected_path = os.path.join(REJECTED_DIR, basename)
            os.rename(filepath, rejected_path)
            if job_id and conn:
                mark_job_rejected(conn, job_id, error)
            return True

        # File is valid — move to media directory
        dest_dir = os.path.join(MEDIA_DIR, category, length)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, clean_filename)

        # Handle name collisions
        if os.path.exists(dest_path):
            stem, ext = os.path.splitext(clean_filename)
            dest_path = os.path.join(dest_dir, f"{stem}_{int(time.time())}{ext}")
            clean_filename = os.path.basename(dest_path)
            log.info("  Name collision, renamed to: %s", clean_filename)

        os.rename(filepath, dest_path)
        log.info("  Filed: %s/%s/%s (%s, %.1fs)",
                 category, length, clean_filename,
                 f"{info.get('filesize_bytes', 0) / 1048576:.1f}MB",
                 info.get("duration_secs") or 0)

        # Update DB
        media_file_id = upsert_media_file(
            conn, category, length, clean_filename,
            filesize_bytes=info.get("filesize_bytes"),
            duration_secs=info.get("duration_secs"),
            width=info.get("width"),
            height=info.get("height"),
            bitrate_kbps=info.get("bitrate_kbps"),
        )

        if job_id:
            if job and media_file_id:
                apply_job_tags(conn, media_file_id, job)
            mark_job_live(conn, job_id, clean_filename)

        return True

    except Exception as e:
        log.error("  Error processing %s: %s", basename, e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def scan_dropbox():
    """Scan the dropbox directory for new files and process them."""
    try:
        entries = os.listdir(DROPBOX_DIR)
    except OSError as e:
        log.error("Cannot read dropbox directory %s: %s", DROPBOX_DIR, e)
        return

    for entry in sorted(entries):
        filepath = os.path.join(DROPBOX_DIR, entry)

        # Skip directories (like rejected/)
        if not os.path.isfile(filepath):
            continue

        # Skip hidden files and temp files
        if entry.startswith(".") or entry.endswith(".tmp") or entry.endswith(".part"):
            continue

        process_file(filepath)


def main():
    log.info("Dropbox watchdog starting")
    log.info("  Dropbox:  %s", DROPBOX_DIR)
    log.info("  Media:    %s", MEDIA_DIR)
    log.info("  Rejected: %s", REJECTED_DIR)
    log.info("  Poll:     %ds", POLL_INTERVAL)

    # Ensure directories exist
    os.makedirs(DROPBOX_DIR, exist_ok=True)
    os.makedirs(REJECTED_DIR, exist_ok=True)

    # Try DB connection on startup
    try:
        conn = get_conn()
        conn.close()
        log.info("  DB: connected OK")
    except Exception as e:
        log.error("  DB: connection failed: %s", e)
        log.error("  Watchdog will still file unknown drops as uncategorized/medium")

    # Main loop: poll-based (simpler and more reliable than inotify for
    # files arriving via rsync, which does rename-into-place)
    while True:
        scan_dropbox()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
