"""
Integration tests for db.py against a real postgres (mhbn_test).

These exercise the full SQL — sequences, ON CONFLICT, FOR UPDATE SKIP LOCKED —
which unit tests can't cover meaningfully. They write through to the test DB
and clean up after themselves; the suite skips entirely when
MHBN_TEST_DATABASE_URL isn't set.
"""

import pytest

pytestmark = pytest.mark.integration


# ─── Categories + tags ──────────────────────────────────────────────────────

def test_add_user_category_idempotent(db_module, clean_test_categories):
    db_module.add_user_category("zzz_test_cat")
    db_module.add_user_category("zzz_test_cat")  # no exception on dup
    cats = db_module.get_user_categories()
    assert cats.count("zzz_test_cat") == 1


def test_ensure_tags_exist_inserts_and_dedupes(db_module, clean_test_categories):
    db_module.ensure_tags_exist(["zzz_test_tagA", "zzz_test_tagB"])
    db_module.ensure_tags_exist(["zzz_test_tagA"])  # re-run, no error
    all_tags = db_module.get_all_tags()
    assert "zzz_test_tagA" in all_tags
    assert "zzz_test_tagB" in all_tags


def test_ensure_tags_exist_with_empty_list_is_noop(db_module):
    # Should not raise, should not open a transaction unnecessarily.
    db_module.ensure_tags_exist([])
    db_module.ensure_tags_exist(None)


# ─── Job lifecycle ─────────────────────────────────────────────────────────

def test_insert_and_get_job(db_module, clean_jobs):
    job_id = db_module.insert_job(
        "test://example", "Test Title", "youtube", "zzz_test", "short",
        crop_sides=False, tags=["zzz_test_tag"],
    )
    assert isinstance(job_id, int) and job_id > 0
    job = db_module.get_job(job_id)
    assert job["url"] == "test://example"
    assert job["title"] == "Test Title"
    assert job["status"] == "pending"
    assert job["category"] == "zzz_test"
    assert job["length"] == "short"
    assert job["crop_sides"] is False


def test_claim_next_pending_returns_oldest_first(db_module, clean_jobs):
    j1 = db_module.insert_job("test://a", "A", "youtube", "zzz_test", "short")
    j2 = db_module.insert_job("test://b", "B", "youtube", "zzz_test", "short")
    claimed = db_module.claim_next_pending()
    assert claimed["id"] == j1
    assert claimed["status"] == "running"
    next_claimed = db_module.claim_next_pending()
    assert next_claimed["id"] == j2


def test_claim_next_pending_returns_none_when_empty(db_module, clean_jobs):
    assert db_module.claim_next_pending() is None


def test_mark_done_clears_pid(db_module, clean_jobs):
    job_id = db_module.insert_job("test://done", "X", "youtube", "zzz_test", "short")
    db_module.set_pid(job_id, 12345, "/tmp/x.log")
    db_module.mark_done(job_id)
    job = db_module.get_job(job_id)
    assert job["status"] == "done"
    assert job["pid"] is None


def test_mark_failed_truncates_long_error(db_module, clean_jobs):
    job_id = db_module.insert_job("test://fail", "X", "youtube", "zzz_test", "short")
    db_module.mark_failed(job_id, "x" * 1000)
    job = db_module.get_job(job_id)
    assert job["status"] == "failed"
    assert len(job["error_msg"]) == 500


def test_set_filename_updates(db_module, clean_jobs):
    job_id = db_module.insert_job("test://fn", "X", "youtube", "zzz_test", "short")
    db_module.set_filename(job_id, "Resolved_Name.mp4")
    assert db_module.get_job(job_id)["filename"] == "Resolved_Name.mp4"


def test_mark_pipeline_status_round_trip(db_module, clean_jobs):
    job_id = db_module.insert_job("test://p", "X", "youtube", "zzz_test", "short")
    db_module.mark_done(job_id)
    assert db_module.get_job(job_id).get("pipeline_status") is None
    db_module.mark_pipeline_status(job_id, "live")
    assert db_module.get_job(job_id)["pipeline_status"] == "live"


def test_mark_cancelled(db_module, clean_jobs):
    job_id = db_module.insert_job("test://c", "X", "youtube", "zzz_test", "short")
    db_module.mark_cancelled(job_id)
    assert db_module.get_job(job_id)["status"] == "cancelled"


def test_delete_job(db_module, clean_jobs):
    job_id = db_module.insert_job("test://d", "X", "youtube", "zzz_test", "short")
    db_module.delete_job(job_id)
    assert db_module.get_job(job_id) is None


# ─── Queue + pipeline-pending views ─────────────────────────────────────────

def test_get_queue_returns_pending_and_running_only(db_module, clean_jobs):
    db_module.insert_job("test://q1", "A", "youtube", "zzz_test", "short")
    done_id = db_module.insert_job("test://q2", "B", "youtube", "zzz_test", "short")
    db_module.mark_done(done_id)
    queued_test = [j for j in db_module.get_queue() if j["category"] == "zzz_test"]
    statuses = {j["status"] for j in queued_test}
    assert statuses.issubset({"pending", "running"})
    assert "done" not in statuses


def test_get_pipeline_pending_excludes_ia(db_module, clean_jobs):
    yt_id = db_module.insert_job("test://yt", "Y", "youtube", "zzz_test", "short")
    ia_id = db_module.insert_job("test://ia", "I", "ia", "zzz_test", "short")
    db_module.mark_done(yt_id)
    db_module.mark_done(ia_id)
    pending_ids = {j["id"] for j in db_module.get_pipeline_pending()}
    assert yt_id in pending_ids
    assert ia_id not in pending_ids


def test_get_pipeline_pending_excludes_already_live(db_module, clean_jobs):
    jid = db_module.insert_job("test://live", "X", "youtube", "zzz_test", "short")
    db_module.mark_done(jid)
    db_module.mark_pipeline_status(jid, "live")
    pending_ids = {j["id"] for j in db_module.get_pipeline_pending()}
    assert jid not in pending_ids


def test_get_recent_orders_by_updated_at_desc(db_module, clean_jobs):
    j1 = db_module.insert_job("test://r1", "A", "youtube", "zzz_test", "short")
    j2 = db_module.insert_job("test://r2", "B", "youtube", "zzz_test", "short")
    db_module.mark_done(j1)
    db_module.mark_done(j2)  # newer update
    recent = [j for j in db_module.get_recent(limit=20) if j["category"] == "zzz_test"]
    assert recent[0]["id"] == j2
    assert recent[1]["id"] == j1


# ─── Media files (upsert + remove + move) ──────────────────────────────────

def test_upsert_media_file_inserts_then_updates(db_module):
    # Use a unique-enough filename so we don't collide with real data.
    cat, leng, fname = "zzz_test", "short", "test_upsert_video.mp4"
    db_module.upsert_media_file(cat, leng, fname, filesize_bytes=100)
    rows = [r for r in db_module.list_media_files(cat, leng) if r["filename"] == fname]
    assert len(rows) == 1
    assert rows[0]["size"] == 100
    # Second call updates the same row, not a new insert.
    db_module.upsert_media_file(cat, leng, fname, filesize_bytes=500)
    rows = [r for r in db_module.list_media_files(cat, leng) if r["filename"] == fname]
    assert len(rows) == 1
    assert rows[0]["size"] == 500
    db_module.remove_media_file(cat, leng, fname)


def test_move_media_file_db_reparents(db_module):
    cat, leng, fname = "zzz_test", "short", "test_move_video.mp4"
    db_module.upsert_media_file(cat, leng, fname, filesize_bytes=1)
    db_module.move_media_file_db(cat, leng, fname, "zzz_test", "medium")
    rows_short = [r for r in db_module.list_media_files(cat, "short") if r["filename"] == fname]
    rows_medium = [r for r in db_module.list_media_files(cat, "medium") if r["filename"] == fname]
    assert rows_short == []
    assert len(rows_medium) == 1
    db_module.remove_media_file(cat, "medium", fname)


def test_remove_media_file_is_noop_when_missing(db_module):
    # Should not raise even though the row doesn't exist.
    db_module.remove_media_file("zzz_test", "short", "does_not_exist.mp4")
