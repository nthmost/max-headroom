"""
E2E fixtures. These tests drive the full intake pipeline:
    loki (this host) -> headroom:/mnt/dropbox -> dropbox-watchdog -> mhbn_test
They require:
  - MHBN_TEST_DATABASE_URL pointing at mhbn_test on loki
  - HEADROOM_HOST, HEADROOM_USER, HEADROOM_JUMP env vars matching the
    headroom test target (see ansible/playbooks/headroom.yml)
  - This host can `ssh -J <jump> <user>@<host>` headroom and run rm/find
  - ffmpeg + yt-dlp + ia CLI installed locally (i.e., we're on loki)

Each test runs a real job through the pipeline, then purges every artifact
it created — both in mhbn_test and on headroom's filesystems. If you Ctrl-C
mid-test, the next run's `clean_e2e_state` fixture will sweep up.
"""

import os
import subprocess
import time

import pytest


# ─── env-driven config ──────────────────────────────────────────────────────

HEADROOM_HOST = os.environ.get("HEADROOM_HOST", "10.100.0.4")
HEADROOM_USER = os.environ.get("HEADROOM_USER", "nthmost")
HEADROOM_JUMP = os.environ.get("HEADROOM_JUMP", "zephyr")
HEADROOM_DROPBOX = os.environ.get("HEADROOM_DROPBOX", "/mnt/dropbox")
HEADROOM_MEDIA = os.environ.get("HEADROOM_MEDIA", "/mnt/media")

# Knob for nightly runs: increase the wait if your link is slow.
PIPELINE_TIMEOUT_S = int(os.environ.get("E2E_PIPELINE_TIMEOUT", "600"))
PIPELINE_POLL_S = int(os.environ.get("E2E_PIPELINE_POLL", "10"))

# Known-safe IA identifier — small, public domain, always available.
TEST_IA_IDENTIFIER = os.environ.get("E2E_IA_IDENTIFIER", "Popeye_forPresident_512kb")

# Known-safe Creative Commons YouTube URL.
TEST_YT_URL = os.environ.get(
    "E2E_YT_URL", "https://www.youtube.com/watch?v=BHACKCNDMW8",  # Big Buck Bunny trailer
)

E2E_CATEGORY = "zzz_test"
E2E_LENGTH = "short"


pytestmark = pytest.mark.e2e


# ─── Guardrails ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _require_e2e_prereqs():
    """Hard-skip the suite if essentials are missing."""
    if not os.environ.get("MHBN_TEST_DATABASE_URL"):
        pytest.skip("MHBN_TEST_DATABASE_URL not set", allow_module_level=True)
    if HEADROOM_HOST == "10.100.0.4" and not _can_reach_headroom():
        pytest.skip(
            f"can't reach headroom ({HEADROOM_HOST}) via SSH jump {HEADROOM_JUMP}",
            allow_module_level=True,
        )


def _can_reach_headroom():
    """Quick SSH probe — true if we can run `true` on headroom."""
    try:
        rc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             "-J", HEADROOM_JUMP, f"{HEADROOM_USER}@{HEADROOM_HOST}", "true"],
            capture_output=True, timeout=10,
        ).returncode
        return rc == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ─── DB + ssh helpers ───────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def db_module():
    """Same trick as integration/conftest — point db at the test URL."""
    os.environ["DATABASE_URL"] = os.environ["MHBN_TEST_DATABASE_URL"]
    import db
    db.DATABASE_URL = os.environ["MHBN_TEST_DATABASE_URL"]
    return db


def _ssh_headroom(cmd, timeout=30):
    """Run a command on headroom via the configured jump. Returns CompletedProcess."""
    return subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no",
         "-J", HEADROOM_JUMP, f"{HEADROOM_USER}@{HEADROOM_HOST}", cmd],
        capture_output=True, text=True, timeout=timeout,
    )


# ─── Cleanup ────────────────────────────────────────────────────────────────

@pytest.fixture
def clean_e2e_state(db_module):
    """
    Around each test:
      - Drop every test-category row from jobs and media_files on mhbn_test.
      - Sweep headroom's dropbox + media/<test category>/<length>/ of any
        leftovers (broken previous runs).
    """
    def _purge():
        with db_module.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM media_files WHERE category = %s", (E2E_CATEGORY,)
                )
                cur.execute(
                    "DELETE FROM jobs WHERE category = %s OR url LIKE 'test://%%'",
                    (E2E_CATEGORY,),
                )
        # Sweep headroom: dropbox + rejected + the test category tree.
        _ssh_headroom(
            f"rm -f {HEADROOM_DROPBOX}/*__* "
            f"{HEADROOM_DROPBOX}/rejected/*__* 2>/dev/null; "
            f"rm -rf {HEADROOM_MEDIA}/{E2E_CATEGORY} 2>/dev/null",
            timeout=15,
        )
    _purge()
    yield
    _purge()


# ─── Pipeline-wait helper ──────────────────────────────────────────────────

def wait_for_pipeline_status(db_module, job_id, expected, timeout=PIPELINE_TIMEOUT_S):
    """
    Poll the DB until the job's pipeline_status matches `expected`, or raise.
    `expected` can be a string or a set of acceptable terminal states.
    """
    targets = {expected} if isinstance(expected, str) else set(expected)
    deadline = time.monotonic() + timeout
    last_seen = None
    while time.monotonic() < deadline:
        job = db_module.get_job(job_id)
        if job is None:
            raise AssertionError(f"job {job_id} disappeared from DB")
        last_seen = (job["status"], job.get("pipeline_status"))
        if job.get("pipeline_status") in targets:
            return job
        if job["status"] == "failed":
            raise AssertionError(f"job {job_id} failed: {job.get('error_msg')}")
        time.sleep(PIPELINE_POLL_S)
    raise AssertionError(
        f"timed out waiting for job {job_id} pipeline_status in {targets}; "
        f"last seen={last_seen}"
    )


# ─── Constants exposed to tests ────────────────────────────────────────────

@pytest.fixture(scope="session")
def e2e_const():
    return {
        "category": E2E_CATEGORY,
        "length": E2E_LENGTH,
        "ia_id": TEST_IA_IDENTIFIER,
        "yt_url": TEST_YT_URL,
        "headroom_host": HEADROOM_HOST,
        "headroom_user": HEADROOM_USER,
        "headroom_jump": HEADROOM_JUMP,
        "media_root": HEADROOM_MEDIA,
        "dropbox": HEADROOM_DROPBOX,
        "ssh": _ssh_headroom,
    }
