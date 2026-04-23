#!/usr/bin/env python3
"""
intake.py — Media Intake Web App for Max Headroom Broadcast Network
Accepts YouTube URLs, Internet Archive identifiers, and playlist files.
Queues downloads into /mnt/incoming/ for the existing cron pipeline.
"""

import os
import re
import threading
import time

from flask import Flask, request, jsonify, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

import db
import downloader
import analyzer
from config import CATEGORIES, LENGTHS, PORT, classify_length

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

def _all_categories():
    extra = [c for c in db.get_user_categories() if c not in CATEGORIES]
    return CATEGORIES + extra


@app.route("/")
def index():
    return render_template("index.html", categories=_all_categories(), lengths=LENGTHS, base_path=BASE_PATH)


@app.route("/api/categories")
def api_categories():
    return jsonify(_all_categories())


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

        result = analyzer.classify(metadata)
        return jsonify(
            title=metadata["title"],
            duration_seconds=metadata.get("duration_seconds"),
            category=result["category"],
            is_new_category=result.get("is_new_category", False),
            length=result["length"],
            reasoning=result["reasoning"],
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

    if source not in ("youtube", "ia", "playlist_file"):
        return jsonify(error="source must be youtube, ia, or playlist_file"), 400
    if not re.match(r'^[a-z][a-z0-9_]*$', category):
        return jsonify(error=f"invalid category name: {category}"), 400
    if length not in ("auto", *LENGTHS):
        return jsonify(error="length must be auto, short, medium, or long"), 400
    if not urls:
        return jsonify(error="no urls provided"), 400

    if category not in CATEGORIES:
        db.add_user_category(category)

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
                    jid = db.insert_job(video_url, title, "youtube", category, resolved_length)
                    job_ids.append(jid)
            else:
                if length == "auto":
                    try:
                        title, duration = downloader.resolve_youtube_metadata(url)
                        resolved_length = classify_length(duration)
                    except Exception:
                        return jsonify(
                            error="could not fetch video metadata; pick a length manually"
                        ), 400
                else:
                    title, _ = downloader.resolve_youtube_metadata(url)
                    resolved_length = length
                jid = db.insert_job(url, title, "youtube", category, resolved_length)
                job_ids.append(jid)

        elif source == "ia":
            identifier = downloader.parse_ia_identifier(url)
            if not identifier:
                return jsonify(error=f"not a valid IA identifier or URL: {url}"), 400
            title, duration = downloader.resolve_ia_metadata(identifier)
            resolved_length = length if length != "auto" else classify_length(duration)
            jid = db.insert_job(identifier, title, "ia", category, resolved_length)
            job_ids.append(jid)

        elif source == "playlist_file":
            # urls here are individual video URLs parsed client-side from the file
            if length == "auto":
                try:
                    title, duration = downloader.resolve_youtube_metadata(url)
                    resolved_length = classify_length(duration)
                except Exception:
                    title, resolved_length = url, "medium"
            else:
                title, resolved_length = url, length
            jid = db.insert_job(url, title, "youtube", category, resolved_length)
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
        abort(404)
    log_path = job.get("log_path")
    if not log_path or not os.path.exists(log_path):
        return jsonify(lines=[])
    tail = int(request.args.get("tail", 40))
    with open(log_path) as f:
        lines = f.readlines()
    return jsonify(lines=[l.rstrip() for l in lines[-tail:]])


@app.route("/api/job/<int:job_id>/cancel", methods=["POST"])
def api_job_cancel(job_id):
    job = db.get_job(job_id)
    if not job:
        abort(404)
    if job["status"] == "running" and job.get("pid"):
        try:
            os.kill(job["pid"], 15)  # SIGTERM
        except ProcessLookupError:
            pass
    db.mark_cancelled(job_id)
    return jsonify(ok=True)


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
