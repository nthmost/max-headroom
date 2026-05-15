"""
E2E: YouTube URL → loki yt-dlp + transcode → headroom dropbox → watchdog → mhbn_test.
"""

import pytest

import downloader

pytestmark = pytest.mark.e2e


def test_youtube_full_pipeline(db_module, clean_e2e_state, e2e_const):
    """Submit a known CC YouTube URL; verify the file lands and DB flips to live."""
    downloader.ZIKZAK_HOST = e2e_const["headroom_host"]
    downloader.ZIKZAK_USER = e2e_const["headroom_user"]
    downloader.ZIKZAK_JUMP = e2e_const["headroom_jump"]
    downloader.ZIKZAK_DROPBOX = e2e_const["dropbox"]
    downloader.ZIKZAK_MEDIA = e2e_const["media_root"]

    job_id = db_module.insert_job(
        e2e_const["yt_url"], "E2E YouTube test",
        "youtube", e2e_const["category"], e2e_const["length"],
    )

    downloader.run_job(db_module.get_job(job_id))

    from tests.e2e.conftest import wait_for_pipeline_status
    job = wait_for_pipeline_status(db_module, job_id, "live")

    filename = job["filename"]
    assert filename, "watchdog never wrote a filename onto the job"
    media_path = f"{e2e_const['media_root']}/{e2e_const['category']}/{e2e_const['length']}/{filename}"
    res = e2e_const["ssh"](f"test -s {media_path} && echo present")
    assert "present" in res.stdout, f"expected {media_path} on headroom; stdout={res.stdout!r}"


def test_youtube_invalid_url_marks_failed(db_module, clean_e2e_state, e2e_const):
    """A bogus YouTube URL should fail cleanly without hanging the pipeline."""
    downloader.ZIKZAK_HOST = e2e_const["headroom_host"]
    downloader.ZIKZAK_USER = e2e_const["headroom_user"]
    downloader.ZIKZAK_JUMP = e2e_const["headroom_jump"]
    downloader.ZIKZAK_DROPBOX = e2e_const["dropbox"]

    bogus = "https://www.youtube.com/watch?v=THIS_DEFINITELY_DOES_NOT_EXIST"
    job_id = db_module.insert_job(
        bogus, "E2E bogus YT", "youtube", e2e_const["category"], e2e_const["length"],
    )
    downloader.run_job(db_module.get_job(job_id))
    job = db_module.get_job(job_id)
    assert job["status"] == "failed", \
        f"expected failed status for bogus YT URL; got {job['status']}"
