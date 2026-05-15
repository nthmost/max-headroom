#!/usr/bin/env python3
"""
intake.py — Media Intake Web App for Max Headroom Broadcast Network
Accepts YouTube URLs, Internet Archive identifiers, and playlist files.
Queues downloads into /mnt/incoming/ for the existing cron pipeline.
"""

import logging
import os
import posixpath
import re
import threading
import time

from flask import Flask, request, jsonify, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

import db
import downloader
import analyzer
from config import LENGTHS, PORT, classify_length

log = logging.getLogger(__name__)

# BASE_PATH allows the app to run behind a reverse proxy at a sub-path.
# Set via env var: BASE_PATH=/media
# Must NOT have a trailing slash.
BASE_PATH = os.environ.get("BASE_PATH", "").rstrip("/")

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# ─── Worker thread ──────────────────────────────────────────────────────────

_current_proc_lock = threading.Lock()

def worker_loop():
    while True:
        job = db.claim_next_pending()
        if job is None:
            time.sleep(2)
            continue
        try:
            downloader.run_job(job)
        except Exception as exc:
            db.mark_failed(job["id"], str(exc))


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", categories=db.get_all_categories(), lengths=LENGTHS, base_path=BASE_PATH)


@app.route("/api/categories")
def api_categories():
    return jsonify(db.get_all_categories())


@app.route("/api/tags")
def api_tags():
    return jsonify(db.get_all_tags())


@app.route("/api/quickmeta", methods=["POST"])
def api_quickmeta():
    """Fast endpoint: returns title + duration using cheap yt-dlp --print call."""
    data = request.get_json(force=True)
    source = data.get("source")
    raw_url = data.get("url", "").strip()

    if not raw_url:
        return jsonify(error="no url provided"), 400
    if source not in ("youtube", "ia"):
        return jsonify(error="source must be youtube or ia"), 400

    try:
        if source == "youtube":
            title, duration = downloader.resolve_youtube_oembed(raw_url)
        else:
            identifier = downloader.parse_ia_identifier(raw_url)
            if not identifier:
                return jsonify(error=f"not a valid IA identifier: {raw_url}"), 400
            title, duration = downloader.resolve_ia_metadata(identifier)
        return jsonify(title=title, duration_seconds=duration, length=classify_length(duration))
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json(force=True)
    source = data.get("source")
    raw_url = data.get("url", "").strip()

    if not raw_url:
        return jsonify(error="no url provided"), 400
    if source not in ("youtube", "ia"):
        return jsonify(error="source must be youtube or ia"), 400

    try:
        if source == "youtube":
            metadata = downloader.resolve_youtube_rich_metadata(raw_url)
        else:
            identifier = downloader.parse_ia_identifier(raw_url)
            if not identifier:
                return jsonify(error=f"not a valid IA identifier: {raw_url}"), 400
            metadata = downloader.resolve_ia_rich_metadata(identifier)

        existing_tags = db.get_all_tags()
        result = analyzer.classify(metadata, existing_tags=existing_tags)
        w = metadata.get("width")
        h = metadata.get("height")
        is_square = bool(w and h and 0.8 <= w / h <= 1.25)
        return jsonify(
            title=metadata["title"],
            duration_seconds=metadata.get("duration_seconds"),
            category=result["category"],
            is_new_category=result.get("is_new_category", False),
            length=result["length"],
            reasoning=result["reasoning"],
            is_square=is_square,
            suggested_tags=result.get("suggested_tags", []),
        )
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json(force=True)

    source = data.get("source")          # 'youtube', 'ia', 'playlist_file'
    urls = data.get("urls", [])          # list of URL strings
    category = data.get("category", "")
    length = data.get("length", "auto")  # 'auto', 'short', 'medium', 'long'
    is_playlist = data.get("playlist", False)
    crop_sides = bool(data.get("crop_sides", False))
    tags = [t for t in (data.get("tags") or []) if re.match(r'^[a-z][a-z0-9_]*$', t)]

    if source not in ("youtube", "ia", "playlist_file"):
        return jsonify(error="source must be youtube, ia, or playlist_file"), 400
    if not re.match(r'^[a-z][a-z0-9_]*$', category):
        return jsonify(error=f"invalid category name: {category}"), 400
    if length not in ("auto", *LENGTHS):
        return jsonify(error="length must be auto, short, medium, or long"), 400
    if not urls:
        return jsonify(error="no urls provided"), 400

    if category not in db.get_all_categories():
        db.add_user_category(category)
    if tags:
        db.ensure_tags_exist(tags)

    job_ids = []

    for url in urls:
        url = url.strip()
        if not url:
            continue

        if source == "youtube":
            if is_playlist:
                entries = downloader.expand_youtube_playlist(url)
                if not entries:
                    return jsonify(error=f"could not expand playlist: {url}"), 400
                for video_url, title, duration in entries:
                    resolved_length = length if length != "auto" else classify_length(duration)
                    jid = db.insert_job(video_url, title, "youtube", category, resolved_length, crop_sides, tags)
                    job_ids.append(jid)
            else:
                if length == "auto":
                    try:
                        title, duration = downloader.resolve_youtube_metadata(url)
                        resolved_length = classify_length(duration)
                    except Exception:
                        log.exception("yt metadata lookup failed for %s", url)
                        return jsonify(
                            error="could not fetch video metadata; pick a length manually"
                        ), 400
                else:
                    title, _ = downloader.resolve_youtube_metadata(url)
                    resolved_length = length
                jid = db.insert_job(url, title, "youtube", category, resolved_length, crop_sides, tags)
                job_ids.append(jid)

        elif source == "ia":
            identifier = downloader.parse_ia_identifier(url)
            if not identifier:
                return jsonify(error=f"not a valid IA identifier or URL: {url}"), 400
            title, duration = downloader.resolve_ia_metadata(identifier)
            resolved_length = length if length != "auto" else classify_length(duration)
            jid = db.insert_job(identifier, title, "ia", category, resolved_length, crop_sides, tags)
            job_ids.append(jid)

        elif source == "playlist_file":
            # urls here are individual video URLs parsed client-side from the file
            if length == "auto":
                try:
                    title, duration = downloader.resolve_youtube_metadata(url)
                    resolved_length = classify_length(duration)
                except Exception:
                    # Best-effort: bulk playlist imports keep going on per-row failure.
                    log.warning("yt metadata lookup failed for %s; defaulting to medium", url)
                    title, resolved_length = url, "medium"
            else:
                title, resolved_length = url, length
            jid = db.insert_job(url, title, "youtube", category, resolved_length, crop_sides, tags)
            job_ids.append(jid)

    return jsonify(job_ids=job_ids, queued=len(job_ids))


@app.route("/api/queue")
def api_queue():
    return jsonify(db.get_queue())


@app.route("/api/recent")
def api_recent():
    return jsonify(db.get_recent())


@app.route("/api/job/<int:job_id>/log")
def api_job_log(job_id):
    job = db.get_job(job_id)
    if not job:
        return jsonify(error="job not found"), 404
    log_path = job.get("log_path")
    if not log_path or not os.path.exists(log_path):
        return jsonify(lines=[])
    tail = int(request.args.get("tail", 40))
    with open(log_path) as f:
        lines = f.readlines()
    return jsonify(lines=[l.rstrip() for l in lines[-tail:]])


@app.route("/api/job/<int:job_id>/purge", methods=["POST"])
def api_job_purge(job_id):
    """Cancel if running, delete all pipeline files, remove from DB."""
    job = db.get_job(job_id)
    if not job:
        return jsonify(error="job not found"), 404
    # Cancel first if still in flight
    if job["status"] in ("running", "pending") and job.get("pid"):
        try:
            os.kill(job["pid"], 15)
        except ProcessLookupError:
            pass
    # Delete remote/local files
    result = downloader.purge_job_files(job)
    db.delete_job(job_id)
    return jsonify(ok=True, **result)


@app.route("/api/job/<int:job_id>/cancel", methods=["POST"])
def api_job_cancel(job_id):
    job = db.get_job(job_id)
    if not job:
        return jsonify(error="job not found"), 404
    if job["status"] == "running" and job.get("pid"):
        try:
            os.kill(job["pid"], 15)  # SIGTERM
        except ProcessLookupError:
            pass
    db.mark_cancelled(job_id)
    return jsonify(ok=True)


# ─── Media manager ───────────────────────────────────────────────────────────

def _valid_cat(c):
    return bool(re.match(r'^[a-z][a-z0-9_]*$', c or ""))

def _valid_len(l):
    return bool(re.match(r'^[a-z][a-z0-9_]*$', l or ""))

def _valid_fname(f):
    return bool(f) and f == posixpath.basename(f) and ".." not in f


@app.route("/api/media")
def api_media_list():
    category = request.args.get("category") or None
    length   = request.args.get("length")   or None
    try:
        limit = int(request.args.get("limit") or 0)
    except ValueError:
        limit = 0
    if category and not _valid_cat(category):
        return jsonify(error="invalid category"), 400
    if length and not _valid_len(length):
        return jsonify(error="invalid length"), 400
    try:
        files = downloader.list_zikzak_media(category, length)
        if limit > 0:
            files = files[:limit]
        tags_map = db.get_tags_by_category(category)
        for f in files:
            key = (f["category"], f["length"], f["filename"])
            f["tags"] = tags_map.get(key, [])
        return jsonify(files)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.route("/api/media/probe", methods=["POST"])
def api_media_probe():
    d = request.get_json(force=True)
    cat, leng, fname = d.get("category",""), d.get("length",""), d.get("filename","")
    if not _valid_cat(cat) or not _valid_len(leng) or not _valid_fname(fname):
        return jsonify(error="invalid params"), 400
    try:
        return jsonify(downloader.probe_zikzak_file(cat, leng, fname))
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.route("/api/media/delete", methods=["POST"])
def api_media_delete():
    d = request.get_json(force=True)
    cat, leng, fname = d.get("category",""), d.get("length",""), d.get("filename","")
    if not _valid_cat(cat) or not _valid_len(leng) or not _valid_fname(fname):
        return jsonify(error="invalid params"), 400
    try:
        downloader.delete_media_file(cat, leng, fname)
        return jsonify(ok=True)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.route("/api/media/move", methods=["POST"])
def api_media_move():
    d = request.get_json(force=True)
    cat, leng, fname = d.get("category",""), d.get("length",""), d.get("filename","")
    to_cat  = d.get("to_category","")
    to_leng = d.get("to_length","")
    if not all([_valid_cat(cat), _valid_len(leng), _valid_fname(fname),
                _valid_cat(to_cat), _valid_len(to_leng)]):
        return jsonify(error="invalid params"), 400
    if cat == to_cat and leng == to_leng:
        return jsonify(error="source and destination are the same"), 400
    try:
        downloader.move_media_file(cat, leng, fname, to_cat, to_leng)
        return jsonify(ok=True)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    threading.Thread(target=worker_loop, daemon=True).start()
    threading.Thread(target=downloader.pipeline_poller_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
