import sqlite3
import datetime
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                url         TEXT NOT NULL,
                title       TEXT,
                source      TEXT NOT NULL,
                category    TEXT NOT NULL,
                length      TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                pid         INTEGER,
                log_path    TEXT,
                error_msg   TEXT,
                updated_at  TEXT NOT NULL,
                pipeline_status TEXT DEFAULT NULL
            )
        """)
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN pipeline_status TEXT DEFAULT NULL")
        except Exception:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_categories (
                name TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def add_user_category(name):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_categories (name, created_at) VALUES (?, ?)",
            (name, _now()),
        )
        conn.commit()


def get_user_categories():
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM user_categories ORDER BY name ASC").fetchall()
        return [r["name"] for r in rows]


def _now():
    return datetime.datetime.utcnow().isoformat()


def insert_job(url, title, source, category, length):
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO jobs (created_at, url, title, source, category, length, status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (now, url, title, source, category, length, now),
        )
        conn.commit()
        return cur.lastrowid


def claim_next_pending():
    """Atomically grab the next pending job and mark it running."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
        conn.commit()
        return dict(row)


def set_pid(job_id, pid, log_path):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET pid = ?, log_path = ?, updated_at = ? WHERE id = ?",
            (pid, log_path, _now(), job_id),
        )
        conn.commit()


def mark_done(job_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'done', pid = NULL, updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        conn.commit()


def mark_failed(job_id, error_msg=""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'failed', pid = NULL, error_msg = ?, updated_at = ? WHERE id = ?",
            (error_msg[:500], _now(), job_id),
        )
        conn.commit()


def mark_cancelled(job_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', pid = NULL, updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        conn.commit()


def mark_pipeline_status(job_id, status):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET pipeline_status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), job_id),
        )
        conn.commit()


def get_job(job_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def get_queue():
    """Return pending and running jobs ordered by id."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('pending', 'running') ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent(limit=60):
    """Return most recent completed/failed/cancelled jobs."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM jobs WHERE status IN ('done', 'failed', 'cancelled')
               ORDER BY updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
