"""
Misc category cleanup:
  - blade_runner (1 file) → music/long, tag blade_runner
  - music_videos (2 files) → music/short, tag music_video
  - gaming_moody (empty) → remove dirs, mark tag_only
  - 0s, 70s (empty) → remove dirs, mark tag_only
Run on zikzak: python3 migrate_misc.py
"""
import os, json, subprocess, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"


def ffprobe_meta(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", path],
        capture_output=True, text=True, timeout=30,
    )
    d = json.loads(r.stdout)
    fmt = d.get("format", {})
    vid = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    dur = None
    for src in (fmt, vid):
        try:
            dur = float(src.get("duration") or 0) or None
            if dur:
                break
        except Exception:
            pass
    return {
        "duration_secs": dur,
        "width": vid.get("width"),
        "height": vid.get("height"),
        "bitrate_kbps": int(fmt.get("bit_rate", 0)) // 1000 or None,
        "filesize_bytes": os.path.getsize(path),
    }


def rmtree_empty(path):
    for dp, dns, fns in os.walk(path, topdown=False):
        if not os.listdir(dp):
            os.rmdir(dp)
    if os.path.isdir(path) and not os.listdir(path):
        os.rmdir(path)


# 1. blade_runner → music/long
fname = "You Look Lonely： Ryan Gosling Synthwave Drive.mp4"
src = os.path.join(MEDIA, "blade_runner", "long", fname)
dst = os.path.join(MEDIA, "music", "long", fname)
if os.path.exists(src):
    shutil.move(src, dst)
    print(f"moved: {fname}")
else:
    print(f"WARN not found: {src}")
cur.execute("UPDATE media_files SET category='music', subdir='long' WHERE id=4")
cur.execute("INSERT INTO media_file_categories VALUES (4,'music',TRUE) ON CONFLICT DO NOTHING")
cur.execute("INSERT INTO media_file_categories VALUES (4,'blade_runner',FALSE) ON CONFLICT DO NOTHING")
cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name='blade_runner'")
print("blade_runner: updated DB")

# 2. music_videos → music/short
cur.execute("INSERT INTO categories (name,is_tag_only) VALUES ('music_video',TRUE) ON CONFLICT DO NOTHING")
cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name='music_videos'")

for fname in [
    "Liquido_-_Narcotic_Official_Video.webm",
    "Junior_Senior_-_Move_Your_Feet_Official_music_video_HD.mp4",
]:
    src = os.path.join(MEDIA, "music_videos", "short", fname)
    dst = os.path.join(MEDIA, "music", "short", fname)
    if os.path.exists(src):
        shutil.move(src, dst)
    m = ffprobe_meta(dst)
    cur.execute("""
        INSERT INTO media_files
            (category, subdir, filename, filesize_bytes, duration_secs, width, height, bitrate_kbps)
        VALUES ('music','short',%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING RETURNING id
    """, (fname, m["filesize_bytes"], m["duration_secs"], m["width"], m["height"], m["bitrate_kbps"]))
    row = cur.fetchone()
    if row:
        fid = row["id"]
        cur.execute("INSERT INTO media_file_categories VALUES (%s,'music',TRUE) ON CONFLICT DO NOTHING", (fid,))
        cur.execute("INSERT INTO media_file_categories VALUES (%s,'music_video',FALSE) ON CONFLICT DO NOTHING", (fid,))
        print(f"music_video inserted id={fid}: {fname}")

# 3. Mark empty categories tag_only and remove dirs
for cat in ["gaming_moody", "0s", "70s", "music_videos"]:
    cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name=%s", (cat,))
    rmtree_empty(os.path.join(MEDIA, cat))
    print(f"cleaned up: {cat}")

rmtree_empty(os.path.join(MEDIA, "blade_runner"))

pg.commit()

cur.execute("SELECT COUNT(*) AS n FROM media_files WHERE category='music'")
print(f"\nTotal music files: {cur.fetchone()['n']}")
cur.execute("""
    SELECT mfc.category_name, COUNT(*) AS n
    FROM media_file_categories mfc
    JOIN categories c ON c.name=mfc.category_name AND c.is_tag_only
    GROUP BY mfc.category_name ORDER BY n DESC
""")
print("Tag counts:")
for row in cur.fetchall():
    print(f"  {row['category_name']}: {row['n']}")

cur.close()
pg.close()
