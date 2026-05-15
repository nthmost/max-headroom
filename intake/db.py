"""
Postgres data access layer for mhbn. All public functions return plain dicts
or lists of dicts so callers don't depend on psycopg2 types.
"""

import os
from typing import Any, Optional

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# A `jobs` row keyed by column name. Schema lives in migrate_to_pg.py / DDL.
Job = dict[str, Any]
# A `media_files` row as exposed by list_media_files (subdir renamed to length).
MediaRow = dict[str, Any]
# Map of (category, subdir, filename) -> [tag, ...].
TagMap = dict[tuple[str, str, str], list[str]]


def get_conn() -> psycopg2.extensions.connection:
    """Return a fresh psycopg2 connection. Callers must use as a context manager."""
    return psycopg2.connect(DATABASE_URL)


def _row(cur: psycopg2.extensions.cursor) -> Optional[Job]:
    """Return one row as a dict, or None."""
    row = cur.fetchone()
    return dict(row) if row else None


def _rows(cur: psycopg2.extensions.cursor) -> list[Job]:
    """Return all rows as a list of dicts."""
    return [dict(r) for r in cur.fetchall()]


def init_db() -> None:
    """No-op: schema is managed via migrate_to_pg.py / manual DDL on zikzak."""
    pass


def add_user_category(name: str) -> None:
    """Add a user-defined (non-builtin) category. Idempotent."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO categories (name, is_builtin) VALUES (%s, FALSE) ON CONFLICT DO NOTHING",
                (name,),
            )


def get_user_categories() -> list[str]:
    """Return the names of user-defined categories, alphabetically."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT name FROM categories WHERE is_builtin = FALSE ORDER BY name ASC")
            return [r["name"] for r in cur.fetchall()]


def get_all_categories() -> list[str]:
    """Return names of all real categories (excludes tag-only entries)."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT name FROM categories WHERE is_tag_only = FALSE ORDER BY name ASC")
            return [r["name"] for r in cur.fetchall()]


def get_all_tags() -> list[str]:
    """Return all tag names from the categories table, ordered by name."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT name FROM categories ORDER BY name ASC")
            return [r["name"] for r in cur.fetchall()]


def ensure_tags_exist(tag_names: list[str]) -> None:
    """Insert any tags that don't yet exist in the categories table."""
    if not tag_names:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            for tag in tag_names:
                cur.execute(
                    "INSERT INTO categories (name, is_builtin, is_tag_only) "
                    "VALUES (%s, FALSE, TRUE) ON CONFLICT DO NOTHING",
                    (tag,),
                )


def set_filename(job_id: int, filename: str) -> None:
    """Set the resolved on-disk filename for a job."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET filename = %s, updated_at = NOW() WHERE id = %s",
                (filename, job_id),
            )


def delete_job(job_id: int) -> None:
    """Hard-delete a job row by id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))


def insert_job(
    url: str,
    title: str,
    source: str,
    category: str,
    length: str,
    crop_sides: bool = False,
    tags: Optional[list[str]] = None,
) -> int:
    """Create a new pending job; return its id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO jobs (url, title, source, category, length, status, crop_sides, tags)
                   VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s)
                   RETURNING id""",
                (url, title, source, category, length, bool(crop_sides), tags or []),
            )
            return cur.fetchone()[0]


def claim_next_pending() -> Optional[Job]:
    """Atomically grab the next pending job and mark it running."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                UPDATE jobs SET status = 'running', updated_at = NOW()
                WHERE id = (
                    SELECT id FROM jobs WHERE status = 'pending' ORDER BY id ASC LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
            """)
            return _row(cur)


def set_pid(job_id: int, pid: int, log_path: str) -> None:
    """Record the OS pid + log path for a running job."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET pid = %s, log_path = %s, updated_at = NOW() WHERE id = %s",
                (pid, log_path, job_id),
            )


def mark_done(job_id: int) -> None:
    """Mark a job as 'done' and clear its pid."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'done', pid = NULL, updated_at = NOW() WHERE id = %s",
                (job_id,),
            )


def mark_failed(job_id: int, error_msg: str = "") -> None:
    """Mark a job as 'failed' with a truncated error message (500 char cap)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'failed', pid = NULL, error_msg = %s, updated_at = NOW() WHERE id = %s",
                (error_msg[:500], job_id),
            )


def mark_cancelled(job_id: int) -> None:
    """Mark a job as 'cancelled' and clear its pid."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'cancelled', pid = NULL, updated_at = NOW() WHERE id = %s",
                (job_id,),
            )


def mark_pipeline_status(job_id: int, status: str) -> None:
    """Set jobs.pipeline_status (typically 'live' or 'rejected' from the watchdog)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET pipeline_status = %s, updated_at = NOW() WHERE id = %s",
                (status, job_id),
            )


def get_job(job_id: int) -> Optional[Job]:
    """Return a single job by id, or None if not found."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            return _row(cur)


def get_queue() -> list[Job]:
    """Return all currently-pending and running jobs, oldest first."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM jobs WHERE status IN ('pending', 'running') ORDER BY id ASC"
            )
            return _rows(cur)


def get_pipeline_pending() -> list[Job]:
    """
    Return YouTube/playlist jobs whose downloader is done but the dropbox-watchdog
    on zikzak hasn't yet acknowledged (pipeline_status IS NULL).
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # pipeline_status starts NULL when a job completes; the
            # dropbox-watchdog on zikzak flips it to 'live' or 'rejected'.
            # ('on_zikzak' was a legacy intermediate state from the pre-
            # watchdog flow; verified zero rows in mhbn as of 2026-05-15.)
            cur.execute("""
                SELECT * FROM jobs
                WHERE status = 'done' AND source != 'ia'
                AND pipeline_status IS NULL
                ORDER BY id ASC
            """)
            return _rows(cur)


def get_tags_by_category(category: Optional[str] = None) -> TagMap:
    """Return a dict mapping (category, subdir, filename) -> [tag, ...] for non-primary tags."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if category:
                cur.execute("""
                    SELECT mf.category, mf.subdir, mf.filename, mfc.category_name AS tag
                    FROM media_file_categories mfc
                    JOIN media_files mf ON mf.id = mfc.media_file_id
                    WHERE mfc.is_primary = FALSE AND mf.category = %s
                    ORDER BY mf.id, mfc.category_name
                """, (category,))
            else:
                cur.execute("""
                    SELECT mf.category, mf.subdir, mf.filename, mfc.category_name AS tag
                    FROM media_file_categories mfc
                    JOIN media_files mf ON mf.id = mfc.media_file_id
                    WHERE mfc.is_primary = FALSE
                    ORDER BY mf.id, mfc.category_name
                """)
            result: TagMap = {}
            for row in cur.fetchall():
                key = (row["category"], row["subdir"] or "", row["filename"])
                result.setdefault(key, []).append(row["tag"])
            return result


def get_recent(limit: int = 60) -> list[Job]:
    """Return the most recently updated completed/failed/cancelled jobs."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM jobs WHERE status IN ('done', 'failed', 'cancelled')
                ORDER BY updated_at DESC LIMIT %s
            """, (limit,))
            return _rows(cur)


# ─── Media file registry ─────────────────────────────────────────────────────

def list_media_files(
    category: Optional[str] = None,
    length: Optional[str] = None,
) -> list[MediaRow]:
    """
    Query media_files table. Returns list of dicts: {category, length, filename, size, mtime}.
    'length' maps to the subdir column; 'size' to filesize_bytes; 'mtime' to ingest_date epoch.
    """
    base = (
        "SELECT category, subdir AS length, filename, "
        "COALESCE(filesize_bytes, 0) AS size, "
        "EXTRACT(EPOCH FROM ingest_date)::bigint AS mtime "
        "FROM media_files"
    )
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if category and length:
                cur.execute(base + " WHERE category=%s AND subdir=%s ORDER BY ingest_date DESC",
                            (category, length))
            elif category:
                cur.execute(base + " WHERE category=%s ORDER BY ingest_date DESC", (category,))
            else:
                cur.execute(base + " ORDER BY ingest_date DESC")
            return _rows(cur)


def upsert_media_file(
    category: str,
    length: str,
    filename: str,
    filesize_bytes: Optional[int] = None,
    duration_secs: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    bitrate_kbps: Optional[int] = None,
) -> None:
    """Insert or update a media_files row keyed on (category, subdir, filename)."""
    with get_conn() as conn:
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
            """, (category, length, filename, filesize_bytes,
                  duration_secs, width, height, bitrate_kbps))


def remove_media_file(category: str, length: str, filename: str) -> None:
    """Delete a media_files row keyed on (category, subdir, filename)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM media_files WHERE category=%s AND subdir=%s AND filename=%s",
                (category, length, filename),
            )


def move_media_file_db(
    category: str,
    length: str,
    filename: str,
    to_category: str,
    to_length: str,
) -> None:
    """Reparent a media_files row to a new (category, length) tuple."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE media_files SET category=%s, subdir=%s "
                "WHERE category=%s AND subdir=%s AND filename=%s",
                (to_category, to_length, category, length, filename),
            )
