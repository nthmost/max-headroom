"""
E2E: IA identifier → loki transcode → headroom dropbox → watchdog → mhbn_test.
"""

import os
import pytest

import downloader  # imported for the helpers; we drive it directly here

# Make pytest skip these for `pytest tests/unit` runs by default.
pytestmark = pytest.mark.e2e


def test_ia_full_pipeline(db_module, clean_e2e_state, e2e_const):
    """Submit a known IA identifier; verify the file lands and DB flips to live."""
    # Override the push target by setting env that downloader.* read from config.py.
    # config.py reads at import time, so we monkey-patch the module globals instead.
    downloader.ZIKZAK_HOST = e2e_const["headroom_host"]
    downloader.ZIKZAK_USER = e2e_const["headroom_user"]
    downloader.ZIKZAK_JUMP = e2e_const["headroom_jump"]
    downloader.ZIKZAK_DROPBOX = e2e_const["dropbox"]
    downloader.ZIKZAK_MEDIA = e2e_const["media_root"]

    job_id = db_module.insert_job(
        e2e_const["ia_id"], f"E2E IA {e2e_const['ia_id']}",
        "ia", e2e_const["category"], e2e_const["length"],
    )

    # Drive the pipeline synchronously (same as the worker_loop would).
    downloader.run_job(db_module.get_job(job_id))

    from tests.e2e.conftest import wait_for_pipeline_status
    job = wait_for_pipeline_status(db_module, job_id, "live")

    # The watchdog should have filed the transcoded file under
    # headroom:/mnt/media/<category>/<length>/<filename>
    filename = job["filename"]
    assert filename, "watchdog never wrote a filename onto the job"
    media_path = f"{e2e_const['media_root']}/{e2e_const['category']}/{e2e_const['length']}/{filename}"
    res = e2e_const["ssh"](f"test -s {media_path} && echo present")
    assert "present" in res.stdout, f"expected {media_path} on headroom; stdout={res.stdout!r}"


def test_ia_invalid_identifier_marks_failed(db_module, clean_e2e_state, e2e_const):
    """A bogus IA identifier should fail the job, not hang the pipeline."""
    downloader.ZIKZAK_HOST = e2e_const["headroom_host"]
    downloader.ZIKZAK_USER = e2e_const["headroom_user"]
    downloader.ZIKZAK_JUMP = e2e_const["headroom_jump"]
    downloader.ZIKZAK_DROPBOX = e2e_const["dropbox"]

    bogus = "this_identifier_definitely_does_not_exist_xyzzy"
    job_id = db_module.insert_job(
        bogus, "E2E bogus", "ia", e2e_const["category"], e2e_const["length"],
    )
    downloader.run_job(db_module.get_job(job_id))
    job = db_module.get_job(job_id)
    assert job["status"] == "failed", \
        f"expected failed status for bogus IA id; got {job['status']}"
