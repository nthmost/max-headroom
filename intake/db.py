import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def _row(cur):
    """Return one row as a dict, or None."""
    row = cur.fetchone()
    return dict(row) if row else None


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def init_db():
    """No-op: schema is managed via migrate_to_pg.py / manual DDL on zikzak."""
    pass


def add_user_category(name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO categories (name, is_builtin) VALUES (%s, FALSE) ON CONFLICT DO NOTHING",
                (name,),
            )


def get_user_categories():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT name FROM categories WHERE is_builtin = FALSE ORDER BY name ASC")
            return [r["name"] for r in cur.fetchall()]


def get_all_categories():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT name FROM categories WHERE is_tag_only = FALSE ORDER BY name ASC")
            return [r["name"] for r in cur.fetchall()]


def set_filename(job_id, filename):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET filename = %s, updated_at = NOW() WHERE id = %s",
                (filename, job_id),
            )


def delete_job(job_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))


def insert_job(url, title, source, category, length, crop_sides=False):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO jobs (url, title, source, category, length, status, crop_sides)
                   VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                   RETURNING id""",
                (url, title, source, category, length, bool(crop_sides)),
            )
            return cur.fetchone()[0]


def claim_next_pending():
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


def set_pid(job_id, pid, log_path):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET pid = %s, log_path = %s, updated_at = NOW() WHERE id = %s",
                (pid, log_path, job_id),
            )


def mark_done(job_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'done', pid = NULL, updated_at = NOW() WHERE id = %s",
                (job_id,),
            )


def mark_failed(job_id, error_msg=""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'failed', pid = NULL, error_msg = %s, updated_at = NOW() WHERE id = %s",
                (error_msg[:500], job_id),
            )


def mark_cancelled(job_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'cancelled', pid = NULL, updated_at = NOW() WHERE id = %s",
                (job_id,),
            )


def mark_pipeline_status(job_id, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET pipeline_status = %s, updated_at = NOW() WHERE id = %s",
                (status, job_id),
            )


def get_job(job_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            return _row(cur)


def get_queue():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM jobs WHERE status IN ('pending', 'running') ORDER BY id ASC"
            )
            return _rows(cur)


def get_pipeline_pending():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM jobs
                WHERE status = 'done' AND source != 'ia'
                AND (pipeline_status IS NULL OR pipeline_status = 'on_zikzak')
                ORDER BY id ASC
            """)
            return _rows(cur)


def get_tags_by_category(category=None):
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
            result = {}
            for row in cur.fetchall():
                key = (row["category"], row["subdir"] or "", row["filename"])
                result.setdefault(key, []).append(row["tag"])
            return result


def get_recent(limit=60):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM jobs WHERE status IN ('done', 'failed', 'cancelled')
                ORDER BY updated_at DESC LIMIT %s
            """, (limit,))
            return _rows(cur)
