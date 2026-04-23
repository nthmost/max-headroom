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

from flask import Flask, request, jsonify, render_template, abort

import db
import downloader
from config import API_KEY, CATEGORIES, LENGTHS, PORT, classify_length

app = Flask(__name__)


# ─── Auth ───────────────────────────────────────────────────────────────────

def check_auth():
    key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not key:
        key = request.args.get("key", "")
    if key != API_KEY:
        abort(401)


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
    return render_template("index.html", categories=CATEGORIES, lengths=LENGTHS)


@app.route("/api/categories")
def api_categories():
    check_auth()
    return jsonify(CATEGORIES)


@app.route("/api/submit", methods=["POST"])
def api_submit():
    check_auth()
    data = request.get_json(force=True)

    source = data.get("source")          # 'youtube', 'ia', 'playlist_file'
    urls = data.get("urls", [])          # list of URL strings
    category = data.get("category", "")
    length = data.get("length", "auto")  # 'auto', 'short', 'medium', 'long'
    is_playlist = data.get("playlist", False)

    if source not in ("youtube", "ia", "playlist_file"):
        return jsonify(error="source must be youtube, ia, or playlist_file"), 400
    if category not in CATEGORIES:
        return jsonify(error=f"unknown category: {category}"), 400
    if length not in ("auto", *LENGTHS):
        return jsonify(error="length must be auto, short, medium, or long"), 400
    if not urls:
        return jsonify(error="no urls provided"), 400

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
    check_auth()
    return jsonify(db.get_queue())


@app.route("/api/recent")
def api_recent():
    check_auth()
    return jsonify(db.get_recent())


@app.route("/api/job/<int:job_id>/log")
def api_job_log(job_id):
    check_auth()
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
    check_auth()
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
